"""E13 steps 6-8 (Block 4a Part 3): GET /settings/corrective-status - live-computed on every call,
nothing stored, nothing to dismiss. Status uses CorrectiveStatusResponse's actual frozen Literal
("OK" / "CEILING_EXCEEDED" / "INSUFFICIENT_DATA") - the pasted work packet's prose ("not active" /
"within ceiling" / "ceiling exceeded") describes the same three states informally; contracts.py is
read-only (AGENTS.md rule 3) and already names these three exactly, so no contract change was needed
or made. INSUFFICIENT_DATA fires strictly below min_confirmed_outcomes_for_ceiling (default 10,
Good+Defective, Unknown excluded) regardless of the FN rate. The endpoint changes nothing itself.
"""
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts import AnalysisResults, LotDisposition, RiskAssessment
from identity.auth import create_access_token
from storage import repository
from storage.repository import save_account, save_analysis_run, save_confirmed_outcome, save_project


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    from storage import database
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    test_engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(repository, "SessionLocal", TestSessionLocal)

    repository.init_db()
    save_account("account1", "User 1", "Quality Engineer", "$argon2id$v=19$m=65536,t=3,p=4$x$y")
    save_account("account2", "User 2", "Reliability Engineer", "$argon2id$v=19$m=65536,t=3,p=4$x$y")


def _make_results(component_id: str, verdict: str) -> AnalysisResults:
    return AnalysisResults(
        assessments=[
            RiskAssessment(
                component_id=component_id, lot_id="lot_001", verdict=verdict,
                module_a_rank=1.0, module_b_rank=1.0, worst_parameter="leakage",
                module_a_ran=True, module_b_ran=True, predicted_168h=None, actual_168h=None,
                explanation_sentence=None,
            )
        ],
        disposition=LotDisposition(lot_id="lot_001", status="COMPLETE", pda_result=0.0, verdict="REJECT",
                                    is_forecast=False),
    )


def _seed_outcome(project_id: str, component_id: str, verdict: str, confirmed_outcome: str) -> None:
    save_project(project_id, "lot_001", "PN123", datetime.now(UTC), "account1")
    run = save_analysis_run(project_id, {}, _make_results(component_id, verdict))
    save_confirmed_outcome(
        project_id=project_id, component_id=component_id, analysis_run_id=run.analysis_run_id,
        account_id="account1", confirmed_outcome=confirmed_outcome,
    )


@pytest.fixture
def client():
    from capa.router import planned_router

    app = FastAPI()
    app.include_router(planned_router)
    return TestClient(app)


@pytest.fixture
def auth_headers():
    token = create_access_token("account1", "Quality Engineer")
    return {"Authorization": f"Bearer {token}"}


def test_below_ten_outcomes_is_insufficient_data_even_at_100_percent_fn_rate(client, auth_headers):
    # 5 Confirmed Defective outcomes, all missed (PASS) -> a 100% FN rate, but only 5 total outcomes.
    for i in range(5):
        _seed_outcome(f"proj{i}", f"comp{i}", "PASS", "Confirmed Defective")

    resp = client.get("/settings/corrective-status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "INSUFFICIENT_DATA"
    assert body["confirmed_outcome_count"] == 5


def test_exactly_ten_outcomes_is_active(client, auth_headers):
    for i in range(10):
        _seed_outcome(f"proj{i}", f"comp{i}", "PASS", "Confirmed Good")  # all fine, FP rate 0

    resp = client.get("/settings/corrective-status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["confirmed_outcome_count"] == 10
    assert body["status"] in ("OK", "CEILING_EXCEEDED")  # "active", not INSUFFICIENT_DATA


def test_ceiling_exceeded_once_fn_rate_crosses_the_default_5_percent_ceiling(client, auth_headers):
    # 10 Confirmed Defective outcomes, 1 missed (PASS) -> FN rate 10%, above the default 5% ceiling.
    for i in range(9):
        _seed_outcome(f"proj{i}", f"comp{i}", "REJECT", "Confirmed Defective")  # caught
    _seed_outcome("proj-miss", "comp-miss", "PASS", "Confirmed Defective")  # miss

    resp = client.get("/settings/corrective-status", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["confirmed_outcome_count"] == 10
    assert body["fn_rate"] == pytest.approx(0.1)
    assert body["status"] == "CEILING_EXCEEDED"


def test_status_recomputes_when_a_new_outcome_is_added(client, auth_headers):
    for i in range(10):
        _seed_outcome(f"proj{i}", f"comp{i}", "REJECT", "Confirmed Defective")  # all caught, FN rate 0

    resp1 = client.get("/settings/corrective-status", headers=auth_headers)
    assert resp1.json()["status"] == "OK"
    assert resp1.json()["fn_rate"] == pytest.approx(0.0)

    _seed_outcome("proj-new-miss", "comp-new-miss", "PASS", "Confirmed Defective")  # a new miss

    resp2 = client.get("/settings/corrective-status", headers=auth_headers)
    body2 = resp2.json()
    assert body2["confirmed_outcome_count"] == 11
    assert body2["fn_rate"] == pytest.approx(1 / 11)


def test_endpoint_writes_nothing(client, auth_headers):
    for i in range(10):
        _seed_outcome(f"proj{i}", f"comp{i}", "PASS", "Confirmed Good")

    from storage.repository import query_confirmed_outcomes, query_events, query_disposition_signoffs
    outcomes_before = len(query_confirmed_outcomes())
    events_before = len(query_events())
    signoffs_before = len(query_disposition_signoffs())

    client.get("/settings/corrective-status", headers=auth_headers)

    assert len(query_confirmed_outcomes()) == outcomes_before
    assert len(query_events()) == events_before
    assert len(query_disposition_signoffs()) == signoffs_before


def test_requires_auth(client):
    resp = client.get("/settings/corrective-status")
    assert resp.status_code in (401, 403)


def test_unknown_excluded_from_the_minimum_count(client, auth_headers):
    for i in range(9):
        _seed_outcome(f"proj{i}", f"comp{i}", "PASS", "Confirmed Good")
    _seed_outcome("proj-unknown", "comp-unknown", "PASS", "Unknown")  # would make 10 if miscounted

    resp = client.get("/settings/corrective-status", headers=auth_headers)
    body = resp.json()
    assert body["confirmed_outcome_count"] == 9
    assert body["status"] == "INSUFFICIENT_DATA"
