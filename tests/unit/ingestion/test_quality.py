"""E7 step 7: data-quality checks - missing values, out-of-datasheet-range flags, duplicate
part IDs."""
from contracts import Reading
from ingestion.quality import check_duplicate_component_ids, check_missing_checkpoints, check_out_of_range


def _reading(component_id: str, parameter: str, checkpoint_hour: float, value: float = 1.0, unit: str = "uA") -> Reading:
    return Reading(
        component_id=component_id, lot_id="L1", part_number="PN-1", manufacturer="ACME",
        date_code="2601", parameter=parameter, checkpoint_hour=checkpoint_hour, value=value, unit=unit,
    )


def test_missing_24h_flags_insufficient_data():
    readings = [_reading("c1", "iddq", 0.0)]
    flags = check_missing_checkpoints(readings)
    assert len(flags) == 1
    assert flags[0].flag_type == "INSUFFICIENT_DATA"
    assert flags[0].component_id == "c1"


def test_missing_0h_flags_insufficient_data():
    readings = [_reading("c1", "iddq", 24.0)]
    flags = check_missing_checkpoints(readings)
    assert flags[0].flag_type == "INSUFFICIENT_DATA"


def test_present_0h_and_24h_missing_96h_flags_missing_96h_not_insufficient():
    readings = [_reading("c1", "iddq", 0.0), _reading("c1", "iddq", 24.0)]
    flags = check_missing_checkpoints(readings)
    assert len(flags) == 1
    assert flags[0].flag_type == "MISSING_96H"


def test_all_four_checkpoints_present_raises_no_flag():
    readings = [
        _reading("c1", "iddq", 0.0), _reading("c1", "iddq", 24.0),
        _reading("c1", "iddq", 96.0), _reading("c1", "iddq", 168.0),
    ]
    assert check_missing_checkpoints(readings) == []


def test_missing_checkpoints_is_scoped_per_component_and_parameter():
    readings = [
        _reading("c1", "iddq", 0.0), _reading("c1", "iddq", 24.0),  # complete-ish (missing 96h)
        _reading("c2", "iddq", 0.0),  # missing 24h -> insufficient
    ]
    flags = check_missing_checkpoints(readings)
    by_component = {f.component_id: f.flag_type for f in flags}
    assert by_component == {"c1": "MISSING_96H", "c2": "INSUFFICIENT_DATA"}


def test_out_of_range_flags_a_value_outside_the_supplied_limits():
    readings = [_reading("c1", "iddq", 0.0, value=45.0)]
    flags = check_out_of_range(readings, {"iddq": (0.0, 50.0)})
    assert flags == []
    flags = check_out_of_range(readings, {"iddq": (0.0, 40.0)})
    assert len(flags) == 1
    assert flags[0].flag_type == "OUT_OF_RANGE"


def test_out_of_range_is_a_no_op_without_limits():
    readings = [_reading("c1", "iddq", 0.0, value=999.0)]
    assert check_out_of_range(readings, None) == []
    assert check_out_of_range(readings, {}) == []


def test_duplicate_component_ids_flags_two_readings_mapped_to_the_same_label():
    readings = [_reading("c1", "iddq", 24.0), _reading("c1", "iddq", 24.3)]
    flags = check_duplicate_component_ids(readings)
    assert len(flags) == 1
    assert flags[0].flag_type == "DUPLICATE_CHECKPOINT"


def test_duplicate_component_ids_no_flag_for_distinct_checkpoints():
    readings = [_reading("c1", "iddq", 0.0), _reading("c1", "iddq", 24.0)]
    assert check_duplicate_component_ids(readings) == []
