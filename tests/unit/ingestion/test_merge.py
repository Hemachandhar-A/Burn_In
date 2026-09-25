"""E7 steps 3-4: incremental merge-by-part-ID, and the Complete/In-Progress trigger."""
from contracts import LotDataset, Reading
from ingestion.merge import compute_status, merge_checkpoint


def _reading(component_id: str, parameter: str, checkpoint_hour: float, value: float = 1.0) -> Reading:
    return Reading(
        component_id=component_id, lot_id="L1", part_number="PN-1", manufacturer="ACME",
        date_code="2601", parameter=parameter, checkpoint_hour=checkpoint_hour, value=value, unit="uA",
    )


def test_compute_status_is_in_progress_without_a_168h_reading():
    readings = [_reading("c1", "iddq", 0.0), _reading("c1", "iddq", 24.0)]
    assert compute_status(readings) == "IN_PROGRESS"


def test_compute_status_stays_in_progress_even_past_168h_without_the_168h_read_itself():
    # essential-features.md E7 step 4: readings past 168h with no 168h read stays In-Progress.
    readings = [_reading("c1", "iddq", 0.0), _reading("c1", "iddq", 200.0)]
    assert compute_status(readings) == "IN_PROGRESS"


def test_compute_status_is_complete_once_a_168h_reading_exists():
    readings = [_reading("c1", "iddq", 0.0), _reading("c1", "iddq", 168.0)]
    assert compute_status(readings) == "COMPLETE"


def test_merge_checkpoint_adds_new_component_history():
    existing = LotDataset(
        lot_id="L1", part_number="PN-1", status="IN_PROGRESS",
        readings=[_reading("c1", "iddq", 0.0)], account_id="a.sharma",
    )
    new_readings = [_reading("c1", "iddq", 24.0), _reading("c2", "iddq", 0.0)]
    merged = merge_checkpoint(existing, new_readings)
    assert len(merged.readings) == 3
    assert merged.lot_id == "L1"
    assert merged.account_id == "a.sharma"


def test_merge_checkpoint_matches_by_component_id_not_position():
    existing = LotDataset(
        lot_id="L1", part_number="PN-1", status="IN_PROGRESS",
        readings=[_reading("c1", "iddq", 0.0), _reading("c2", "iddq", 0.0)], account_id="a.sharma",
    )
    new_readings = [_reading("c2", "iddq", 24.0), _reading("c1", "iddq", 24.0)]
    merged = merge_checkpoint(existing, new_readings)
    c1_hours = sorted(r.checkpoint_hour for r in merged.readings if r.component_id == "c1")
    c2_hours = sorted(r.checkpoint_hour for r in merged.readings if r.component_id == "c2")
    assert c1_hours == [0.0, 24.0]
    assert c2_hours == [0.0, 24.0]


def test_merge_checkpoint_deduplicates_an_exact_repeat_reading():
    existing = LotDataset(
        lot_id="L1", part_number="PN-1", status="IN_PROGRESS",
        readings=[_reading("c1", "iddq", 0.0)], account_id="a.sharma",
    )
    merged = merge_checkpoint(existing, [_reading("c1", "iddq", 0.0)])
    assert len(merged.readings) == 1


def test_merge_checkpoint_recomputes_status_to_complete():
    existing = LotDataset(
        lot_id="L1", part_number="PN-1", status="IN_PROGRESS",
        readings=[_reading("c1", "iddq", 0.0)], account_id="a.sharma",
    )
    merged = merge_checkpoint(existing, [_reading("c1", "iddq", 168.0)])
    assert merged.status == "COMPLETE"
