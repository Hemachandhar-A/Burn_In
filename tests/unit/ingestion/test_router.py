"""Session P2.2: POST /lots, /lots/{lot_id}/checkpoints, /lots/demo - real parsing,
validation, merge, and the demo-lot button, over the interim in-process store.

Session P2.5: every POST /lots and POST /lots/{lot_id}/checkpoints call also runs
`fusion.run_full_pipeline` and persists via `storage.repository` now - each test gets its own
temp SQLite file (same pattern as tests/unit/storage/test_repository.py), reloading
storage.database/storage.repository so DATABASE_URL takes effect; ingestion/router.py holds a
`from storage import repository` module reference, so the reload is picked up in place.
"""
import importlib
import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ingestion import store
from ingestion.router import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store_and_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    from storage import database

    importlib.reload(database)
    from storage import repository

    importlib.reload(repository)
    repository.init_db()
    store.clear()
    yield
    store.clear()


def _csv_file(text: str):
    return {"file": ("lot.csv", io.BytesIO(text.encode()), "text/csv")}


VALID_CSV = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,0,1.2,uA\nc2,iddq,0,1.1,uA\n"
METADATA = {"lot_id": "L1", "part_number": "PN-1", "manufacturer": "ACME", "date_code": "2601", "account_id": "a.sharma"}


def test_post_lots_parses_and_stores_a_real_upload():
    response = client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    assert response.status_code == 200
    assert response.json() == {"lot_id": "L1", "part_number": "PN-1", "status": "IN_PROGRESS", "reading_count": 2,
        "insufficient_data_components": []}


def test_post_lots_requires_metadata_fields():
    response = client.post("/lots", files=_csv_file(VALID_CSV), data={"lot_id": "L1"})
    assert response.status_code == 422


def test_post_lots_returns_422_with_specific_errors_on_bad_csv():
    bad_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,not-a-number,1.2,uA\n"
    response = client.post("/lots", files=_csv_file(bad_csv), data=METADATA)
    assert response.status_code == 422
    assert any("checkpoint_hour" in e for e in response.json()["detail"])


def test_post_lots_rejects_a_second_upload_for_the_same_lot_id():
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    response = client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    assert response.status_code == 409


def test_post_lots_checkpoints_merges_into_the_existing_lot():
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    checkpoint_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,24,1.3,uA\nc2,iddq,24,1.2,uA\n"
    response = client.post("/lots/L1/checkpoints", files=_csv_file(checkpoint_csv), data={"account_id": "a.sharma"})
    assert response.status_code == 200
    assert response.json() == {"lot_id": "L1", "part_number": "PN-1", "status": "IN_PROGRESS", "reading_count": 4,
        "insufficient_data_components": []}


def test_post_lots_checkpoints_flips_status_to_complete_at_168h():
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    checkpoint_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,168,1.5,uA\nc2,iddq,168,1.4,uA\n"
    response = client.post("/lots/L1/checkpoints", files=_csv_file(checkpoint_csv), data={"account_id": "a.sharma"})
    assert response.json()["status"] == "COMPLETE"


def test_post_lots_checkpoints_flips_status_to_complete_within_168h_tolerance():
    # P2.3: irregular checkpoint hours - a jittered 167.6h final read still counts as 168h.
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    checkpoint_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,167.6,1.5,uA\nc2,iddq,167.6,1.4,uA\n"
    response = client.post("/lots/L1/checkpoints", files=_csv_file(checkpoint_csv), data={"account_id": "a.sharma"})
    assert response.json()["status"] == "COMPLETE"


def test_post_lots_checkpoints_requires_account_id():
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    checkpoint_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,24,1.3,uA\n"
    response = client.post("/lots/L1/checkpoints", files=_csv_file(checkpoint_csv))
    assert response.status_code == 422


def test_post_lots_checkpoints_records_attribution_for_each_event():
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    checkpoint_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,24,1.3,uA\n"
    client.post("/lots/L1/checkpoints", files=_csv_file(checkpoint_csv), data={"account_id": "r.mehta"})
    record = store.get("L1")
    assert [(e.event_type, e.account_id) for e in record.events] == [
        ("ingest", "a.sharma"), ("checkpoint_add", "r.mehta"),
    ]


def test_post_lots_checkpoints_404s_on_an_unknown_lot():
    response = client.post(
        "/lots/does-not-exist/checkpoints", files=_csv_file(VALID_CSV), data={"account_id": "a.sharma"}
    )
    assert response.status_code == 404


def test_post_lots_normalizes_units_to_canonical_before_storing():
    # P2.3: iddq's canonical unit is uA (generator.parameters.PARAMETERS) - mA must convert.
    csv_text = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,0,0.0012,mA\nc2,iddq,0,1.1,uA\n"
    response = client.post("/lots", files=_csv_file(csv_text), data=METADATA)
    assert response.status_code == 200
    record = store.get("L1")
    c1 = next(r for r in record.dataset.readings if r.component_id == "c1")
    assert c1.unit == "uA"
    assert c1.value == pytest.approx(1.2)


def test_post_lots_rejects_unconvertible_unit_mismatch():
    csv_text = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,0,1.2,uA\nc2,iddq,0,5,ns\n"
    response = client.post("/lots", files=_csv_file(csv_text), data=METADATA)
    assert response.status_code == 422


