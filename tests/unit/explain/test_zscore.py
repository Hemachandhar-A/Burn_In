"""P5.7 (explain/zscore.py): per-parameter robust z-score table for one part, read directly off
FeatureFrame - no z-score is recomputed here."""
import pytest

from contracts import FeatureFrame
from explain.models import ZScoreTable
from explain.zscore import build_zscore_table
from harness.golden import GOLDEN_COMPONENT_ID, GOLDEN_LOT_MEDIAN_UA, GOLDEN_PARAMETER, GOLDEN_PART_VALUE_UA, golden_feature_frames


def _component_frames(frames: list[FeatureFrame], component_id: str) -> list[FeatureFrame]:
    return [f for f in frames if f.component_id == component_id]


def test_golden_part_leakage_row_shows_value_45_and_lot_median_10():
    frames = _component_frames(golden_feature_frames(), GOLDEN_COMPONENT_ID)
    table = build_zscore_table(frames, "0h")
    assert isinstance(table, ZScoreTable)
    leakage_row = next(r for r in table.rows if r.parameter == GOLDEN_PARAMETER)
    assert leakage_row.value == pytest.approx(GOLDEN_PART_VALUE_UA)
    assert leakage_row.lot_median == pytest.approx(GOLDEN_LOT_MEDIAN_UA)


def test_table_has_one_row_per_parameter_sorted_by_name():
    frames = _component_frames(golden_feature_frames(), GOLDEN_COMPONENT_ID)
    table = build_zscore_table(frames, "0h")
    names = [r.parameter for r in table.rows]
    assert names == sorted(names)
    assert set(names) == {f.parameter for f in frames}


def test_z_is_read_from_the_frames_own_robust_z_not_recomputed():
    frames = _component_frames(golden_feature_frames(), GOLDEN_COMPONENT_ID)
    table = build_zscore_table(frames, "0h")
    by_param = {f.parameter: f for f in frames}
    for row in table.rows:
        assert row.z == pytest.approx(by_param[row.parameter].robust_z["0h"])


def test_24h_checkpoint_also_supported():
    frames = _component_frames(golden_feature_frames(), GOLDEN_COMPONENT_ID)
    table = build_zscore_table(frames, "24h")
    assert table.checkpoint == "24h"
    leakage_row = next(r for r in table.rows if r.parameter == GOLDEN_PARAMETER)
    assert leakage_row.value == pytest.approx(GOLDEN_PART_VALUE_UA)


def test_rejects_a_checkpoint_with_no_named_lot_median_field():
    frames = _component_frames(golden_feature_frames(), GOLDEN_COMPONENT_ID)
    with pytest.raises(ValueError):
        build_zscore_table(frames, "96h")


def test_rejects_frames_from_more_than_one_component():
    frames = golden_feature_frames()  # every component, not just one
    with pytest.raises(ValueError):
        build_zscore_table(frames, "0h")


def test_rejects_empty_frames():
    with pytest.raises(ValueError):
        build_zscore_table([], "0h")
