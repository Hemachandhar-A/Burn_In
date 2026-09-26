"""P4.2 / E3 steps 3-5: MAPIE CQR with lot-boundary calibration, the calibrated safety slope, and the
early-reject flag."""

import math

import numpy as np
import pytest

from contracts import FeatureFrame, to_module_b_input
from features.compute import compute
from generator.lot import generate_lot
from module_b.calibration import (
    DEFAULT_CONFIDENCE_LEVEL,
    calibrate_drift_models,
    conformal_upper_quantile,
    drift_rate,
    forecast,
    split_lots,
)
from module_b.model import view_at_24h

TRAIN_SEEDS = range(14)
TEST_SEEDS = range(200, 206)


def _generated(seeds, part_number="PN-1"):
    lots = [generate_lot(f"{part_number}-L{s}", part_number, s, account_id="a") for s in seeds]
    frames = [f for g in lots for f in compute(g.dataset)]
    defective = {p.component_id for g in lots for p in g.ground_truth.baselines.parts if p.is_defective}
    return frames, defective


@pytest.fixture(scope="module")
def trained():
    frames, _ = _generated(TRAIN_SEEDS)
    return calibrate_drift_models(frames)


@pytest.fixture(scope="module")
def held_out():
    return _generated(TEST_SEEDS)


# --- lot-boundary split (AGENTS.md rule 8) ---------------------------------------------------


def test_split_is_disjoint_complete_and_deterministic():
    lots = [f"L{i}" for i in range(10)]
    train, cal = split_lots(lots, calibration_fraction=0.3, seed=0)
    assert set(train).isdisjoint(cal)
    assert set(train) | set(cal) == set(lots)
    assert len(cal) == 3
    assert split_lots(list(reversed(lots)), 0.3, 0) == (train, cal)


def test_split_keeps_at_least_one_lot_on_each_side():
    train, cal = split_lots(["A", "B"], calibration_fraction=0.01, seed=0)
    assert len(train) == 1 and len(cal) == 1
    train, cal = split_lots(["A", "B"], calibration_fraction=0.99, seed=0)
    assert len(train) == 1 and len(cal) == 1


def test_split_needs_two_lots():
    with pytest.raises(ValueError):
        split_lots(["A"], 0.3, 0)


def test_no_lot_is_on_both_sides_of_the_calibration(trained):
    for model in trained.values():
        assert set(model.train_lots).isdisjoint(model.calibration_lots)
        assert model.train_lots and model.calibration_lots


def test_a_part_number_with_a_single_lot_is_not_calibrated():
    frames, _ = _generated([1], part_number="PN-SOLO")
    assert calibrate_drift_models(frames) == {}


def test_in_progress_frames_never_enter_calibration():
    # Frames with no measured 168h can't be training or calibration rows - they don't count as lots either.
    frames, _ = _generated([1, 2])
    stripped = [f.model_copy(update={"value_168h": None, "delta_168h": None}) for f in frames]
    assert calibrate_drift_models(stripped) == {}


# --- CQR intervals ---------------------------------------------------------------------------


@pytest.mark.parametrize("horizon", ["96h", "24h"])
def test_interval_ordering_lower_le_point_le_upper(trained, held_out, horizon):
    # Part 7.3 Module B row: CQR interval ordering.
    frames, _ = held_out
    inputs = [to_module_b_input(f) for f in frames]
    if horizon == "24h":
        inputs = [view_at_24h(i) for i in inputs]
    for fc in forecast(trained, inputs):
        assert fc.interval_lower <= fc.predicted_168h <= fc.interval_upper


@pytest.mark.parametrize("horizon", ["96h", "24h"])
def test_held_out_lot_coverage_is_near_the_confidence_level(trained, held_out, horizon):
    # Lots never seen in training or calibration. CQR's guarantee assumes exchangeability, which lot
    # structure can violate (context.md 4.4, disclosed) - so this checks "close to", not ">=".
    frames, _ = held_out
    inputs = [to_module_b_input(f) for f in frames]
    if horizon == "24h":
        inputs = [view_at_24h(i) for i in inputs]
    fcs = forecast(trained, inputs)
    covered = [fc.interval_lower <= f.value_168h <= fc.interval_upper for f, fc in zip(frames, fcs)]
    assert np.mean(covered) >= DEFAULT_CONFIDENCE_LEVEL - 0.05


def test_24h_intervals_are_wider_than_96h_intervals(trained, held_out):
    frames, _ = held_out
    inputs = [to_module_b_input(f) for f in frames]
    w96 = [fc.interval_upper - fc.interval_lower for fc in forecast(trained, inputs)]
    w24 = [fc.interval_upper - fc.interval_lower for fc in forecast(trained, [view_at_24h(i) for i in inputs])]
    assert np.median(w24) > np.median(w96)


def test_each_horizon_has_its_own_calibration(trained):
    for model in trained.values():
        assert set(model.regressors) == {"96h", "24h"}


# --- safety slope ----------------------------------------------------------------------------


def test_conformal_upper_quantile_uses_the_finite_sample_rank():
    values = list(range(1, 20))  # n=19, q=0.9 -> rank ceil(20*0.9)=18
    assert conformal_upper_quantile(values, 0.9) == 18