def test_get_quality_flags_reports_missing_24h_as_insufficient_data():
    csv_text = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,0,1.2,uA\n"
    client.post("/lots", files=_csv_file(csv_text), data=METADATA)
    response = client.get("/lots/L1/quality")
    assert response.status_code == 200
    flags = response.json()
    assert any(f["flag_type"] == "INSUFFICIENT_DATA" and f["component_id"] == "c1" for f in flags)


def test_get_quality_flags_404s_on_an_unknown_lot():
    response = client.get("/lots/does-not-exist/quality")
    assert response.status_code == 404


def test_post_lots_accepts_unrecognized_parameter_without_error():
    # E7 step 10: a numeric column outside {iddq, leakage, prop_delay} is still a valid Reading.
    csv_text = "component_id,parameter,checkpoint_hour,value,unit\nc1,vth_shift,0,0.5,mV\n"
    response = client.post("/lots", files=_csv_file(csv_text), data=METADATA)
    assert response.status_code == 200
    record = store.get("L1")
    assert record.dataset.readings[0].parameter == "vth_shift"


def test_demo_lot_quality_flags_run_cleanly_against_real_generator_output():
    # P2.3: E7 steps 6-11 exercised against real data - the generator's (P1.4) actual LotDataset,
    # not a hand-built fixture. A real, complete 168h lot has every checkpoint per component, so
    # no INSUFFICIENT_DATA/MISSING_96H flags are expected - just confirms the pipeline doesn't
    # choke on real generator output (units already canonical, no unrecognized parameters).
    lot_id = client.post("/lots/demo", data={"account_id": "a.sharma"}).json()["lot_id"]
    response = client.get(f"/lots/{lot_id}/quality")
    assert response.status_code == 200
    flag_types = {f["flag_type"] for f in response.json()}
    assert "INSUFFICIENT_DATA" not in flag_types


def test_post_lots_applies_tester_offset_correction_from_reference_parts():
    # E7 step 8: two reference parts with known expected 10.0 uA read as 11.0 uA raw -> offset +1.0.
    csv_text = (
        "component_id,parameter,checkpoint_hour,value,unit\n"
        "ref1,iddq,0,11.0,uA\n"
        "ref2,iddq,0,11.0,uA\n"
        "c1,iddq,0,12.0,uA\n"
    )
    reference_expected = json.dumps({"ref1": {"iddq": 10.0}, "ref2": {"iddq": 10.0}})
    response = client.post(
        "/lots", files=_csv_file(csv_text), data={**METADATA, "reference_expected_json": reference_expected}
    )
    assert response.status_code == 200
    record = store.get("L1")
    c1 = next(r for r in record.dataset.readings if r.component_id == "c1")
    assert c1.value == pytest.approx(11.0)


def test_post_lots_demo_returns_a_complete_synthetic_lot():
    response = client.post("/lots/demo", data={"account_id": "a.sharma"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETE"
    assert body["reading_count"] > 0
    assert body["lot_id"].startswith("demo-")


def test_post_lots_demo_returns_a_fresh_lot_id_each_call():
    first = client.post("/lots/demo", data={"account_id": "a.sharma"}).json()
    second = client.post("/lots/demo", data={"account_id": "a.sharma"}).json()
    assert first["lot_id"] != second["lot_id"]


# P2.5: fusion.run_full_pipeline + storage persistence, wired after a successful save.


def _repository():
    from storage import repository

    return repository


def test_post_lots_creates_a_project_row_and_persists_an_analysis_run():
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    repository = _repository()

    project = repository.query_project("L1")
    assert project is not None
    assert project.lot_id == "L1"
    assert project.part_number == "PN-1"
    assert project.created_by == "a.sharma"

    runs = repository.query_project_data("L1")
    assert len(runs) == 1
    results = json.loads(runs[0].results_json)
    # fusion.run_full_pipeline is P5's stub - fixed "COMP-001"/"PASS", not derived from
    # this lot's actual readings; this test only pins that the stub's output round-trips.
    assert results["per_component"]["COMP-001"]["verdict"] == "PASS"
    assert results["lot_disposition"]["verdict"] in {"LOT_ON_TRACK", "ACCEPT"}


def test_post_lots_logs_an_analysis_run_event():
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    repository = _repository()

    events = repository.query_events("L1")
    event_types = [e.event_type for e in events]
    assert "analysis_run" in event_types


def test_post_lots_checkpoints_reuses_the_same_project_row_and_adds_another_run():
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    checkpoint_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,24,1.3,uA\nc2,iddq,24,1.2,uA\n"
    client.post("/lots/L1/checkpoints", files=_csv_file(checkpoint_csv), data={"account_id": "a.sharma"})
    repository = _repository()

    assert len(repository.query_projects()) == 1
    runs = repository.query_project_data("L1")
    assert len(runs) == 2
    assert runs[1].diff_vs_prior is not None


def test_post_lots_demo_does_not_require_a_project_row():
    # /lots/demo is unchanged by P2.5 - out of scope per Part 10's session wording.
    response = client.post("/lots/demo", data={"account_id": "a.sharma"})
    assert response.status_code == 200
    lot_id = response.json()["lot_id"]
    assert _repository().query_project(lot_id) is None
