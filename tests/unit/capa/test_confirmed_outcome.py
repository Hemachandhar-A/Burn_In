"""E13 step 1 (Block 4a Part 1): POST /parts/{component_id}/confirmed-outcome.

Append-only - never touches disposition_signoffs. Links to project_id/component_id and the
analysis_run_id of the latest stored run that contains the part (optional lot_id query param to
disambiguate a component_id appearing in several lots, mirroring GET /parts/{component_id}).
Auth required. 404 for an unknown part. No event is logged here - see the CONTRACT_CHANGES.md entry:
none of the five event_type literal values (ingest/checkpoint_add/analysis_run/config_change/
timing_flag) fits "a confirmed outcome was recorded", so per AGENTS.md rule 3 no event type was
invented and no event is stored for this action.
"""
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts import AnalysisResults, LotDisposition, RiskAssessment
from identity.auth import create_access_token
from storage import repository
from storage.repository import save_account, save_analysis_run, save_project


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    """Same isolation pattern as tests/integration/test_golden_module_a.py and
    tests/unit/capa/test_capa.py - monkeypatch the shared SessionLocal every already-imported
    repository function reads at call time, rather than importlib.reload."""
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


def _make_results(component_id: str, verdict: str = "REJECT", lot_id: str = "lot_001") -> AnalysisResults:
    return AnalysisResults(
        assessments=[
            RiskAssessment(
                component_id=component_id, lot_id=lot_id, verdict=verdict,
                module_a_rank=1.0, module_b_rank=1.0, worst_parameter="leakage",
                module_a_ran=True, module_b_ran=True, predicted_168h=None, actual_168h=None,
                explanation_sentence=None,
            )
        ],
        disposition=LotDisposition(lot_id=lot_id, status="COMPLETE", pda_result=0.0, verdict="REJECT",
                                    is_forecast=False),
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


def test_creates_a_confirmed_outcome_record(client, auth_headers):
    save_project("proj1", "lot_001", "PN123", datetime.now(UTC), "account1")
    save_analysis_run("proj1", {}, _make_results("comp1"))

    resp = client.post(
        "/parts/comp1/confirmed-outcome",
        json={"confirmed_outcome": "Confirmed Defective", "note": "DPA confirmed crack"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == "proj1"
    assert body["component_id"] == "comp1"
    assert body["confirmed_outcome"] == "Confirmed Defective"
    assert body["note"] == "DPA confirmed crack"
    assert body["account_id"] == "account1"
    assert body["analysis_run_id"]


def test_two_records_for_the_same_part_append_no_overwrite(client, auth_headers):
    save_project("proj1", "lot_001", "PN123", datetime.now(UTC), "account1")
    save_analysis_run("proj1", {}, _make_results("comp1"))

    client.post("/parts/comp1/confirmed-outcome", json={"confirmed_outcome": "Unknown"}, headers=auth_headers)
    client.post("/parts/comp1/confirmed-outcome", json={"confirmed_outcome": "Confirmed Good"},
                headers=auth_headers)

    from storage.repository import query_confirmed_outcomes
    outcomes = query_confirmed_outcomes(project_id="proj1")
    assert len(outcomes) == 2
    assert [o.confirmed_outcome for o in outcomes] == ["Unknown", "Confirmed Good"]


def test_requires_auth(client):
    resp = client.post("/parts/comp1/confirmed-outcome", json={"confirmed_outcome": "Unknown"})
    assert resp.status_code in (401, 403)


def test_unknown_part_returns_404(client, auth_headers):
    resp = client.post(
        "/parts/does-not-exist/confirmed-outcome",
        json={"confirmed_outcome": "Unknown"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_disposition_signoffs_row_count_unchanged(client, auth_headers):
    save_project("proj1", "lot_001", "PN123", datetime.now(UTC), "account1")
    save_analysis_run("proj1", {}, _make_results("comp1"))

    from storage.repository import query_disposition_signoffs
    before = len(query_disposition_signoffs())
    client.post("/parts/comp1/confirmed-outcome", json={"confirmed_outcome": "Confirmed Defective"},
                headers=auth_headers)
    after = len(query_disposition_signoffs())
    assert before == after == 0


def test_lot_id_disambiguates_a_component_id_present_in_two_lots(client, auth_headers):
    save_project("proj1", "lot_001", "PN123", datetime.now(UTC), "account1")
    save_project("proj2", "lot_002", "PN123", datetime.now(UTC), "account1")
    save_analysis_run("proj1", {}, _make_results("comp1", lot_id="lot_001"))
    save_analysis_run("proj2", {}, _make_results("comp1", lot_id="lot_002"))

    resp = client.post(
        "/parts/comp1/confirmed-outcome?lot_id=lot_002",
        json={"confirmed_outcome": "Confirmed Good"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["project_id"] == "proj2"
