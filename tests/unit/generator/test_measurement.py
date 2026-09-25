"""E1 step 7: tester-offset correction via simulated reference parts, quantization, and proportional
Gaussian measurement noise, applied on top of P1.2's noise-free trajectories."""
import math

import numpy as np
import pytest
from scipy.stats import kurtosis

from contracts import ScreeningConfig
from generator.baselines import generate_lot_baselines
from generator.measurement import MeasurementParams, measure_lot
from generator.parameters import PARAMETERS
from generator.trajectories import generate_lot_trajectories


def _per_param(value):
    return {name: value for name in PARAMETERS}


def _trajectories(n_parts=77, seed=3, checkpoint_hours=(0.0, 24.0, 96.0, 168.0)):
    config = ScreeningConfig()
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=n_parts, seed=seed, config=config)
    return generate_lot_trajectories(lot, seed=seed, config=config, checkpoint_hours=checkpoint_hours)


FINE = _per_param(1e-6)
NOISELESS = MeasurementParams(noise_frac=_per_param(0.0), resolution=FINE, tester_offset_sigma=_per_param(0.0))


def _on_grid(value, step):
    return abs(value / step - round(value / step)) < 1e-6


# --- determinism (7.3) ---------------------------------------------------------

def test_same_seed_identical_measurements():
    traj = _trajectories()
    assert measure_lot(traj, seed=11) == measure_lot(traj, seed=11)


def test_different_seed_different_noise():
    traj = _trajectories()
    assert measure_lot(traj, seed=11).values != measure_lot(traj, seed=12).values


def test_unaffected_by_global_numpy_state():
    traj = _trajectories()
    np.random.seed(0)
    a = measure_lot(traj, seed=5)
    np.random.seed(999)
    np.random.random(100)
    assert measure_lot(traj, seed=5) == a


# --- shape ---------------------------------------------------------------------

def test_every_part_parameter_checkpoint_measured():
    traj = _trajectories(n_parts=10)
    measured = measure_lot(traj, seed=1)
    assert measured.checkpoint_hours == traj.checkpoint_hours
    assert set(measured.values) == {p.component_id for p in traj.parts}
    for series_by_param in measured.values.values():
        assert set(series_by_param) == set(PARAMETERS)
        assert all(len(s) == len(traj.checkpoint_hours) for s in series_by_param.values())


# --- noise-free path is exact --------------------------------------------------

def test_noiseless_measurement_reproduces_true_values():
    traj = _trajectories(n_parts=20)
    measured = measure_lot(traj, seed=1, params=NOISELESS)
    for part in traj.parts:
        for name in PARAMETERS:
            assert measured.values[part.component_id][name] == pytest.approx(part.values[name], abs=1e-5)


# --- quantization --------------------------------------------------------------

def test_every_value_on_the_resolution_grid():
    params = MeasurementParams()
    measured = measure_lot(_trajectories(), seed=2, params=params)
    for series_by_param in measured.values.values():
        for name, series in series_by_param.items():
            assert all(_on_grid(v, params.resolution[name]) for v in series)


def test_coarse_quantization_error_bounded_by_half_step():
    step = _per_param(0.5)
    params = MeasurementParams(noise_frac=_per_param(0.0), resolution=step, tester_offset_sigma=_per_param(0.0))
    traj = _trajectories(n_parts=30)
    measured = measure_lot(traj, seed=2, params=params)
    for part in traj.parts:
        for name in PARAMETERS:
            for true, got in zip(part.values[name], measured.values[part.component_id][name]):
                assert abs(got - true) <= 0.5 / 2 + 1e-9
                assert _on_grid(got, 0.5)


def test_value_never_below_one_resolution_step():
    # A resolution coarser than the signal itself: a reading floors at the tester's resolution, never 0/negative.
    params = MeasurementParams(noise_frac=_per_param(0.0), resolution=_per_param(1000.0),
                               tester_offset_sigma=_per_param(0.0))
    measured = measure_lot(_trajectories(n_parts=5), seed=2, params=params)
    for series_by_param in measured.values.values():
        for series in series_by_param.values():
            assert all(v == 1000.0 for v in series)


# --- tester offset + reference-part correction ---------------------------------

def test_offset_is_drawn_per_checkpoint_and_recorded():
    traj = _trajectories()
    measured = measure_lot(traj, seed=4)
    offsets = measured.truth.tester_offset
    assert len(offsets) == len(traj.checkpoint_hours)
    assert all(set(o) == set(PARAMETERS) for o in offsets)
    assert len({o["iddq"] for o in offsets}) == len(offsets)  # different tester session per checkpoint


def test_reference_parts_recorded_and_stable():
    params = MeasurementParams(n_reference_parts=7)
    measured = measure_lot(_trajectories(), seed=4, params=params)
    for name in PARAMETERS:
        refs = measured.truth.reference_values[name]
        assert len(refs) == 7
        assert all(v > 0 for v in refs)


def test_large_offset_fully_corrected_when_noise_free():
    # Offset 10x the signal, zero noise: the reference parts pin the offset exactly, so it vanishes.
    params = MeasurementParams(noise_frac=_per_param(0.0), resolution=FINE, tester_offset_sigma=_per_param(100.0))
    traj = _trajectories(n_parts=20)
    measured = measure_lot(traj, seed=4, params=params)
    assert any(abs(o["iddq"]) > 10 for o in measured.truth.tester_offset)
    for part in traj.parts:
        for name in PARAMETERS:
            assert measured.values[part.component_id][name] == pytest.approx(part.values[name], abs=1e-4)


