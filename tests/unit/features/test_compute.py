"""Session P2.4: real E8 steps 1-5 statistics (deltas, lot-relative robust stats, the <30-part
small-lot fallback, per-part robust z-scores, and the joint MCD feature vector) - replacing the
P2.1 stub's fixed placeholder values.  Part 7.3's Features row: zero-MAD lot, lot size < 30,
lot size = 1.
"""
from contracts import LotDataset, Reading
from features.compute import build_mcd_matrix, compute


def _reading(component_id: str, parameter: str, checkpoint_hour: float, value: float,
             part_number: str = "PN-1") -> Reading:
    return Reading(
        component_id=component_id,
        lot_id="L1",
        part_number=part_number,
        manufacturer="m",
        date_code="2601",
        parameter=parameter,
        checkpoint_hour=checkpoint_hour,
        value=value,
        unit="uA",
    )


def _lot(readings: list[Reading], lot_id: str = "L1", part_number: str = "PN-1",
         status: str = "IN_PROGRESS") -> LotDataset:
    return LotDataset(
        lot_id=lot_id, part_number=part_number, status=status, readings=readings,
        account_id="a.sharma",
    )


def _component_with_0h_24h(component_id: str, parameter: str, v0: float, v24: float,
                            v96: float | None = None, v168: float | None = None) -> list[Reading]:
    readings = [
        _reading(component_id, parameter, 0.0, v0),
        _reading(component_id, parameter, 24.0, v24),
    ]
    if v96 is not None:
        readings.append(_reading(component_id, parameter, 96.0, v96))
    if v168 is not None:
        readings.append(_reading(component_id, parameter, 168.0, v168))
    return readings


def _lot_of_identical_parts(n: int, parameter: str = "iddq", value: float = 10.0) -> LotDataset:
    readings = []
    for i in range(n):
        readings += _component_with_0h_24h(f"c{i}", parameter, value, value)
    return _lot(readings)


def test_one_frame_per_component_parameter_pair():
    readings = (
        _component_with_0h_24h("c1", "iddq", 10.0, 11.0)
        + _component_with_0h_24h("c1", "leakage", 5.0, 5.5)
        + _component_with_0h_24h("c2", "iddq", 9.0, 9.5)
        + _component_with_0h_24h("c2", "leakage", 4.0, 4.2)
    )
    frames = compute(_lot(readings))
    pairs = {(f.component_id, f.parameter) for f in frames}
    assert pairs == {("c1", "iddq"), ("c1", "leakage"), ("c2", "iddq"), ("c2", "leakage")}


def test_lot_id_and_part_number_carried_through_from_the_lot():
    readings = _component_with_0h_24h("c1", "iddq", 10.0, 11.0)
    frame = compute(_lot(readings, lot_id="L9", part_number="PN-9"))[0]
    assert frame.lot_id == "L9"
    assert frame.part_number == "PN-9"


def test_missing_24h_produces_no_frame_for_that_pair():
    """AGENTS.md rule 7: INSUFFICIENT_DATA (missing 0h or 24h) is never silently guessed -
    the pair simply gets no FeatureFrame at all, since value_0h/value_24h are non-optional."""
    readings = [_reading("c1", "iddq", 0.0, 10.0)]  # 0h only, no 24h
    frames = compute(_lot(readings))
    assert frames == []


def test_missing_0h_produces_no_frame_for_that_pair():
    readings = [_reading("c1", "iddq", 24.0, 11.0)]  # 24h only, no 0h
    frames = compute(_lot(readings))
    assert frames == []


def test_one_pair_missing_data_does_not_block_others_in_the_same_lot():
    readings = (
        _component_with_0h_24h("c1", "iddq", 10.0, 11.0)
        + [_reading("c2", "iddq", 0.0, 9.0)]  # c2/iddq missing 24h
    )
    frames = compute(_lot(readings))
    pairs = {(f.component_id, f.parameter) for f in frames}
    assert pairs == {("c1", "iddq")}


def test_delta_24h_and_96h_computed_correctly():
    readings = _component_with_0h_24h("c1", "iddq", 10.0, 13.0, v96=18.0)
    frame = compute(_lot(readings))[0]
    assert frame.value_0h == 10.0
    assert frame.value_24h == 13.0
    assert frame.value_96h == 18.0
    assert frame.delta_24h == 3.0
    assert frame.delta_96h == 8.0


