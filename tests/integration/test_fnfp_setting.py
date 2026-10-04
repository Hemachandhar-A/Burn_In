"""Session I3 Part 4b: a change to the FN:FP cost ratio through the real dual sign-off route changes the thresholds the NEXT analysis uses.

Uploads the same finished lot twice (different lot ids, same readings): once at the default ratio, once after propose + sign-off by two
distinct accounts. A higher ratio gives lower cut-offs, so the second analysis flags at least as many parts, and strictly more here."""
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DEMO = Path(__file__).resolve().parent.parent.parent / "demo_data"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api.main import app
    from ingestion import store
    from storage import database, repository

    engine = create_engine(f"sqlite:///{tmp_path / 'fnfp.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    monkeypatch.setattr(repository, "SessionLocal", session_local)
    repository.init_db()
    store.clear()
    repository.save_account("a.sharma", "A. Sharma", "Quality Engineer", PasswordHasher().hash("1234"))
    repository.save_account("r.mehta", "R. Mehta", "Reliability Engineer", PasswordHasher().hash("5678"))
    monkeypatch.delenv("MODULE_A_SCORING", raising=False)
    yield TestClient(app)
    store.clear()


def _h(client, account, pin):
    token = client.post("/auth/login", json={"account_id": account, "pin": pin}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _upload(client, headers, lot_id):
    r = client.post("/lots", headers=headers, data={"lot_id": lot_id, "part_number": "DEMO-PN", "manufacturer": "Northvale Semiconductor",
                                                    "date_code": "2601", "account_id": "a.sharma"},
                    files={"file": ("full_lot.csv", (DEMO / "full_lot.csv").read_bytes(), "text/csv")})
    assert r.status_code == 200, r.text
    lot = client.get(f"/lots/{lot_id}", headers=headers).json()
    assert lot["disposition"]["status"] == "COMPLETE"
    return lot


def _flagged_a_tiers(lot):
    return sum(a["verdict"] != "PASS" for a in lot["assessments"])


def _set_ratio(client, ratio):
    a, b = _h(client, "a.sharma", "1234"), _h(client, "r.mehta", "5678")
    assert client.post("/settings/propose", json={"field": "fn_fp_cost_ratio", "proposed_value": ratio}, headers=a).status_code == 200
    ok = client.post("/settings/signoff", json={"field": "fn_fp_cost_ratio"}, headers=b)
    assert ok.status_code == 200 and ok.json()["fn_fp_cost_ratio"] == ratio


def test_a_signed_off_ratio_changes_the_next_analysis(client):
    a = _h(client, "a.sharma", "1234")
    default_lot = _upload(client, a, "RATIO-DEFAULT")
    _set_ratio(client, 50.0)
    high_lot = _upload(client, a, "RATIO-50")
    _set_ratio(client, 2.0)
    low_lot = _upload(client, a, "RATIO-2")
    n_default, n_high, n_low = (_flagged_a_tiers(x) for x in (default_lot, high_lot, low_lot))
    assert n_low <= n_default <= n_high and n_low < n_high
    # the earlier analysis is a stored result: not recomputed by the later change
    assert _flagged_a_tiers(client.get("/lots/RATIO-DEFAULT", headers=a).json()) == n_default


def test_unsupported_ratios_are_rejected_at_the_proposal(client):
    a = _h(client, "a.sharma", "1234")
    for bad in (0, -5, 1.5, 51, 1000):
        r = client.post("/settings/propose", json={"field": "fn_fp_cost_ratio", "proposed_value": bad}, headers=a)
        assert r.status_code == 400 and "between 2 and 50" in r.json()["detail"], (bad, r.text)
    assert client.get("/settings", headers=a).json()["pending_changes"] == []
    ok = client.post("/settings/propose", json={"field": "fn_fp_cost_ratio", "proposed_value": 2}, headers=a)
    assert ok.status_code == 200


def test_the_pda_threshold_setting_reaches_the_analysis_too(client):
    a = _h(client, "a.sharma", "1234")
    base = _upload(client, a, "PDA-DEFAULT")
    assert base["disposition"]["verdict"] in ("REJECT", "HOLD", "ACCEPT")
    a2, b2 = _h(client, "a.sharma", "1234"), _h(client, "r.mehta", "5678")
    assert client.post("/settings/propose", json={"field": "pda_threshold", "proposed_value": 0.99}, headers=a2).status_code == 200
    assert client.post("/settings/signoff", json={"field": "pda_threshold"}, headers=b2).status_code == 200
    relaxed = _upload(client, a, "PDA-99")
    assert relaxed["disposition"]["verdict"] != "REJECT"


def test_the_cutoffs_an_analysis_used_are_stored_with_it_and_shown_in_the_work_order(client):
    a = _h(client, "a.sharma", "1234")
    default_lot = _upload(client, a, "CUT-DEFAULT")
    from module_a.fnfp import thresholds_for_ratio

    assert default_lot["module_a_cutoffs"] == {"review": 2.956, "reject": 3.419}
    wo = client.post("/lots/CUT-DEFAULT/dpa-work-order", headers=a)
    assert wo.status_code == 200 and "flag threshold 2.96" in wo.json()["recommendations"][0]["reason"]
    _set_ratio(client, 50.0)
    review50, reject50 = thresholds_for_ratio(50.0)
    lot50 = _upload(client, a, "CUT-50")
    assert lot50["module_a_cutoffs"] == {"review": pytest.approx(review50), "reject": pytest.approx(reject50)}
    reason50 = client.post("/lots/CUT-50/dpa-work-order", headers=a).json()["recommendations"][0]["reason"]
    assert f"flag threshold {review50:.2f}" in reason50
    # the earlier lot's work order still quotes the cut-off ITS analysis used, not today's setting
    assert "flag threshold 2.96" in client.post("/lots/CUT-DEFAULT/dpa-work-order", headers=a).json()["recommendations"][0]["reason"]