def test_offset_estimate_recorded_and_close_to_true_offset():
    measured = measure_lot(_trajectories(), seed=4, params=MeasurementParams(n_reference_parts=50))
    for true, est in zip(measured.truth.tester_offset, measured.truth.offset_estimate):
        for name in PARAMETERS:
            # residual error ~ noise_frac * reference value / sqrt(n_ref) - well under the offset scale
            assert abs(true[name] - est[name]) < MeasurementParams().tester_offset_sigma[name]


def test_more_reference_parts_shrink_residual_offset_error():
    traj = _trajectories(n_parts=2)

    def mean_residual(n_ref):
        errs = []
        for seed in range(60):
            truth = measure_lot(traj, seed=seed, params=MeasurementParams(n_reference_parts=n_ref)).truth
            errs += [abs(t["iddq"] - e["iddq"]) for t, e in zip(truth.tester_offset, truth.offset_estimate)]
        return float(np.mean(errs))

    assert mean_residual(40) < 0.5 * mean_residual(2)


# --- proportional Gaussian noise ------------------------------------------------

def test_noise_is_proportional_with_configured_sigma():
    noise = {"iddq": 0.03, "leakage": 0.05, "prop_delay": 0.01}
    # Many reference parts: the offset estimate's own noise (shared lot-wide per checkpoint) would otherwise
    # show up as a per-checkpoint bias on top of the per-reading noise this test isolates.
    params = MeasurementParams(noise_frac=noise, resolution=FINE, tester_offset_sigma=_per_param(0.0),
                               n_reference_parts=10_000)
    traj = _trajectories(n_parts=1500)
    measured = measure_lot(traj, seed=6, params=params)
    for name in PARAMETERS:
        rel = [
            (got - true) / true
            for part in traj.parts
            for true, got in zip(part.values[name], measured.values[part.component_id][name])
        ]
        assert np.std(rel) == pytest.approx(noise[name], rel=0.08)
        assert abs(np.mean(rel)) < 0.1 * noise[name]


def test_student_t_tail_option_is_heavier_tailed_than_gaussian():
    base = dict(resolution=FINE, tester_offset_sigma=_per_param(0.0), noise_frac=_per_param(0.05))
    traj = _trajectories(n_parts=1500)

    def rel_residuals(params):
        measured = measure_lot(traj, seed=8, params=params)
        return [
            (got - true) / true
            for part in traj.parts
            for true, got in zip(part.values["iddq"], measured.values[part.component_id]["iddq"])
        ]

    gaussian = rel_residuals(MeasurementParams(**base))
    heavy = rel_residuals(MeasurementParams(**base, noise_tail_df=5.0))
    assert abs(kurtosis(gaussian)) < 0.5
    assert kurtosis(heavy) > 1.5
    # scaled to the same standard deviation, so the regime differs in shape, not just scale
    assert np.std(heavy) == pytest.approx(0.05, rel=0.15)


# --- no future leakage (rule 6) -------------------------------------------------

def test_early_checkpoint_measurements_independent_of_later_checkpoints():
    early = measure_lot(_trajectories(checkpoint_hours=(0.0, 24.0)), seed=9)
    full = measure_lot(_trajectories(checkpoint_hours=(0.0, 24.0, 96.0, 168.0)), seed=9)
    for cid, series_by_param in early.values.items():
        for name, series in series_by_param.items():
            assert series == full.values[cid][name][:2]
    assert early.truth.tester_offset == full.truth.tester_offset[:2]


# --- validation -----------------------------------------------------------------

@pytest.mark.parametrize("kwargs", [
    {"noise_frac": {"iddq": 0.01, "leakage": 0.01}},  # missing a parameter
    {"noise_frac": {**_per_param(0.01), "extra": 0.01}},  # unknown parameter
    {"noise_frac": _per_param(-0.01)},
    {"noise_frac": _per_param(0.9)},
    {"noise_frac": _per_param(math.nan)},
    {"resolution": _per_param(0.0)},
    {"resolution": _per_param(math.inf)},
    {"tester_offset_sigma": _per_param(-1.0)},
    {"n_reference_parts": 0},
    {"n_reference_parts": 2.5},
    {"n_reference_parts": True},
    {"noise_tail_df": 2.0},
    {"noise_tail_df": math.inf},
])
def test_invalid_params_rejected(kwargs):
    with pytest.raises((ValueError, TypeError)):
        MeasurementParams(**kwargs)


def test_params_are_not_mutable_through_their_mappings():
    params = MeasurementParams()
    with pytest.raises(TypeError):
        params.noise_frac["iddq"] = 0.5


def test_caller_dict_mutation_does_not_leak_into_params():
    noise = _per_param(0.02)
    params = MeasurementParams(noise_frac=noise)
    noise["iddq"] = 0.4
    assert params.noise_frac["iddq"] == 0.02


@pytest.mark.parametrize("bad_seed", [-1, 1.5, True, "1"])
def test_invalid_seed_rejected(bad_seed):
    with pytest.raises((ValueError, TypeError)):
        measure_lot(_trajectories(n_parts=2), seed=bad_seed)


def test_wrong_type_inputs_rejected():
    with pytest.raises(TypeError):
        measure_lot("not a lot", seed=1)
    with pytest.raises(TypeError):
        measure_lot(_trajectories(n_parts=2), seed=1, params={})
