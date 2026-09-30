"""Session P2.8 (IMPLEMENTATION_PLAN.md Part 10): storage/router.py - projects, events,
disposition-signoffs read routes. Backs E6's Project Browser (projects list) and History
screen (events + disposition-signoffs), per essential-features.md E11 step 8.
"""
import importlib
from datetime import UTC, datetime

import pytest

from contracts import AnalysisResults, LotDisposition
from fastapi import FastAPI
from fastapi.testclient import TestClient


_EMPTY_RESULTS = AnalysisResults(
    assessments=[],
    disposition=LotDisposition(lot_id="L", status="IN_PROGRESS", pda_result=0.0, verdict="LOT_ON_TRACK", is_forecast=True),
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    from storage import database

    importlib.reload(database)
    from storage import repository

    importlib.reload(repository)
    repository.init_db()

    from storage import router as router_module

    importlib.reload(router_module)

    app = FastAPI()
    app.include_router(router_module.router)

    repository.save_account(account_id="a.sharma", display_name="A. Sharma", role="QE", pin_hash="h")
    repository.save_account(account_id="b.rao", display_name="B. Rao", role="QE", pin_hash="h2")
    repository.save_project(project_id="proj-1", lot_id="L1", part_number="PN-100", test_date=datetime(2026, 8, 1, tzinfo=UTC), created_by="a.sharma")
    repository.save_project(project_id="proj-2", lot_id="L2", part_number="PN-200", test_date=datetime(2026, 8, 1, tzinfo=UTC), created_by="a.sharma")

    return TestClient(app)


# --- GET /projects ----------------------------------------------------------------


def test_get_projects_lists_all_projects(client):
    response = client.get("/projects")
    assert response.status_code == 200
    body = response.json()
    assert {p["project_id"] for p in body} == {"proj-1", "proj-2"}
    by_id = {p["project_id"]: p for p in body}
    assert by_id["proj-2"]["lot_id"] == "L2"
    assert by_id["proj-2"]["part_number"] == "PN-200"
    assert by_id["proj-2"]["created_by"] == "a.sharma"


def test_get_projects_empty_when_none_exist(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'empty.db'}")
    from storage import database

    importlib.reload(database)
    from storage import repository

    importlib.reload(repository)
    repository.init_db()
    from storage import router as router_module

    importlib.reload(router_module)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router_module.router)
    empty_client = TestClient(app)

    response = empty_client.get("/projects")
    assert response.status_code == 200
    assert response.json() == []


# --- GET /projects/{project_id} ----------------------------------------------------


def test_get_project_returns_single_project(client):
    response = client.get("/projects/proj-1")
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == "proj-1"
    assert body["lot_id"] == "L1"


def test_get_project_404_when_missing(client):
    response = client.get("/projects/does-not-exist")
    assert response.status_code == 404


# --- GET /projects/{project_id}/events ----------------------------------------------


def test_get_project_events_returns_logged_events_in_order(client):
    from storage import repository

    repository.log_event("proj-1", "a.sharma", "ingest", {"lot_id": "L1"})
    repository.log_event("proj-1", "b.rao", "analysis_run", {"run": 1})

    response = client.get("/projects/proj-1/events")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert [e["event_type"] for e in body] == ["ingest", "analysis_run"]
    assert body[0]["payload"] == {"lot_id": "L1"}
    assert body[1]["account_id"] == "b.rao"


def test_get_project_events_empty_list_when_none_logged(client):
    response = client.get("/projects/proj-1/events")
    assert response.status_code == 200
    assert response.json() == []


def test_get_project_events_404_when_project_missing(client):
    response = client.get("/projects/does-not-exist/events")
    assert response.status_code == 404


# --- GET /projects/{project_id}/disposition-signoffs --------------------------------


def test_get_disposition_signoffs_returns_them_in_order(client):
    from storage import repository

    repository.save_project(project_id="proj-3", lot_id="L3", part_number="PN-300", test_date=datetime(2026, 8, 1, tzinfo=UTC), created_by="a.sharma")
    repository.save_analysis_run(
        project_id="proj-3", raw_data={}, results=_EMPTY_RESULTS
    )
    run = repository.query_latest_project_data("proj-3")
    repository.save_disposition_signoff(
        project_id="proj-3", component_id="C1", analysis_run_id=run.analysis_run_id,
        account_id="a.sharma", verdict="ACCEPT", rationale="within limits",
    )
    repository.save_disposition_signoff(
        project_id="proj-3", component_id="C2", analysis_run_id=run.analysis_run_id,
        account_id="b.rao", verdict="HOLD", rationale="borderline",
    )

    response = client.get("/projects/proj-3/disposition-signoffs")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["component_id"] == "C1"
    assert body[0]["verdict"] == "ACCEPT"
    assert body[1]["verdict"] == "HOLD"


