"""Block 4c Part 3b/3c: PartExplanation.trajectory, built at analysis time in
fusion/pipeline.py::_build_trajectory from the stored FeatureFrame for a part's worst parameter -
one TrajectoryPoint per MEASURED checkpoint (0h/24h always, 96h/168h only when the lot actually has
that reading), skipping absent/non-finite values, never guessing a lot_median where FeatureFrame
carries none (96h/168h)."""
import math

import pytest

from contracts import AnalysisResults, LotDataset, Reading, ScreeningConfig
from fusion.pipeline import run_full_pipeline
from harness.golden import (
    GOLDEN_COMPONENT_ID, GOLDEN_LOT_MEDIAN_UA, GOLDEN_PARAMETER, GOLDEN_PART_VALUE_UA, run_golden_pipeline,
)


def _reading(cid, lot_id, part_number, param, hour, value, unit="uA"):
    return Reading(component_id=cid, lot_id=lot_id, part_number=part_number, manufacturer="M",
                    date_code="D", parameter=param, checkpoint_hour=hour, value=value, unit=unit)


def test_golden_045_trajectory_has_0h_and_24h_with_value_45_and_median_10():
    result = run_golden_pipeline()
    trajectory = result.part_explanations[GOLDEN_COMPONENT_ID].trajectory
    by_hour = {p.checkpoint_hour: p for p in trajectory}

    assert 0 in by_hour and 24 in by_hour
    assert by_hour[24].value == pytest.approx(GOLDEN_PART_VALUE_UA)
    assert by_hour[24].lot_median == pytest.approx(GOLDEN_LOT_MEDIAN_UA)
    assert by_hour[0].value == pytest.approx(GOLDEN_PART_VALUE_UA)
    assert by_hour[0].lot_median == pytest.approx(GOLDEN_LOT_MEDIAN_UA)


def test_golden_045_trajectory_also_has_96h_and_168h_on_the_complete_golden_lot():
    """The golden lot is COMPLETE (harness/golden.py), so Module A's post-hoc screen carries the
    full series - the worst-parameter frame has real value_96h/value_168h, so both must appear."""
    result = run_golden_pipeline()
    trajectory = result.part_explanations[GOLDEN_COMPONENT_ID].trajectory
    hours = {p.checkpoint_hour for p in trajectory}
    assert hours == {0, 24, 96, 168}
    by_hour = {p.checkpoint_hour: p for p in trajectory}
    assert by_hour[96].value == pytest.approx(GOLDEN_PART_VALUE_UA)
    assert by_hour[168].value == pytest.approx(GOLDEN_PART_VALUE_UA)
    # FeatureFrame carries no lot_median_96h/168h field - never a guessed median at these checkpoints.
    assert by_hour[96].lot_median is None
    assert by_hour[168].lot_median is None


def test_no_nan_or_null_value_in_any_trajectory_point_on_the_golden_lot():
    result = run_golden_pipeline()
    for explanation in result.part_explanations.values():
        for point in explanation.trajectory:
            assert point.value is not None
            assert math.isfinite(point.value)
            if point.lot_median is not None:
                assert math.isfinite(point.lot_median)


def test_in_progress_part_trajectory_has_only_0h_and_24h():
    """A part on an IN_PROGRESS lot (0h/24h readings only, no 96h/168h at all) whose Module B
    result exceeds the safety slope - a non-PASS verdict reachable without Module A (which never
    runs before COMPLETE), same fixture shape as test_pipeline.py's B6a in-progress-lot tests."""
    readings = [
        _reading("c1", "L-TRAJ", "PN-TRAJ", "iddq", 0.0, 1.0),
        _reading("c1", "L-TRAJ", "PN-TRAJ", "iddq", 24.0, 500.0),
        _reading("c2", "L-TRAJ", "PN-TRAJ", "iddq", 0.0, 1.0),
        _reading("c2", "L-TRAJ", "PN-TRAJ", "iddq", 24.0, 1.1),
    ]
    lot = LotDataset(lot_id="L-TRAJ", part_number="PN-TRAJ", status="IN_PROGRESS",
                      readings=readings, account_id="a")
    result = run_full_pipeline(lot, ScreeningConfig())

    assert "c1" in result.part_explanations  # flagged by Module B's safety-slope check
    trajectory = result.part_explanations["c1"].trajectory
    hours = {p.checkpoint_hour for p in trajectory}
    assert hours == {0, 24}


def test_old_stored_json_without_trajectory_still_parses():
    """PartExplanation.trajectory defaults to [] - a pre-Block-4c stored row (no trajectory key at
    all) must still validate."""
    from contracts import PartExplanation

    old_shape = '{"shap_contributions": [], "mcd_contributions": [], "ecod_dimensions": [], ' \
                '"zscore_table": [], "explanation_sentence": "x", "confidence_qualifier": null, ' \
                '"severity_cap_note": null, "unavailable_forecast_note": null}'
    parsed = PartExplanation.model_validate_json(old_shape)
    assert parsed.trajectory == []
