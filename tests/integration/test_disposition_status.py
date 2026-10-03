"""F24 Part 2 (E10): the disposition status state machine, required rationale, concurrency, immutability.
T7 exhaustive truth table, T8 empty rationale, T9 concurrent dual REJECT, T10 same-account REJECT, T11 timing flag,
T12 immutable history."""
import itertools
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts import AnalysisResults, LotDisposition, RiskAssessment
from identity.status import derive_status, disposition_status_for
from storage import repository
from storage.repository import (
    query_disposition_signoffs, save_account, save_analysis_run, save_disposition_signoff, save_project,
)

hasher = PasswordHasher()
ACCOUNTS = ("a.sharma", "r.mehta")
VERDICTS = ("ACCEPT", "HOLD", "REJECT")
COMPONENTS = [f"comp{i}" for i in range(30)]


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from storage import database

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    monkeypatch.setattr(repository, "SessionLocal", session_local)
    repository.init_db()
    save_account("a.sharma", "A. Sharma", "Quality Engineer", hasher.hash("1234"))
    save_account("r.mehta", "R. Mehta", "Reliability Engineer", hasher.hash("5678"))
    save_project("proj1", "lot_001", "PN123", datetime.now(UTC), "a.sharma")
    results = AnalysisResults(
        assessments=[
            RiskAssessment(component_id=c, lot_id="lot_001", verdict="REJECT", module_a_rank=1.0, module_b_rank=1.0,
                           worst_parameter="leakage", module_a_ran=True, module_b_ran=True, predicted_168h=None,
                           actual_168h=None, explanation_sentence=None)
            for c in COMPONENTS
        ],
        disposition=LotDisposition(lot_id="lot_001", status="COMPLETE", pda_result=1.0, verdict="REJECT", is_forecast=False),
    )
    save_analysis_run("proj1", {}, results)


@pytest.fixture
def client():
    from fusion.router import router as fusion_router
    from identity.router import router as identity_router
    from storage.router import router as storage_router

    app = FastAPI()
    for r in (identity_router, fusion_router, storage_router):
        app.include_router(r)
    return TestClient(app)


