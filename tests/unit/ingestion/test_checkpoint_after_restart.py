"""POST /lots/{lot_id}/checkpoints after a process restart: ingestion.store (process memory) is empty, but every
analysis run persists the lot's full readings (project_data.raw_data), so the route rebuilds the lot from storage
instead of answering 404 for a lot that exists."""
import csv
import importlib
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from generator.lot import generate_lot
from ingestion import store
from ingestion.router import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

LOT = "RESTART-01"
META = {"lot_id": LOT, "part_number": "DEMO-PN", "manufacturer": "ACME", "date_code": "2601", "account_id": "a.sharma"}


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    from storage import database

    importlib.reload(database)
    from storage import repository

    importlib.reload(repository)
    repository.init_db()
    store.clear()
    yield
    store.clear()


@pytest.fixture(scope="module")
def readings():
    return generate_lot(lot_id=LOT, part_number="DEMO-PN", seed=5, account_id="a.sharma").dataset.readings


def _file(readings, hours):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["component_id", "parameter", "checkpoint_hour", "value", "unit"])
    for r in readings:
        if r.checkpoint_hour in hours:
            w.writerow([r.component_id, r.parameter, r.checkpoint_hour, r.value, r.unit])
    return {"file": ("cp.csv", io.BytesIO(buf.getvalue().encode()), "text/csv")}


def _stored_run():
    from contracts import AnalysisResults
    from storage import repository

    row = repository.query_latest_project_data(LOT)
    return AnalysisResults.model_validate_json(row.results_json), len(__import__("json").loads(row.raw_data)["readings"])


def test_checkpoints_continue_after_a_restart(readings):
    up = client.post("/lots", files=_file(readings, (0, 24)), data=META)
    assert up.status_code == 200 and up.json()["status"] == "IN_PROGRESS"
    base_count = up.json()["reading_count"]

    store.clear()  # the restart: process memory gone, the database stays

    r96 = client.post(f"/lots/{LOT}/checkpoints", files=_file(readings, (96,)), data={"account_id": "a.sharma"})
    assert r96.status_code == 200, r96.text
    assert r96.json()["status"] == "IN_PROGRESS" and r96.json()["reading_count"] > base_count
    results, n_readings = _stored_run()
    assert n_readings == r96.json()["reading_count"]
    assert {r.checkpoint_hour for r in readings if r.checkpoint_hour in (0, 24, 96)} == {0, 24, 96}

    store.clear()  # and again: the rebuilt lot carries the 96h rows too

    r168 = client.post(f"/lots/{LOT}/checkpoints", files=_file(readings, (168,)), data={"account_id": "a.sharma"})
    assert r168.status_code == 200, r168.text
    assert r168.json()["status"] == "COMPLETE"
    assert r168.json()["reading_count"] == len(readings)
    results, _ = _stored_run()
    assert results.disposition.status == "COMPLETE" and results.disposition.is_forecast is False
    assert results.module_a_results, "Module A results appear once the lot is complete"


def test_unknown_lot_is_still_404_after_a_restart(readings):
    store.clear()
    r = client.post("/lots/NOWHERE/checkpoints", files=_file(readings, (96,)), data={"account_id": "a.sharma"})
    assert r.status_code == 404
