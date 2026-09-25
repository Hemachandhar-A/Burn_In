"""E7 step 6: unit normalization to a canonical unit per parameter."""
import pytest

from contracts import Reading
from ingestion.units import (
    UnitMismatchError, canonical_unit_for, convert_value, is_recognized_parameter, normalize_readings,
)


def _reading(parameter: str, value: float, unit: str, component_id: str = "c1") -> Reading:
    return Reading(
        component_id=component_id, lot_id="L1", part_number="PN-1", manufacturer="ACME",
        date_code="2601", parameter=parameter, checkpoint_hour=0.0, value=value, unit=unit,
    )


def test_canonical_unit_for_recognized_parameter_comes_from_the_registry():
    assert canonical_unit_for("iddq", "mA") == "uA"
    assert canonical_unit_for("leakage", "uA") == "nA"
    assert canonical_unit_for("prop_delay", "us") == "ns"


def test_canonical_unit_for_unrecognized_parameter_is_whatever_was_observed():
    assert canonical_unit_for("vth_shift", "mV") == "mV"


def test_convert_value_within_current_family():
    assert convert_value(1.0, "mA", "uA") == pytest.approx(1000.0)
    assert convert_value(1000.0, "nA", "uA") == pytest.approx(1.0)


def test_convert_value_same_unit_is_identity():
    assert convert_value(5.0, "uA", "uA") == 5.0


def test_convert_value_across_families_raises_unit_mismatch():
    with pytest.raises(UnitMismatchError):
        convert_value(1.0, "uA", "ns")


def test_normalize_readings_converts_mixed_units_for_same_parameter():
    readings = [_reading("iddq", 0.0012, "mA"), _reading("iddq", 1.1, "uA", "c2")]
    normalized, errors = normalize_readings(readings)
    assert not errors
    assert {r.unit for r in normalized} == {"uA"}
    c1 = next(r for r in normalized if r.component_id == "c1")
    assert c1.value == pytest.approx(1.2)


def test_normalize_readings_reports_unconvertible_mismatch_without_raising():
    readings = [_reading("iddq", 1.2, "uA"), _reading("iddq", 5.0, "ns", "c2")]
    normalized, errors = normalize_readings(readings)
    assert errors
    assert any("c2" in e for e in errors)


def test_is_recognized_parameter():
    assert is_recognized_parameter("iddq") is True
    assert is_recognized_parameter("leakage") is True
    assert is_recognized_parameter("vth_shift") is False