def test_delta_96h_and_value_96h_none_when_96h_absent():
    readings = _component_with_0h_24h("c1", "iddq", 10.0, 13.0)
    frame = compute(_lot(readings))[0]
    assert frame.value_96h is None
    assert frame.delta_96h is None


def test_lot_median_and_robust_z_computed_from_lot_population():
    # Three components, values 10, 20, 30 at 0h -> median 20, IQR/1.35 = (25-15)/1.35
    readings = (
        _component_with_0h_24h("c1", "iddq", 10.0, 10.0)
        + _component_with_0h_24h("c2", "iddq", 20.0, 20.0)
        + _component_with_0h_24h("c3", "iddq", 30.0, 30.0)
    )
    frames = {f.component_id: f for f in compute(_lot(readings))}
    assert frames["c2"].lot_median_0h == 20.0
    expected_sigma = (25.0 - 15.0) / 1.35
    assert frames["c1"].robust_z["0h"] == (10.0 - 20.0) / expected_sigma
    assert frames["c2"].robust_z["0h"] == 0.0


def test_zero_mad_lot_all_identical_values_gives_zero_z_not_a_crash():
    """Part 7.3 Features row: zero-MAD lot (all-identical values)."""
    lot = _lot_of_identical_parts(5, value=10.0)
    frames = compute(lot)
    assert len(frames) == 5
    for f in frames:
        assert f.robust_z["0h"] == 0.0
        assert f.robust_z["24h"] == 0.0
        assert f.lot_median_0h == 10.0


def test_lot_size_of_one_does_not_crash_and_flags_pooled_fallback():
    """Part 7.3 Features row: lot size = 1."""
    lot = _lot_of_identical_parts(1, value=42.0)
    frames = compute(lot)
    assert len(frames) == 1
    frame = frames[0]
    assert frame.lot_size == 1
    assert frame.used_pooled_fallback is True
    assert frame.robust_z["0h"] == 0.0  # sigma is 0 for a single-part "lot"


def test_small_lot_triggers_pooled_fallback_flag():
    """Part 7.3 Features row: lot size < 30 triggers pooled fallback."""
    lot = _lot_of_identical_parts(5)
    frames = compute(lot)
    assert all(f.used_pooled_fallback for f in frames)
    assert all(f.lot_size == 5 for f in frames)


def test_lot_of_30_or_more_does_not_trigger_pooled_fallback():
    lot = _lot_of_identical_parts(30)
    frames = compute(lot)
    assert not any(f.used_pooled_fallback for f in frames)
    assert all(f.lot_size == 30 for f in frames)


def test_pooled_reference_used_for_small_lot_when_supplied():
    lot = _lot_of_identical_parts(5, parameter="iddq", value=10.0)
    pooled_reference = {("PN-1", "iddq", "0h"): (100.0, 2.0), ("PN-1", "iddq", "24h"): (100.0, 2.0)}
    frames = compute(lot, pooled_reference=pooled_reference)
    for f in frames:
        assert f.lot_median_0h == 100.0
        assert f.robust_z["0h"] == (10.0 - 100.0) / 2.0


def test_pooled_reference_ignored_when_lot_is_not_small():
    lot = _lot_of_identical_parts(30, parameter="iddq", value=10.0)
    pooled_reference = {("PN-1", "iddq", "0h"): (999.0, 2.0), ("PN-1", "iddq", "24h"): (999.0, 2.0)}
    frames = compute(lot, pooled_reference=pooled_reference)
    for f in frames:
        assert f.lot_median_0h == 10.0  # lot-relative, pooled reference not applied


def test_elapsed_hours_reflects_actual_irregular_checkpoint_not_assumed_nominal():
    readings = [
        _reading("c1", "iddq", 0.3, 10.0),   # jittered 0h
        _reading("c1", "iddq", 23.6, 11.0),  # jittered 24h
    ]
    frame = compute(_lot(readings))[0]
    assert frame.elapsed_hours["0h"] == 0.3
    assert frame.elapsed_hours["24h"] == 23.6


def test_duplicate_readings_mapping_to_same_label_pick_the_closest_to_nominal():
    readings = [
        _reading("c1", "iddq", 0.0, 10.0),
        _reading("c1", "iddq", 24.3, 11.0),
        _reading("c1", "iddq", 25.5, 999.0),  # also maps to "24h", further from nominal
    ]
    frame = compute(_lot(readings))[0]
    assert frame.value_24h == 11.0
    assert frame.elapsed_hours["24h"] == 24.3