def test_get_disposition_signoffs_filters_by_component_id(client):
    from storage import repository

    repository.save_project(project_id="proj-4", lot_id="L4", part_number="PN-400", test_date=datetime(2026, 8, 1, tzinfo=UTC), created_by="a.sharma")
    repository.save_analysis_run(project_id="proj-4", raw_data={}, results=_EMPTY_RESULTS)
    run = repository.query_latest_project_data("proj-4")
    repository.save_disposition_signoff(
        project_id="proj-4", component_id="C1", analysis_run_id=run.analysis_run_id,
        account_id="a.sharma", verdict="ACCEPT", rationale="ok",
    )
    repository.save_disposition_signoff(
        project_id="proj-4", component_id="C2", analysis_run_id=run.analysis_run_id,
        account_id="a.sharma", verdict="REJECT", rationale="bad",
    )

    response = client.get("/projects/proj-4/disposition-signoffs", params={"component_id": "C2"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["component_id"] == "C2"
    assert body[0]["verdict"] == "REJECT"


def test_get_disposition_signoffs_empty_list_when_none(client):
    response = client.get("/projects/proj-1/disposition-signoffs")
    assert response.status_code == 200
    assert response.json() == []


def test_get_disposition_signoffs_404_when_project_missing(client):
    response = client.get("/projects/does-not-exist/disposition-signoffs")
    assert response.status_code == 404


# --- GET /events (global) -----------------------------------------------------------


def test_get_all_events_spans_multiple_projects(client):
    from storage import repository

    repository.log_event("proj-1", "a.sharma", "ingest", {"lot_id": "L1"})
    repository.log_event("proj-2", "b.rao", "analysis_run", {"run": 1})

    response = client.get("/events")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {e["project_id"] for e in body} == {"proj-1", "proj-2"}


def test_get_all_events_empty_list_when_none_logged(client):
    response = client.get("/events")
    assert response.status_code == 200
    assert response.json() == []


# --- GET /disposition-signoffs (global) ----------------------------------------------


def test_get_all_disposition_signoffs_spans_multiple_projects(client):
    from storage import repository

    repository.save_project(project_id="proj-5", lot_id="L5", part_number="PN-500", test_date=datetime(2026, 8, 1, tzinfo=UTC), created_by="a.sharma")
    repository.save_project(project_id="proj-6", lot_id="L6", part_number="PN-600", test_date=datetime(2026, 8, 1, tzinfo=UTC), created_by="a.sharma")
    repository.save_analysis_run(project_id="proj-5", raw_data={}, results=_EMPTY_RESULTS)
    repository.save_analysis_run(project_id="proj-6", raw_data={}, results=_EMPTY_RESULTS)
    run5 = repository.query_latest_project_data("proj-5")
    run6 = repository.query_latest_project_data("proj-6")
    repository.save_disposition_signoff(
        project_id="proj-5", component_id="C1", analysis_run_id=run5.analysis_run_id,
        account_id="a.sharma", verdict="ACCEPT", rationale="within limits",
    )
    repository.save_disposition_signoff(
        project_id="proj-6", component_id="C1", analysis_run_id=run6.analysis_run_id,
        account_id="b.rao", verdict="HOLD", rationale="borderline",
    )

    response = client.get("/disposition-signoffs")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {s["project_id"] for s in body} == {"proj-5", "proj-6"}


def test_get_all_disposition_signoffs_filters_by_component_id(client):
    from storage import repository

    repository.save_project(project_id="proj-7", lot_id="L7", part_number="PN-700", test_date=datetime(2026, 8, 1, tzinfo=UTC), created_by="a.sharma")
    repository.save_analysis_run(project_id="proj-7", raw_data={}, results=_EMPTY_RESULTS)
    run7 = repository.query_latest_project_data("proj-7")
    repository.save_disposition_signoff(
        project_id="proj-7", component_id="C1", analysis_run_id=run7.analysis_run_id,
        account_id="a.sharma", verdict="ACCEPT", rationale="ok",
    )
    repository.save_disposition_signoff(
        project_id="proj-7", component_id="C2", analysis_run_id=run7.analysis_run_id,
        account_id="a.sharma", verdict="REJECT", rationale="bad",
    )

    response = client.get("/disposition-signoffs", params={"component_id": "C2"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["component_id"] == "C2"
    assert body[0]["verdict"] == "REJECT"


def test_get_all_disposition_signoffs_empty_list_when_none(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'empty2.db'}")
    from storage import database

    importlib.reload(database)
    from storage import repository

    importlib.reload(repository)
    repository.init_db()
    from storage import router as router_module

    importlib.reload(router_module)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router_module.router)
    empty_client = TestClient(app)

    response = empty_client.get("/disposition-signoffs")
    assert response.status_code == 200
    assert response.json() == []
