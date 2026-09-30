"""E13 step 5 (Block 4a Part 5): POST /lots/{lot_id}/dpa-work-order router mechanics - lot lookup,
COMPLETE-only gate (409 on IN_PROGRESS), 404s, auth. Selection-rule behavior itself is covered by
tests/unit/capa/test_dpa_selection.py (pure function) and the golden lot in
tests/integration/test_dpa_work_order_golden.py."""
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts import AnalysisResults, LotDisposition, ModuleAResult, RiskAssessment
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


def _results(status: str) -> AnalysisResults:
    return AnalysisResults(
        assessments=[
            RiskAssessment(component_id="comp1", lot_id="lot_001", verdict="REJECT",
                            module_a_rank=1.0, module_b_rank=1.0, worst_parameter="leakage",
                            module_a_ran=True, module_b_ran=True, predicted_168h=None, actual_168h=None,
                            explanation_sentence=None),
            RiskAssessment(component_id="comp2", lot_id="lot_001", verdict="PASS",
                            module_a_rank=2.0, module_b_rank=2.0, worst_parameter="leakage",
                            module_a_ran=True, module_b_ran=True, predicted_168h=None, actual_168h=None,
                            explanation_sentence=None),
        ],
        disposition=LotDisposition(lot_id="lot_001", status=status, pda_result=0.0, verdict="REJECT",
                                    is_forecast=(status == "IN_PROGRESS")),
        module_a_results={
            "comp1": ModuleAResult(component_id="comp1", lot_id="lot_001", parameter="leakage",
                                    robust_z=3.0, mcd_distance=None, isolation_forest_score=None,
                                    ecod_score=0.1, explainable_tags={"robust_z": True, "mcd": False,
                                    "isolation_forest": False, "ecod": False}, direction="above_median",
                                    severity_tier="REJECT", severity_cap_reason=None, combined_severity=0.95,
                                    explainable_corroboration=True),
            "comp2": ModuleAResult(component_id="comp2", lot_id="lot_001", parameter="leakage",
                                    robust_z=0.1, mcd_distance=None, isolation_forest_score=None,
                                    ecod_score=0.05, explainable_tags={"robust_z": False, "mcd": False,
                                    "isolation_forest": False, "ecod": False}, direction="above_median",
                                    severity_tier="PASS", severity_cap_reason=None, combined_severity=0.02,
                                    explainable_corroboration=False),
        },
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


def test_complete_lot_returns_recommendations(client, auth_headers):
    save_project("proj1", "lot_001", "PN123", datetime.now(UTC), "account1")
    save_analysis_run("proj1", {}, _results("COMPLETE"))

    resp = client.post("/lots/lot_001/dpa-work-order", headers=auth_headers)
    assert resp.status_code == 200
    recs = resp.json()["recommendations"]
    assert len(recs) == 2
    assert recs[0]["component_id"] == "comp1"
    assert recs[1]["component_id"] == "comp2"


def test_in_progress_lot_returns_409(client, auth_headers):
    save_project("proj1", "lot_001", "PN123", datetime.now(UTC), "account1")
    save_analysis_run("proj1", {}, _results("IN_PROGRESS"))

    resp = client.post("/lots/lot_001/dpa-work-order", headers=auth_headers)
    assert resp.status_code == 409


def test_unknown_lot_returns_404(client, auth_headers):
    resp = client.post("/lots/does-not-exist/dpa-work-order", headers=auth_headers)
    assert resp.status_code == 404


def test_requires_auth(client):
    resp = client.post("/lots/lot_001/dpa-work-order")
    assert resp.status_code in (401, 403)