def test_168h_absent_for_in_progress_lot_even_if_reading_present():
    """CONTRACT_CHANGES.md SUPERSEDES entry: 168h is Module A's post-hoc scoring on Complete
    lots only - an In-Progress lot never gets a 168h frame entry, even if a 168h Reading is
    already present in the data (168h is also the Complete-lot trigger and Module B's target,
    not a value to expose mid-run)."""
    readings = _component_with_0h_24h("c1", "iddq", 10.0, 11.0) + [_reading("c1", "iddq", 168.0, 50.0)]
    frame = compute(_lot(readings, status="IN_PROGRESS"))[0]
    assert frame.value_168h is None
    assert frame.delta_168h is None
    assert "168h" not in frame.elapsed_hours
    assert "168h" not in frame.robust_z


def test_168h_populated_for_complete_lot():
    """CONTRACT_CHANGES.md SUPERSEDES entry: on a Complete lot, Module A scores the 168h
    reading too - value_168h/delta_168h/robust_z["168h"]/elapsed_hours["168h"] are populated,
    the same pattern as the existing 96h fields."""
    readings = (
        _component_with_0h_24h("c1", "iddq", 10.0, 13.0, v96=18.0, v168=25.0)
        + _component_with_0h_24h("c2", "iddq", 8.0, 9.0, v96=12.0, v168=15.0)
        + _component_with_0h_24h("c3", "iddq", 12.0, 15.0, v96=20.0, v168=35.0)
    )
    frames = {f.component_id: f for f in compute(_lot(readings, status="COMPLETE"))}
    frame = frames["c1"]
    assert frame.value_168h == 25.0
    assert frame.delta_168h == 15.0
    assert frame.elapsed_hours["168h"] == 168.0
    assert "168h" in frame.robust_z
    # lot-relative median at 168h: 15, 25, 35 -> median 25
    assert frame.robust_z["168h"] == 0.0
    assert frames["c2"].robust_z["168h"] == (15.0 - 25.0) / ((30.0 - 20.0) / 1.35)


def test_168h_absent_when_reading_missing_even_on_complete_lot():
    """A Complete lot with no 168h Reading for a pair still gets None, not a guessed value
    (AGENTS.md rule 7)."""
    readings = _component_with_0h_24h("c1", "iddq", 10.0, 13.0, v96=18.0)  # no 168h reading
    frame = compute(_lot(readings, status="COMPLETE"))[0]
    assert frame.value_168h is None
    assert frame.delta_168h is None
    assert "168h" not in frame.elapsed_hours
    assert "168h" not in frame.robust_z


def test_168h_mcd_matrix_buildable_for_complete_lot():
    readings = (
        _component_with_0h_24h("c1", "iddq", 10.0, 10.0, v168=20.0)
        + _component_with_0h_24h("c1", "leakage", 4.0, 4.0, v168=8.0)
        + _component_with_0h_24h("c2", "iddq", 20.0, 20.0, v168=30.0)
        + _component_with_0h_24h("c2", "leakage", 8.0, 8.0, v168=16.0)
    )
    frames = compute(_lot(readings, status="COMPLETE"))
    component_ids, parameters, matrix = build_mcd_matrix(frames, "168h")
    assert component_ids == ["c1", "c2"]
    assert parameters == ["iddq", "leakage"]
    assert len(matrix) == 2


def test_build_mcd_matrix_joint_across_parameters_for_same_component():
    readings = (
        _component_with_0h_24h("c1", "iddq", 10.0, 10.0)
        + _component_with_0h_24h("c1", "leakage", 4.0, 4.0)
        + _component_with_0h_24h("c2", "iddq", 20.0, 20.0)
        + _component_with_0h_24h("c2", "leakage", 8.0, 8.0)
    )
    frames = compute(_lot(readings))
    component_ids, parameters, matrix = build_mcd_matrix(frames, "0h")
    assert component_ids == ["c1", "c2"]
    assert parameters == ["iddq", "leakage"]
    assert len(matrix) == 2
    assert len(matrix[0]) == 2


def test_build_mcd_matrix_excludes_component_missing_a_parameter():
    readings = (
        _component_with_0h_24h("c1", "iddq", 10.0, 10.0)
        + _component_with_0h_24h("c1", "leakage", 4.0, 4.0)
        + _component_with_0h_24h("c2", "iddq", 20.0, 20.0)  # c2 has no leakage reading
    )
    frames = compute(_lot(readings))
    component_ids, parameters, matrix = build_mcd_matrix(frames, "0h")
    assert component_ids == ["c1"]