def _headers(client, account_id):
    pin = {"a.sharma": "1234", "r.mehta": "5678"}[account_id]
    token = client.post("/auth/login", json={"account_id": account_id, "pin": pin}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _run_id():
    return repository.query_project_data("proj1")[-1].analysis_run_id


def _post(client, component, account_id, verdict, rationale="a reason", run_id=None):
    return client.post(
        f"/parts/{component}/disposition?project_id=proj1&analysis_run_id={run_id or _run_id()}",
        json={"verdict": verdict, "rationale": rationale}, headers=_headers(client, account_id),
    )


def _status(client, component):
    return client.get(f"/parts/{component}", headers=_headers(client, "a.sharma")).json()["disposition_status"]


def expected_status(sequence):
    """The Lead's rule, written out independently of identity.status: latest decision per account counts."""
    latest = {}
    for account, verdict in sequence:
        latest[account] = verdict
    rejecters = [a for a, v in latest.items() if v == "REJECT"]
    if not latest:
        return "NONE"
    if len(rejecters) >= 2:
        return "REJECT_FINAL"
    if len(set(latest.values())) > 1:
        return "CONFLICT"
    return {"ACCEPT": "ACCEPT_RECORDED", "HOLD": "HOLD_RECORDED", "REJECT": "REJECT_PENDING_SECOND"}[next(iter(latest.values()))]


ALL_STEPS = list(itertools.product(ACCOUNTS, VERDICTS))  # 6 possible sign-offs
ALL_SEQUENCES = [s for n in range(0, 4) for s in itertools.product(ALL_STEPS, repeat=n)]  # 1 + 6 + 36 + 216


def test_t7_truth_table_pure_function(capsys):
    assert len(ALL_SEQUENCES) == 259
    for seq in ALL_SEQUENCES:
        assert derive_status(list(seq)) == expected_status(seq), seq
    sample = [
        (), (("a.sharma", "ACCEPT"),), (("a.sharma", "HOLD"),), (("a.sharma", "REJECT"),),
        (("a.sharma", "REJECT"), ("r.mehta", "REJECT")), (("a.sharma", "REJECT"), ("r.mehta", "ACCEPT")),
        (("a.sharma", "REJECT"), ("a.sharma", "ACCEPT")),
        (("a.sharma", "REJECT"), ("r.mehta", "ACCEPT"), ("r.mehta", "REJECT")),
        (("a.sharma", "ACCEPT"), ("r.mehta", "HOLD")),
    ]
    with capsys.disabled():
        print("\nT7 truth-table sample (sequence of (account, verdict) -> status):")
        for seq in sample:
            print("  ", [f"{a}:{v}" for a, v in seq], "->", derive_status(list(seq)))
    assert derive_status(list(sample[7])) == "REJECT_FINAL"


def test_t7_truth_table_from_stored_signoffs():
    """Every sequence of up to 3 sign-offs, stored through the repository (one part per sequence) and read back by
    the status function the part-detail route uses."""
    for i, seq in enumerate(ALL_SEQUENCES):
        for account, verdict in seq:
            save_disposition_signoff("proj1", f"seq{i}", "run-x", account, verdict, "r")
        assert disposition_status_for("proj1", f"seq{i}", "run-x") == expected_status(seq), seq


def test_t7_status_on_the_route_follows_the_rule(client):
    steps = [("a.sharma", "HOLD", "HOLD_RECORDED"), ("r.mehta", "ACCEPT", "CONFLICT"),
             ("r.mehta", "HOLD", "HOLD_RECORDED"), ("a.sharma", "REJECT", "CONFLICT"),
             ("r.mehta", "REJECT", "REJECT_FINAL")]
    assert _status(client, "comp0") == "NONE"
    for account, verdict, status in steps:
        assert _post(client, "comp0", account, verdict).status_code == 200
        assert _status(client, "comp0") == status, (account, verdict)
    # a single REJECT is pending its second sign-off
    assert _post(client, "comp1", "a.sharma", "REJECT").status_code == 200
    assert _status(client, "comp1") == "REJECT_PENDING_SECOND"


def test_t7_a_signoff_on_another_analysis_run_does_not_count():
    save_disposition_signoff("proj1", "comp2", "older-run", "a.sharma", "REJECT", "r")
    save_disposition_signoff("proj1", "comp2", "older-run", "r.mehta", "REJECT", "r")
    assert disposition_status_for("proj1", "comp2", "older-run") == "REJECT_FINAL"
    assert disposition_status_for("proj1", "comp2", "newer-run") == "NONE"


@pytest.mark.parametrize("rationale", ["", " ", "   \t\n  "])
def test_t8_empty_or_whitespace_rationale_is_422_and_writes_nothing(client, rationale):
    for verdict in VERDICTS:
        r = _post(client, "comp3", "a.sharma", verdict, rationale=rationale)
        assert r.status_code == 422 and "rationale" in r.json()["detail"].lower()
    assert query_disposition_signoffs(project_id="proj1", component_id="comp3") == []
    assert _status(client, "comp3") == "NONE"


def test_t8_rationale_is_stored_trimmed(client):
    assert _post(client, "comp3", "a.sharma", "HOLD", rationale="  needs a retest  ").status_code == 200
    assert query_disposition_signoffs(project_id="proj1", component_id="comp3")[0].rationale == "needs a retest"


def test_t9_concurrent_first_and_second_reject_end_final_with_two_records(client):
    run_id = _run_id()
    for rep in range(20):
        component = f"comp{10 + rep}"
        barrier = threading.Barrier(2)

        def submit(account, component=component, barrier=barrier):
            barrier.wait()
            return _post(client, component, account, "REJECT", run_id=run_id).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(submit, ACCOUNTS))
        assert codes == [200, 200], (rep, codes)
        records = query_disposition_signoffs(project_id="proj1", component_id=component)
        assert len(records) == 2 and {r.account_id for r in records} == set(ACCOUNTS)
        assert _status(client, component) == "REJECT_FINAL"


def test_t10_same_account_second_reject_is_the_existing_400(client):
    assert _post(client, "comp0", "a.sharma", "REJECT").status_code == 200
    r = _post(client, "comp0", "a.sharma", "REJECT")
    assert r.status_code == 400 and "two distinct account IDs" in r.json()["detail"]
    assert len(query_disposition_signoffs(project_id="proj1", component_id="comp0")) == 1
    assert _status(client, "comp0") == "REJECT_PENDING_SECOND"


def test_t11_timing_flag_for_two_rejects_under_two_minutes_and_never_config_change(client):
    assert _post(client, "comp0", "a.sharma", "REJECT").status_code == 200
    assert _post(client, "comp0", "r.mehta", "REJECT").status_code == 200
    events = client.get("/projects/proj1/events", headers=_headers(client, "a.sharma")).json()
    assert [e["event_type"] for e in events].count("timing_flag") == 1
    assert not any(e["event_type"] == "config_change" for e in events)


def test_t12_history_is_immutable_a_correction_adds_a_record(client):
    assert _post(client, "comp0", "a.sharma", "ACCEPT", rationale="first view").status_code == 200
    before = query_disposition_signoffs(project_id="proj1", component_id="comp0")
    assert _post(client, "comp0", "a.sharma", "HOLD", rationale="on reflection").status_code == 200
    after = query_disposition_signoffs(project_id="proj1", component_id="comp0")
    assert len(after) == len(before) + 1
    assert (after[0].verdict, after[0].rationale, after[0].timestamp) == (before[0].verdict, before[0].rationale, before[0].timestamp)
    history = client.get("/parts/comp0", headers=_headers(client, "a.sharma")).json()["disposition_history"]
    assert [h["verdict"] for h in history] == ["ACCEPT", "HOLD"]
    assert _status(client, "comp0") == "HOLD_RECORDED"  # the latest decision of the account counts
