"""scripts/load_demo_lots.py: loads both demo lots through the real routes, idempotently, into whatever DB is configured."""
import pytest
from argon2 import PasswordHasher
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scripts import load_demo_lots as demo


@pytest.fixture
def db(tmp_path, monkeypatch):
    from ingestion import store
    from storage import database, repository

    engine = create_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    monkeypatch.setattr(repository, "SessionLocal", session_local)
    repository.init_db()
    store.clear()
    repository.save_account("a.sharma", "A. Sharma", "Quality Engineer", PasswordHasher().hash("1234"))
    yield
    store.clear()


def _headers(client):
    token = client.post("/auth/login", json={"account_id": "a.sharma", "pin": "1234"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_loads_both_lots_then_second_run_skips(db, capsys):
    assert demo.main([]) == 0
    first = capsys.readouterr().out
    assert f"loaded {demo.COMPLETE_LOT_ID}: status COMPLETE" in first
    assert f"loaded {demo.EARLY_LOT_ID}: status IN_PROGRESS" in first

    assert demo.main([]) == 0
    second = capsys.readouterr().out
    assert f"skipped {demo.COMPLETE_LOT_ID}" in second and f"skipped {demo.EARLY_LOT_ID}" in second
    assert "loaded" not in second


def test_lot_contents_match_the_seed_scan(db):
    from fastapi.testclient import TestClient

    from api.main import app

    assert demo.main([]) == 0
    client = TestClient(app)
    h = _headers(client)
    scan = demo.scan_complete_seed(demo.COMPLETE_SEED)
    assert demo.qualifies_complete(scan)
    done = client.get(f"/lots/{demo.COMPLETE_LOT_ID}", headers=h).json()
    assert done["disposition"]["status"] == "COMPLETE" and done["disposition"]["is_forecast"] is False
    assert done["disposition"]["verdict"] == scan["lot_verdict"]
    assert done["disposition"]["pda_result"] == pytest.approx(scan["pda"])
    assert sum(a["verdict"] != "PASS" for a in done["assessments"]) == scan["flagged"]

    early = client.get(f"/lots/{demo.EARLY_LOT_ID}", headers=h).json()
    assert early["disposition"]["status"] == "IN_PROGRESS" and early["disposition"]["is_forecast"] is True
    assert early["disposition"]["verdict"] in ("LOT_AT_RISK", "STOP_RUN_RECOMMENDED")
    assert sum(a["verdict"] == "REJECT" for a in early["assessments"]) >= demo.MIN_B_REJECT


def _row(**kw):
    base = {"status": "COMPLETE", "n_parts": 77, "flagged": 6, "a_reject": 3, "a_watch": 3, "lot_verdict": "REJECT",
            "pda": 0.05, "top": "X-0001", "worst": "iddq", "top_rows": True, "top_sentence": True, "any_reject_rows": True}
    base.update(kw)
    return base


def test_complete_selection_rules_v2():
    """demo-v2 criteria: COMPLETE, 77 parts, REJECT/HOLD lot, 4-10 flagged, >= 2 Module A REJECT, top part has MCD+ECOD rows + sentence."""
    assert demo.qualifies_complete(_row())
    assert not demo.qualifies_complete(_row(status="IN_PROGRESS"))
    assert not demo.qualifies_complete(_row(n_parts=60))
    assert not demo.qualifies_complete(_row(lot_verdict="ACCEPT"))
    assert demo.qualifies_complete(_row(lot_verdict="HOLD"))
    assert not demo.qualifies_complete(_row(flagged=3)) and not demo.qualifies_complete(_row(flagged=11))
    assert demo.qualifies_complete(_row(flagged=4)) and demo.qualifies_complete(_row(flagged=10))
    assert not demo.qualifies_complete(_row(a_reject=1))
    assert not demo.qualifies_complete(_row(top_rows=False))
    assert not demo.qualifies_complete(_row(top_sentence=False))


def test_chosen_seeds_satisfy_their_selection_rules():
    assert demo.qualifies(demo.scan_seed(demo.EARLY_SEED))
    assert demo.qualifies_complete(demo.scan_complete_seed(demo.COMPLETE_SEED))


def _golden_through_route(db, expect):
    import csv
    import io

    from fastapi.testclient import TestClient

    from api.main import app
    from harness.golden import golden_lot

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["component_id", "parameter", "checkpoint_hour", "value", "unit"])
    for r in golden_lot().readings:
        w.writerow([r.component_id, r.parameter, r.checkpoint_hour, r.value, r.unit])
    client = TestClient(app)
    h = _headers(client)
    up = client.post("/lots", headers=h, files={"file": ("g.csv", buf.getvalue().encode(), "text/csv")},
                     data={"lot_id": "GOLDEN-T", "part_number": "PN-GOLDEN", "manufacturer": "GOLDEN-MFR",
                           "date_code": "2601", "account_id": "a.sharma"})
    assert up.status_code == 200
    lot = client.get("/lots/GOLDEN-T", headers=h).json()
    d = lot["disposition"]
    expect(d, lot)
    print("golden through POST /lots:", d["verdict"], d["pda_result"], "REJECT parts:",
          sum(a["verdict"] == "REJECT" for a in lot["assessments"]))
    # F24 T3: the uA->nA scale problem (leakage, 1000x the generator's scale) no longer produces a Module B verdict:
    # every leakage forecast is declined with a reason, and no part is flagged by Module B anywhere in the lot.
    from contracts import to_module_b_input
    from features.compute import compute
    from ingestion.units import normalize_readings
    from module_b import predict
    from contracts import LotDataset

    readings, errors = normalize_readings(golden_lot().readings)
    assert not errors
    b = predict([to_module_b_input(f) for f in compute(
        LotDataset(lot_id="GOLDEN-T", part_number="PN-GOLDEN", status="COMPLETE", readings=readings, account_id="a"))])
    leak = [r for r in b if r.parameter == "leakage"]
    assert len(leak) == 77 and all(r.forecast_unavailable and r.unavailable_reason for r in leak)
    assert not any(r.exceeds_safety_slope for r in b)
    print("golden Module B REJECTs:", sum(bool(r.exceeds_safety_slope) for r in b), "leakage unavailable:", len(leak))
    return lot


def test_golden_lot_through_the_route_is_accept_by_default(db, monkeypatch):
    """demo-v2 (absolute scoring): GOLDEN-045 is the only REJECT; the decoys no longer flag, so 1/77 = 0.01299 < 0.05: ACCEPT."""
    monkeypatch.delenv("MODULE_A_SCORING", raising=False)

    def expect(d, lot):
        rejects = [a["component_id"] for a in lot["assessments"] if a["verdict"] == "REJECT"]
        assert rejects == ["GOLDEN-045"]
        assert d["verdict"] == "ACCEPT" and d["pda_result"] == pytest.approx(1 / 77)

    _golden_through_route(db, expect)


def test_golden_lot_through_the_route_is_hold_in_rank_mode(db, monkeypatch):
    """Legacy path (MODULE_A_SCORING=rank): the decoys flag too, 3/77 REJECT parts, PDA in (0.03, 0.05): HOLD."""
    monkeypatch.setenv("MODULE_A_SCORING", "rank")

    def expect(d, lot):
        assert d["verdict"] == "HOLD" and 0.03 < d["pda_result"] < 0.05
        assert sum(a["verdict"] == "REJECT" for a in lot["assessments"]) == 3  # PDA 3/77, from Module A

    _golden_through_route(db, expect)
