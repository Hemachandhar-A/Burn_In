"""E7 steps 1, 5: CSV upload parsing and schema validation with visible, specific errors."""
import pytest

from ingestion.parsing import IngestionValidationError, parse_lot_csv, parse_wide_lot_csv

METADATA = {"lot_id": "L1", "part_number": "PN-1", "manufacturer": "ACME", "date_code": "2601"}


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


def test_parses_canonical_long_format_header():
    csv_text = (
        "component_id,parameter,checkpoint_hour,value,unit\n"
        "c1,iddq,0,1.2,uA\n"
        "c1,iddq,24,1.3,uA\n"
        "c2,iddq,0,1.1,uA\n"
    )
    readings = parse_lot_csv(_csv(csv_text), **METADATA)
    assert len(readings) == 3
    assert readings[0].lot_id == "L1"
    assert readings[0].part_number == "PN-1"
    assert readings[0].manufacturer == "ACME"
    assert readings[0].date_code == "2601"
    assert readings[0].component_id == "c1"
    assert readings[0].checkpoint_hour == 0.0
    assert readings[0].value == 1.2


def test_fuzzy_column_matching_accepts_known_aliases_and_case_differences():
    csv_text = "Part ID,Param,Hour,Reading,Units\nc1,iddq,0,1.2,uA\n"
    readings = parse_lot_csv(_csv(csv_text), **METADATA)
    assert len(readings) == 1
    assert readings[0].component_id == "c1"


def test_missing_required_column_raises_a_specific_error():
    csv_text = "component_id,parameter,value,unit\nc1,iddq,1.2,uA\n"  # no checkpoint_hour column
    with pytest.raises(IngestionValidationError) as exc_info:
        parse_lot_csv(_csv(csv_text), **METADATA)
    assert any("checkpoint_hour" in e for e in exc_info.value.errors)


def test_ambiguous_column_raises_a_specific_error_naming_the_candidates():
    csv_text = "component_id,part_id,parameter,checkpoint_hour,value,unit\nc1,c1,iddq,0,1.2,uA\n"
    with pytest.raises(IngestionValidationError) as exc_info:
        parse_lot_csv(_csv(csv_text), **METADATA)
    assert any("ambiguous" in e and "component_id" in e for e in exc_info.value.errors)


def test_non_numeric_value_raises_a_line_specific_error():
    csv_text = "component_id,parameter,checkpoint_hour,value,unit\nc1,iddq,0,not-a-number,uA\n"
    with pytest.raises(IngestionValidationError) as exc_info:
        parse_lot_csv(_csv(csv_text), **METADATA)
    assert any("line 2" in e and "value" in e for e in exc_info.value.errors)


def test_duplicate_reading_in_one_file_raises_a_specific_error():
    csv_text = (
        "component_id,parameter,checkpoint_hour,value,unit\n"
        "c1,iddq,0,1.2,uA\n"
        "c1,iddq,0,1.3,uA\n"
    )
    with pytest.raises(IngestionValidationError) as exc_info:
        parse_lot_csv(_csv(csv_text), **METADATA)
    assert any("duplicate" in e and "c1" in e for e in exc_info.value.errors)


def test_empty_file_raises_a_specific_error():
    with pytest.raises(IngestionValidationError) as exc_info:
        parse_lot_csv(_csv(""), **METADATA)
    assert exc_info.value.errors


def test_header_only_file_raises_a_specific_error():
    csv_text = "component_id,parameter,checkpoint_hour,value,unit\n"
    with pytest.raises(IngestionValidationError) as exc_info:
        parse_lot_csv(_csv(csv_text), **METADATA)
    assert any("no data rows" in e for e in exc_info.value.errors)


def test_reports_every_problem_found_not_just_the_first():
    csv_text = (
        "component_id,parameter,checkpoint_hour,value,unit\n"
        "c1,iddq,not-a-number,1.2,uA\n"
        "c2,iddq,0,also-not-a-number,uA\n"
    )
    with pytest.raises(IngestionValidationError) as exc_info:
        parse_lot_csv(_csv(csv_text), **METADATA)
    assert len(exc_info.value.errors) == 2


# --- P2.3: wide-format parsing and wide/long equivalence (Part 7.3 checklist row) ---------


def test_parses_wide_format_header():
    csv_text = (
        "component_id,checkpoint_hour,iddq_uA,leakage_nA\n"
        "c1,0,1.2,5.0\n"
        "c1,24,1.3,5.1\n"
        "c2,0,1.1,4.9\n"
    )
    readings = parse_wide_lot_csv(_csv(csv_text), **METADATA)
    assert len(readings) == 6
    c1_iddq_0h = next(r for r in readings if r.component_id == "c1" and r.parameter == "iddq" and r.checkpoint_hour == 0.0)
    assert c1_iddq_0h.value == 1.2
    assert c1_iddq_0h.unit == "uA"


def test_wide_format_blank_cell_is_skipped_not_an_error():
    csv_text = "component_id,checkpoint_hour,iddq_uA,leakage_nA\nc1,0,1.2,\n"
    readings = parse_wide_lot_csv(_csv(csv_text), **METADATA)
    assert len(readings) == 1
    assert readings[0].parameter == "iddq"


def test_wide_and_long_format_produce_equivalent_readings_for_the_same_data():
    long_csv = (
        "component_id,parameter,checkpoint_hour,value,unit\n"
        "c1,iddq,0,1.2,uA\n"
        "c1,leakage,0,5.0,nA\n"
        "c2,iddq,0,1.1,uA\n"
    )
    wide_csv = (
        "component_id,checkpoint_hour,iddq_uA,leakage_nA\n"
        "c1,0,1.2,5.0\n"
        "c2,0,1.1,\n"
    )
    long_readings = parse_lot_csv(_csv(long_csv), **METADATA)
    wide_readings = parse_wide_lot_csv(_csv(wide_csv), **METADATA)

    def _key(r):
        return (r.component_id, r.parameter, r.checkpoint_hour, r.value, r.unit)

    assert sorted(map(_key, long_readings)) == sorted(map(_key, wide_readings))


def test_wide_format_unrecognized_value_column_raises_a_specific_error():
    csv_text = "component_id,checkpoint_hour,garbage\nc1,0,1.2\n"
    with pytest.raises(IngestionValidationError) as exc_info:
        parse_wide_lot_csv(_csv(csv_text), **METADATA)
    assert any("garbage" in e for e in exc_info.value.errors)