def test_conformal_upper_quantile_refuses_too_few_values():
    # rank ceil((n+1)q) > n: no finite calibrated quantile exists - never silently fall back to the max.
    with pytest.raises(ValueError):
        conformal_upper_quantile([1.0, 2.0, 3.0], 0.95)


def test_drift_rate_is_predicted_change_per_hour_from_the_0h_read():
    i = to_module_b_input(_one_frame(t0=0.0))
    assert drift_rate(i, 10.0 + 16.8) == pytest.approx(0.1)
    j = to_module_b_input(_one_frame(t0=0.5))
    assert drift_rate(j, 10.0 + 16.75) == pytest.approx(0.1)


def test_safety_slope_is_finite_and_one_per_part_number_and_parameter(trained):
    assert set(trained) == {("PN-1", p) for p in ("iddq", "leakage", "prop_delay")}
    for model in trained.values():
        assert math.isfinite(model.safety_slope)


def test_safety_slope_ignores_training_lots_and_outlier_parts():
    frames, _ = _generated(range(6))
    base = calibrate_drift_models(frames)[("PN-1", "iddq")]
    cal = set(base.calibration_lots)

    # Wild 168h values on the training lots' parts: the slope comes from calibration lots only.
    moved_train = [
        f.model_copy(update={"value_168h": f.value_168h + 1e3}) if f.lot_id not in cal else f for f in frames
    ]
    assert calibrate_drift_models(moved_train)[("PN-1", "iddq")].safety_slope == base.safety_slope

    # ...and on calibration-lot parts outside the healthy robust-z core: once a part is an outlier, its
    # 168h value has no say in the slope.
    def outliers(shift):
        return [
            f.model_copy(update={"value_168h": f.value_168h + shift, "robust_z": {k: 50.0 for k in f.robust_z}})
            if f.lot_id in cal and f.component_id.endswith("0")
            else f
            for f in frames
        ]

    marked = calibrate_drift_models(outliers(0.0))[("PN-1", "iddq")].safety_slope
    assert calibrate_drift_models(outliers(1e3))[("PN-1", "iddq")].safety_slope == marked


# --- early-reject flag -----------------------------------------------------------------------


def test_flag_is_predicted_drift_rate_above_the_slope(trained, held_out):
    frames, _ = held_out
    for fc in forecast(trained, [to_module_b_input(f) for f in frames]):
        assert fc.exceeds_safety_slope == (fc.drift_rate > fc.safety_slope)
        assert fc.safety_slope == trained[("PN-1", fc.parameter)].safety_slope


@pytest.mark.parametrize("horizon", ["96h", "24h"])
def test_defective_parts_are_flagged_far_more_often_than_healthy_ones(trained, held_out, horizon):
    # Generator ground truth is harness-only; used here to check the flag means something.
    frames, defective = held_out
    inputs = [to_module_b_input(f) for f in frames]
    if horizon == "24h":
        inputs = [view_at_24h(i) for i in inputs]
    fcs = forecast(trained, inputs)
    flag_def = [fc.exceeds_safety_slope for f, fc in zip(frames, fcs) if f.component_id in defective]
    flag_ok = [fc.exceeds_safety_slope for f, fc in zip(frames, fcs) if f.component_id not in defective]
    assert flag_def and flag_ok
    assert np.mean(flag_def) > 3 * np.mean(flag_ok)
    assert np.mean(flag_ok) <= 0.10


# --- plumbing --------------------------------------------------------------------------------


def test_uncalibrated_key_gets_no_forecast(trained, held_out):
    frames, _ = held_out
    known = to_module_b_input(frames[0])
    out = forecast(trained, [known, known.model_copy(update={"part_number": "PN-X"}),
                             known.model_copy(update={"parameter": "vdd_ripple"})])
    assert out[0] is not None and out[1] is None and out[2] is None


def test_forecast_preserves_input_order_and_identity(trained, held_out):
    frames, _ = held_out
    inputs = [to_module_b_input(f) for f in frames[:40]][::-1]
    out = forecast(trained, inputs)
    assert [(o.component_id, o.parameter) for o in out] == [(i.component_id, i.parameter) for i in inputs]


def test_calibration_and_forecast_are_deterministic(held_out):
    frames, _ = _generated(range(4))
    inputs = [to_module_b_input(f) for f in held_out[0][:60]]
    assert forecast(calibrate_drift_models(frames), inputs) == forecast(calibrate_drift_models(frames), inputs)


def test_empty_inputs(trained):
    assert calibrate_drift_models([]) == {}
    assert forecast(trained, []) == []


def _one_frame(t0: float) -> FeatureFrame:
    return FeatureFrame(
        component_id="C1", lot_id="L1", part_number="PN-1", parameter="iddq",
        value_0h=10.0, value_24h=11.0, value_96h=None, value_168h=None,
        delta_24h=1.0, delta_96h=None, delta_168h=None,
        lot_median_0h=10.0, lot_median_24h=11.0, robust_z={"0h": 0.0, "24h": 0.0},
        lot_size=77, used_pooled_fallback=False, elapsed_hours={"0h": t0, "24h": 24.0},
    )
