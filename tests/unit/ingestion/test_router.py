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

from contracts import AnalysisResults

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
    # VALID_CSV is 0h-only for both components - both are INSUFFICIENT_DATA (R7: never a silent drop).
    assert response.json() == {"lot_id": "L1", "part_number": "PN-1", "status": "IN_PROGRESS", "reading_count": 2,
        "insufficient_data_components": ["c1", "c2"]}


def test_post_lots_requires_metadata_fields():
    response = client.post("/lots", files=_csv_file(VALID_CSV), data={"lot_id": "L1"})
    assert response.status_code == 422


def test_post_lots_returns_422_with_specific_errors_on_bad_csv():
    bad_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,not-a-number,1.2,uA\n"
    response = client.post("/lots", files=_csv_file(bad_csv), data=METADATA)
    assert response.status_code == 422
    assert any("checkpoint_hour" in e for e in response.json()["detail"])


def test_post_lots_returns_422_not_500_on_a_nan_cell():
    # B2 (Lead-as-P2): a bare float() parses "nan" successfully; without the parser-level check
    # this would reach Reading's pydantic validator (contracts.py:66) as an unhandled 500.
    bad_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,0,nan,uA\n"
    response = client.post("/lots", files=_csv_file(bad_csv), data=METADATA)
    assert response.status_code == 422
    assert any("value" in e for e in response.json()["detail"])


def test_post_lots_checkpoints_returns_422_not_500_on_an_inf_cell():
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    bad_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,24,inf,uA\n"
    response = client.post("/lots/L1/checkpoints", files=_csv_file(bad_csv), data={"account_id": "a.sharma"})
    assert response.status_code == 422
    assert any("value" in e for e in response.json()["detail"])


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


# B1 (Lead-as-P2): insufficient_data_components (R7) - populated from ingestion.quality's existing
# INSUFFICIENT_DATA flag, never a new rejection or change to what is stored/analysed.


def test_post_lots_insufficient_data_components_lists_only_the_incomplete_component():
    csv_text = (
        "component_id,parameter,checkpoint_hour,value,unit\n"
        "x,iddq,0,1.2,uA\n"
        "y,iddq,0,1.1,uA\n"
        "y,iddq,24,1.15,uA\n"
    )
    response = client.post("/lots", files=_csv_file(csv_text), data=METADATA)
    assert response.json()["insufficient_data_components"] == ["x"]


def test_post_lots_insufficient_data_components_empty_when_both_complete():
    response = client.post("/lots", files=_csv_file(VALID_IN_PROGRESS_CSV), data=METADATA)
    assert response.json()["insufficient_data_components"] == []


def test_post_lots_checkpoints_insufficient_data_components_becomes_empty_after_merge():
    # Incremental: 0h-only upload lists both components; the 24h checkpoint completes them, and the
    # list must be recomputed over the MERGED dataset, not just the newly-uploaded checkpoint file.
    first = client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    assert first.json()["insufficient_data_components"] == ["c1", "c2"]
    checkpoint_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,24,1.3,uA\nc2,iddq,24,1.2,uA\n"
    response = client.post("/lots/L1/checkpoints", files=_csv_file(checkpoint_csv), data={"account_id": "a.sharma"})
    assert response.json()["insufficient_data_components"] == []


def test_post_lots_checkpoints_insufficient_data_components_lists_the_still_incomplete_component():
    # Only c1 gets a checkpoint; c2 stays 0h-only and must still be listed after the merge.
    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    checkpoint_csv = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,24,1.3,uA\n"
    response = client.post("/lots/L1/checkpoints", files=_csv_file(checkpoint_csv), data={"account_id": "a.sharma"})
    assert response.json()["insufficient_data_components"] == ["c2"]


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


VALID_IN_PROGRESS_CSV = (
    "component_id,parameter,checkpoint_hour,value,unit\n"
    "c1,iddq,0,1.2,uA\n"
    "c1,iddq,24,1.25,uA\n"
    "c2,iddq,0,1.1,uA\n"
    "c2,iddq,24,1.15,uA\n"
)


def test_post_lots_creates_a_project_row_and_persists_an_analysis_run():
    response = client.post("/lots", files=_csv_file(VALID_IN_PROGRESS_CSV), data=METADATA)
    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"
    repository = _repository()

    project = repository.query_project("L1")
    assert project is not None
    assert project.lot_id == "L1"
    assert project.part_number == "PN-1"
    assert project.created_by == "a.sharma"

    runs = repository.query_project_data("L1")
    assert len(runs) == 1
    results = AnalysisResults.model_validate_json(runs[0].results_json)
    # Real fusion.run_full_pipeline output now, not P5's old fixed-stub round trip - only the
    # shape is pinned here, never a specific verdict.
    assert sorted(a.component_id for a in results.assessments) == ["c1", "c2"]
    assert all(a.verdict in {"PASS", "WATCH", "REJECT"} for a in results.assessments)
    assert results.disposition.verdict in {"LOT_ON_TRACK", "LOT_AT_RISK", "STOP_RUN_RECOMMENDED"}


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


