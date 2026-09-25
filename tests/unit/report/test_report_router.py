"""Session P2.7: `report/router.py` - `POST /lots/{lot_id}/report` (IMPLEMENTATION_PLAN.md
Part 5.6 route table): binary PDF by default + `Content-Disposition`, CSV/JSON via `Accept`
negotiation. No `Depends(get_current_account)` yet - `identity/` (P5.4) isn't merged, same
interim as `ingestion/router.py` and `storage/router.py`.
"""
import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    from storage import database

    importlib.reload(database)
    from storage import repository

    importlib.reload(repository)
    repository.init_db()

    from report import router as router_module

    importlib.reload(router_module)

    app = FastAPI()
    app.include_router(router_module.router)

    repository.save_account(account_id="a.sharma", display_name="A. Sharma", role="QE", pin_hash="h")
    repository.save_project(project_id="proj-1", lot_id="L1", part_number="PN-100", created_by="a.sharma")

    from contracts import LotDataset, Reading

    lot = LotDataset(
        lot_id="L1", part_number="PN-100", status="IN_PROGRESS", account_id="a.sharma",
        readings=[
            Reading(component_id="C0", lot_id="L1", part_number="PN-100", manufacturer="Acme",
                    date_code="2450", parameter="iddq", checkpoint_hour=0.0, value=10.0, unit="uA"),
            Reading(component_id="C0", lot_id="L1", part_number="PN-100", manufacturer="Acme",
                    date_code="2450", parameter="iddq", checkpoint_hour=24.0, value=12.0, unit="uA"),
        ],
    )
    repository.save_analysis_run(
        project_id="proj-1", raw_data=lot.model_dump(mode="json"),
        results={"per_component": {"C0": {
            "verdict": "WATCH", "module_a_ran": True, "module_b_ran": False,
            "predicted_168h": None, "actual_168h": None, "explanation_sentence": "elevated z-score",
        }}},
    )

    return TestClient(app)


def test_default_response_is_pdf_with_content_disposition(client):
    response = client.post("/lots/L1/report")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment" in response.headers["content-disposition"]
    assert response.content[:5] == b"%PDF-"


def test_accept_json_returns_json_export(client):
    response = client.post("/lots/L1/report", headers={"Accept": "application/json"})
    assert response.status_code == 200
    body = response.json()
    assert body["lot_id"] == "L1"
    assert body["delta_table"][0]["component_id"] == "C0"


def test_accept_csv_returns_raw_reading_csv(client):
    response = client.post("/lots/L1/report", headers={"Accept": "text/csv"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "component_id" in response.text
    assert "C0" in response.text


def test_404_when_lot_has_no_project(client):
    response = client.post("/lots/does-not-exist/report")
    assert response.status_code == 404


def test_404_when_project_has_no_analysis_run_yet(client):
    from storage import repository

    repository.save_project(project_id="proj-2", lot_id="L2", part_number="PN-200", created_by="a.sharma")
    response = client.post("/lots/L2/report")
    assert response.status_code == 404
