"""E7 step 8: optional tester-offset correction using reference/control parts."""
import pytest

from contracts import Reading
from ingestion.offset import apply_tester_offset_correction


def _reading(component_id: str, value: float, checkpoint_hour: float = 0.0, parameter: str = "iddq") -> Reading:
    return Reading(
        component_id=component_id, lot_id="L1", part_number="PN-1", manufacturer="ACME",
        date_code="2601", parameter=parameter, checkpoint_hour=checkpoint_hour, value=value, unit="uA",
    )


def test_no_reference_expected_is_a_no_op():
    readings = [_reading("c1", 12.0)]
    assert apply_tester_offset_correction(readings, None) == readings
    assert apply_tester_offset_correction(readings, {}) == readings


def test_offset_computed_from_reference_parts_applies_to_every_part_in_the_group():
    readings = [_reading("ref1", 11.0), _reading("ref2", 11.0), _reading("c1", 12.0)]
    reference_expected = {"ref1": {"iddq": 10.0}, "ref2": {"iddq": 10.0}}
    corrected = apply_tester_offset_correction(readings, reference_expected)
    values = {r.component_id: r.value for r in corrected}
    assert values["ref1"] == pytest.approx(10.0)
    assert values["ref2"] == pytest.approx(10.0)
    assert values["c1"] == pytest.approx(11.0)


def test_offset_is_scoped_per_checkpoint_and_parameter():
    readings = [
        _reading("ref1", 11.0, checkpoint_hour=0.0), _reading("c1", 12.0, checkpoint_hour=0.0),
        _reading("c2", 22.0, checkpoint_hour=24.0),  # no reference part present at this checkpoint
    ]
    reference_expected = {"ref1": {"iddq": 10.0}}
    corrected = apply_tester_offset_correction(readings, reference_expected)
    by_key = {(r.component_id, r.checkpoint_hour): r.value for r in corrected}
    assert by_key[("c1", 0.0)] == pytest.approx(11.0)
    assert by_key[("c2", 24.0)] == pytest.approx(22.0)  # no reference at 24h -> unchanged


def test_group_with_no_reference_part_present_is_unchanged():
    readings = [_reading("c1", 12.0), _reading("c2", 13.0)]
    reference_expected = {"ref1": {"iddq": 10.0}}  # ref1 not in this lot's readings at all
    corrected = apply_tester_offset_correction(readings, reference_expected)
    assert corrected == readings