def test_post_lots_demo_creates_a_project_row():
    # Was test_post_lots_demo_does_not_require_a_project_row, which pinned /lots/demo as unchanged by P2.5
    # ("out of scope per Part 10's session wording") - a scope note, not a design choice. The demo route now
    # runs the same pipeline-and-persist sequence as POST /lots, so it gets a Project row (Lead, 2026-09-27).
    response = client.post("/lots/demo", data={"account_id": "a.sharma"})
    assert response.status_code == 200
    lot_id = response.json()["lot_id"]
    assert _repository().query_project(lot_id) is not None


# --- P2-flagged findings, fixed by the Lead while P2 was offline (CONTRACT_CHANGES.md 2026-09-27) ---


def test_demo_lot_runs_the_pipeline_and_persists_a_real_analysis_run():
    response = client.post("/lots/demo", data={"account_id": "a.sharma"})
    assert response.status_code == 200
    lot_id = response.json()["lot_id"]

    from storage import repository

    project = repository.query_project(lot_id)
    assert project is not None and project.part_number == "DEMO-PN"
    run = repository.query_latest_project_data(lot_id)
    assert run is not None
    stored = AnalysisResults.model_validate_json(run.results_json)  # a real AnalysisResults, persisted
    assert stored.assessments and stored.disposition.verdict
    assert json.loads(run.raw_data)["lot_id"] == lot_id
    assert "analysis_run" in {e.event_type for e in repository.query_events(lot_id)}


def test_ingest_and_checkpoint_add_events_are_persisted_alongside_analysis_run():
    from storage import repository

    client.post("/lots", files=_csv_file(VALID_CSV), data=METADATA)
    types = [e.event_type for e in repository.query_events("L1")]
    assert sorted(types) == ["analysis_run", "ingest"]

    later = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,24,1.3,uA\nc2,iddq,24,1.2,uA\n"
    client.post("/lots/L1/checkpoints", files=_csv_file(later), data={"account_id": "r.mehta"})
    events = repository.query_events("L1")
    assert sorted(e.event_type for e in events) == ["analysis_run", "analysis_run", "checkpoint_add", "ingest"]
    # Each ingestion event is attributed to the account that did it (E7 step 11).
    by_type = {e.event_type: e.account_id for e in events if e.event_type != "analysis_run"}
    assert by_type == {"ingest": "a.sharma", "checkpoint_add": "r.mehta"}
    assert all(isinstance(e.payload, dict) for e in events)


def test_demo_lot_persists_an_ingest_event_too():
    from storage import repository

    lot_id = client.post("/lots/demo", data={"account_id": "a.sharma"}).json()["lot_id"]
    assert sorted(e.event_type for e in repository.query_events(lot_id)) == ["analysis_run", "ingest"]


def test_malformed_test_date_is_a_422_naming_the_field_not_a_500():
    response = client.post("/lots", files=_csv_file(VALID_CSV), data={**METADATA, "test_date": "next tuesday"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list) and len(detail) == 1
    assert "test_date" in detail[0] and "'next tuesday'" in detail[0]  # field name and what was received


def test_malformed_test_date_leaves_no_state_behind_so_a_corrected_retry_succeeds():
    bad = client.post("/lots", files=_csv_file(VALID_CSV), data={**METADATA, "test_date": "2026-13-45"})
    assert bad.status_code == 422
    assert store.get("L1") is None  # nothing stored: a retry must not hit "lot already exists" (409)
    good = client.post("/lots", files=_csv_file(VALID_CSV), data={**METADATA, "test_date": "2026-09-26"})
    assert good.status_code == 200


def test_valid_iso_test_date_and_absent_test_date_still_work():
    assert client.post("/lots", files=_csv_file(VALID_CSV), data={**METADATA, "test_date": "2026-09-26T14:30:00"}).status_code == 200
    other = {**METADATA, "lot_id": "L2"}
    assert client.post("/lots", files=_csv_file(VALID_CSV), data=other).status_code == 200


def test_demo_route_attributes_its_events_and_project_to_the_acting_account():
    """E7 step 11: every ingestion event carries the account that did it. Two different accounts, so a
    hardcoded identity in load_demo_lot can match at most one of them."""
    from storage import repository

    for account in ("a.sharma", "r.mehta"):
        lot_id = client.post("/lots/demo", data={"account_id": account}).json()["lot_id"]
        events = {e.event_type: e.account_id for e in repository.query_events(lot_id)}
        assert events == {"ingest": account, "analysis_run": account}
        assert repository.query_project(lot_id).created_by == account
