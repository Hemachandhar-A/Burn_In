"""Block 4c Part 3d: end-to-end disposition round trip through the real app routes (identity +
fusion + storage), isolated DB. Login a.sharma -> GET /parts/{id} -> take project_id/
analysis_run_id/verdict straight from that response (the exact reason PartDetailResponse gained
those five fields in Part 3a - the caller previously had no way to get them) -> POST
/parts/{id}/disposition with those values (first REJECT sign-off) -> login r.mehta -> second REJECT
sign-off (same part, distinct account) -> GET /parts/{id} again: disposition_history has both
records, same analysis_run_id. A second sign-off by the SAME account is rejected (400). A REJECT
dual sign-off landing within 120s writes a timing_flag event (visible in History) and never a
config_change (capa_action removed in Block 4a-resume R3 - nothing else writes a config_change from
a disposition either)."""
from datetime import UTC, datetime

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient

from contracts import AnalysisResults, LotDisposition, RiskAssessment
from storage import repository
from storage.repository import save_account, save_analysis_run, save_project

hasher = PasswordHasher()


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
    save_account("a.sharma", "A. Sharma", "Quality Engineer", hasher.hash("1234"))
    save_account("r.mehta", "R. Mehta", "Reliability Engineer", hasher.hash("5678"))

    save_project("proj1", "lot_001", "PN123", datetime.now(UTC), "a.sharma")
    results = AnalysisResults(
        assessments=[
            RiskAssessment(component_id="comp1", lot_id="lot_001", verdict="REJECT",
                            module_a_rank=1.0, module_b_rank=1.0, worst_parameter="leakage",
                            module_a_ran=True, module_b_ran=True, predicted_168h=None, actual_168h=None,
                            explanation_sentence=None),
        ],
        disposition=LotDisposition(lot_id="lot_001", status="COMPLETE", pda_result=1.0, verdict="REJECT",
                                    is_forecast=False),
    )
    save_analysis_run("proj1", {}, results)


@pytest.fixture
def client():
    from fusion.router import router as fusion_router
    from identity.router import router as identity_router
    from storage.router import router as storage_router

    app = FastAPI()
    app.include_router(identity_router)
    app.include_router(fusion_router)
    app.include_router(storage_router)
    return TestClient(app)


def _login(client, account_id, pin):
    resp = client.post("/auth/login", json={"account_id": account_id, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_end_to_end_disposition_round_trip(client):
    token_sharma = _login(client, "a.sharma", "1234")
    headers_sharma = {"Authorization": f"Bearer {token_sharma}"}

    part_resp = client.get("/parts/comp1", headers=headers_sharma)
    assert part_resp.status_code == 200, part_resp.text
    part_body = part_resp.json()
    print("GET /parts/comp1 (before disposition):", part_body)

    project_id = part_body["project_id"]
    analysis_run_id = part_body["analysis_run_id"]
    verdict = part_body["verdict"]
    assert project_id == "proj1"
    assert analysis_run_id is not None
    assert verdict == "REJECT"

    # First sign-off (a.sharma).
    disp1_resp = client.post(
        f"/parts/comp1/disposition?project_id={project_id}&analysis_run_id={analysis_run_id}",
        json={"verdict": verdict, "rationale": "Confirmed defect, first sign-off"},
        headers=headers_sharma,
    )
    assert disp1_resp.status_code == 200, disp1_resp.text
    print("POST disposition #1 (a.sharma):", disp1_resp.json())

    # A second sign-off by the SAME account is rejected (400).
    disp_same_account_resp = client.post(
        f"/parts/comp1/disposition?project_id={project_id}&analysis_run_id={analysis_run_id}",
        json={"verdict": verdict, "rationale": "a.sharma trying again"},
        headers=headers_sharma,
    )
    assert disp_same_account_resp.status_code == 400
    print("POST disposition (same account retry):", disp_same_account_resp.json())
    assert "two distinct account IDs" in disp_same_account_resp.json()["detail"]

    # Second sign-off (r.mehta, distinct account) - lands well within 120s of the first.
    token_mehta = _login(client, "r.mehta", "5678")
    headers_mehta = {"Authorization": f"Bearer {token_mehta}"}
    disp2_resp = client.post(
        f"/parts/comp1/disposition?project_id={project_id}&analysis_run_id={analysis_run_id}",
        json={"verdict": verdict, "rationale": "Confirmed, second sign-off"},
        headers=headers_mehta,
    )
    assert disp2_resp.status_code == 200, disp2_resp.text
    print("POST disposition #2 (r.mehta):", disp2_resp.json())

    # GET /parts/{id} again: disposition_history has both records, same analysis_run_id.
    part_resp_2 = client.get("/parts/comp1", headers=headers_sharma)
    assert part_resp_2.status_code == 200
    part_body_2 = part_resp_2.json()
    print("GET /parts/comp1 (after disposition):", part_body_2)

    history = part_body_2["disposition_history"]
    assert len(history) == 2
    assert {h["account_id"] for h in history} == {"a.sharma", "r.mehta"}
    assert all(h["analysis_run_id"] == analysis_run_id for h in history)
    assert all(h["verdict"] == "REJECT" for h in history)

    # A REJECT dual sign-off within 120s writes a timing_flag event, visible in History, and never
    # a config_change (capa_action removed in Block 4a-resume R3; nothing else writes one either).
    events_resp = client.get(f"/projects/{project_id}/events", headers=headers_sharma)
    assert events_resp.status_code == 200
    events = events_resp.json()
    print("GET /projects/proj1/events:", events)

    timing_flag_events = [e for e in events if e["event_type"] == "timing_flag"]
    config_change_events = [e for e in events if e["event_type"] == "config_change"]
    assert len(timing_flag_events) == 1
    assert config_change_events == []
