"""Block 4c Part 3a (Lead ruling D79): PartDetailResponse's five new identifiers
(component_id/lot_id/project_id/analysis_run_id/verdict) - fusion/router.py::get_part_detail fills
all five on every response for a found part, never None. analysis_run_id must equal the stored
ProjectData row the response was actually built from."""
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


def _results(component_id="comp1", verdict="WATCH"):
    return AnalysisResults(
        assessments=[
            RiskAssessment(component_id=component_id, lot_id="lot_001", verdict=verdict,
                            module_a_rank=1.0, module_b_rank=1.0, worst_parameter="leakage",
                            module_a_ran=True, module_b_ran=True, predicted_168h=None, actual_168h=None,
                            explanation_sentence=None),
        ],
        disposition=LotDisposition(lot_id="lot_001", status="COMPLETE", pda_result=0.0, verdict="HOLD",
                                    is_forecast=False),
    )


@pytest.fixture
def client():
    from fusion.router import router as fusion_router

    app = FastAPI()
    app.include_router(fusion_router)
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {create_access_token('account1', 'Quality Engineer')}"}


def test_all_five_identifiers_present_and_consistent_with_the_stored_run(client, auth_headers):
    save_project("proj1", "lot_001", "PN123", datetime.now(UTC), "account1")
    run = save_analysis_run("proj1", {}, _results())

    resp = client.get("/parts/comp1", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()

    assert body["component_id"] == "comp1"
    assert body["lot_id"] == "lot_001"
    assert body["project_id"] == "proj1"
    assert body["analysis_run_id"] == run.analysis_run_id
    assert body["verdict"] == "WATCH"


def test_analysis_run_id_matches_the_latest_of_two_runs(client, auth_headers):
    save_project("proj1", "lot_001", "PN123", datetime.now(UTC), "account1")
    save_analysis_run("proj1", {}, _results(verdict="PASS"))
    run2 = save_analysis_run("proj1", {}, _results(verdict="REJECT"))

    resp = client.get("/parts/comp1", headers=auth_headers)
    body = resp.json()
    assert body["analysis_run_id"] == run2.analysis_run_id
    assert body["verdict"] == "REJECT"


def test_five_ids_present_for_a_pass_part_too(client, auth_headers):
    save_project("proj1", "lot_001", "PN123", datetime.now(UTC), "account1")
    run = save_analysis_run("proj1", {}, _results(verdict="PASS"))

    resp = client.get("/parts/comp1", headers=auth_headers)
    body = resp.json()
    assert body["component_id"] == "comp1"
    assert body["lot_id"] == "lot_001"
    assert body["project_id"] == "proj1"
    assert body["analysis_run_id"] == run.analysis_run_id
    assert body["verdict"] == "PASS"
