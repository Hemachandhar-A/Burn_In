"""E1 steps 4-6: power-law healthy drift, Arrhenius-scaled defect trajectories, and the
shared defect-severity correlation factor.

7.3 checklist (Generator row): determinism (same seed -> identical output) is extended here to
trajectories; the healthy-vs-defective divergence test is this session's (P1.2) named deliverable.
Noise, tester offset, quantization and the Reading-shaped output land in P1.3 - values here are
the noise-free physical trajectories those later steps are applied on top of.
"""
from itertools import pairwise

import numpy as np
import pytest
from scipy.stats import spearmanr

from contracts import ScreeningConfig
from generator.baselines import generate_lot_baselines
from generator.parameters import PARAMETERS
from generator.trajectories import (
    BOLTZMANN_EV_PER_K,
    DEFAULT_CHECKPOINT_HOURS,
    DEFECT_ARCHETYPES,
    TrajectoryParams,
    arrhenius_acceleration_factor,
    generate_lot_trajectories,
)

ALL_DEFECTIVE = ScreeningConfig(defect_prevalence_range=(1.0, 1.0))
ALL_HEALTHY = ScreeningConfig(defect_prevalence_range=(0.0, 0.0))


def _lot(n_parts=77, seed=42, config=None):
    config = config or ScreeningConfig()
    baselines = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=n_parts, seed=seed, config=config)
    return generate_lot_trajectories(baselines, seed=seed, config=config)


def _mixed_lot(n_parts=1500, seed=7):
    # Enough of both populations for distribution-level assertions to be stable.
    return _lot(n_parts=n_parts, seed=seed, config=ScreeningConfig(defect_prevalence_range=(0.3, 0.3)))


def _rel_drift(part, name, idx):
    values = part.values[name]
    return (values[idx] - values[0]) / values[0]


# --- determinism (7.3) ---------------------------------------------------------

def test_determinism_same_seed_identical_trajectories():
    assert _lot(seed=42) == _lot(seed=42)


def test_different_seed_produces_different_trajectories():
    baselines = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=30, seed=1)
    a = generate_lot_trajectories(baselines, seed=1)
    b = generate_lot_trajectories(baselines, seed=2)
    assert [p.values for p in a.parts] != [p.values for p in b.parts]


def test_determinism_unaffected_by_polluted_global_numpy_state():
    clean = _lot(n_parts=30, seed=99)
    np.random.seed(12345)
    for _ in range(50):
        np.random.random()
    assert _lot(n_parts=30, seed=99) == clean


def test_values_at_a_checkpoint_do_not_depend_on_which_later_checkpoints_are_requested():
    # A part's 0h/24h values must be a function of that part's own draws and t only - asking
    # for fewer checkpoints (e.g. an In-Progress lot) must not reshuffle the early values.
    baselines = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=40, seed=3)
    full = generate_lot_trajectories(baselines, seed=3, checkpoint_hours=(0.0, 24.0, 96.0, 168.0))
    early = generate_lot_trajectories(baselines, seed=3, checkpoint_hours=(0.0, 24.0))
    for pf, pe in zip(full.parts, early.parts):
        for name in PARAMETERS:
            assert pf.values[name][:2] == pe.values[name]


# --- structure -------------------------------------------------------------------

def test_default_checkpoints_are_the_burn_in_schedule():
    lot = _lot(n_parts=5)
    assert DEFAULT_CHECKPOINT_HOURS == (0.0, 24.0, 96.0, 168.0)
    assert lot.checkpoint_hours == DEFAULT_CHECKPOINT_HOURS
    for part in lot.parts:
        assert set(part.values) == set(PARAMETERS)
        for series in part.values.values():
            assert len(series) == len(DEFAULT_CHECKPOINT_HOURS)


def test_parts_mirror_baselines_one_to_one():
    baselines = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=50, seed=4)
    lot = generate_lot_trajectories(baselines, seed=4)
    assert lot.lot_id == baselines.lot_id and lot.part_number == baselines.part_number
    assert [p.component_id for p in lot.parts] == [p.component_id for p in baselines.parts]
    assert [p.is_defective for p in lot.parts] == [p.is_defective for p in baselines.parts]


def test_value_at_zero_hours_equals_baseline():
    baselines = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=50, seed=5, config=ALL_DEFECTIVE)
    lot = generate_lot_trajectories(baselines, seed=5, config=ALL_DEFECTIVE)
    for pb, pt in zip(baselines.parts, lot.parts):
        for name in PARAMETERS:
            assert pt.values[name][0] == pytest.approx(pb.baseline[name], rel=1e-12)


def test_all_values_finite_and_positive():
    for part in _mixed_lot(n_parts=500).parts:
        for series in part.values.values():
            assert all(np.isfinite(v) and v > 0 for v in series)


def test_irregular_checkpoints_are_honored():
    baselines = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=10, seed=6, config=ALL_HEALTHY)
    hours = (0.0, 23.5, 97.25, 170.0)
    lot = generate_lot_trajectories(baselines, seed=6, checkpoint_hours=hours, config=ALL_HEALTHY)
    assert lot.checkpoint_hours == hours
    for part in lot.parts:
        for name in PARAMETERS:
            expected = [part.baseline[name] + part.drift_amplitude[name] * t ** part.drift_exponent[name]
                        for t in hours]
            assert part.values[name] == pytest.approx(tuple(expected), rel=1e-12)


def test_trajectories_are_immutable():
    from dataclasses import FrozenInstanceError

    lot = _lot(n_parts=3)
    with pytest.raises(FrozenInstanceError):
        lot.lot_id = "L2"
    with pytest.raises(FrozenInstanceError):
        lot.parts[0].defect_type = "progressive"


# --- E1 step 4: healthy power-law drift ------------------------------------------

def test_healthy_trajectory_is_exactly_baseline_plus_power_law():
    lot = _lot(n_parts=200, seed=8, config=ALL_HEALTHY)
    for part in lot.parts:
        for name in PARAMETERS:
            expected = [
                part.baseline[name] + part.drift_amplitude[name] * t ** part.drift_exponent[name]
                for t in lot.checkpoint_hours
            ]
            assert part.values[name] == pytest.approx(tuple(expected), rel=1e-12)


def test_healthy_drift_exponent_within_config_range_and_randomized():
    config = ScreeningConfig(defect_prevalence_range=(0.0, 0.0))
    lo, hi = config.power_law_exponent_range
    lot = _lot(n_parts=200, seed=9, config=config)
    exponents = [p.drift_exponent[name] for p in lot.parts for name in PARAMETERS]
    assert all(lo <= n <= hi for n in exponents)
    assert len(set(exponents)) == len(exponents)  # randomized per part (and per parameter)


def test_drift_exponent_honors_a_widened_config_range():
    # P1.3's "wider drift-exponent range" held-out family is driven by this same config field.
    config = ScreeningConfig(defect_prevalence_range=(0.0, 0.0), power_law_exponent_range=(0.05, 0.6))
    lot = _lot(n_parts=400, seed=9, config=config)
    exponents = [p.drift_exponent["iddq"] for p in lot.parts]
    assert min(exponents) < 0.15 and max(exponents) > 0.30


def test_healthy_drift_amplitude_positive_and_randomized_per_part():
    lot = _lot(n_parts=100, seed=10, config=ALL_HEALTHY)
    for name in PARAMETERS:
        amplitudes = [p.drift_amplitude[name] for p in lot.parts]
        assert all(a > 0 for a in amplitudes)  # increase-is-worse for all three (context.md 3.3)
        assert len(set(amplitudes)) == len(amplitudes)


def test_healthy_trajectories_are_monotone_non_decreasing():
    for part in _lot(n_parts=200, seed=11, config=ALL_HEALTHY).parts:
        for series in part.values.values():
            assert all(b >= a for a, b in pairwise(series))


def test_healthy_drift_is_sub_linear_in_time():
    # context.md 1.4: a straight-line 0->24h extrapolation overshoots a healthy part's real 168h
    # drift - the whole reason Module B can't extrapolate naively.
    lot = _lot(n_parts=200, seed=12, config=ALL_HEALTHY)
    for part in lot.parts:
        for name in PARAMETERS:
            v0, v24, _, v168 = part.values[name]
            linear_extrapolation = v0 + (v24 - v0) * 7.0
            assert v168 < linear_extrapolation


def test_healthy_parts_carry_no_defect_ground_truth():
    for part in _lot(n_parts=100, seed=13, config=ALL_HEALTHY).parts:
        assert part.defect_type is None
        assert part.activation_energy_eV is None
        assert part.acceleration_factor is None
        assert part.defect_onset_hours is None
        assert part.defect_severity is None


def test_healthy_drift_amplitudes_are_near_independent_across_parameters():
    # E1 step 6: healthy-part noise stays close to independent across parameters.
    parts = _lot(n_parts=2000, seed=14, config=ALL_HEALTHY).parts
    rel = {name: [_rel_drift(p, name, 3) for p in parts] for name in PARAMETERS}
    names = list(PARAMETERS)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            rho, _ = spearmanr(rel[names[i]], rel[names[j]])
            assert abs(rho) < 0.1, (names[i], names[j], rho)


# --- E1 step 5: Arrhenius-scaled defect trajectories -------------------------------

def test_arrhenius_factor_is_one_at_reference_temperature():
    assert arrhenius_acceleration_factor(1.0, junction_temp_c=125.0, reference_temp_c=125.0) == pytest.approx(1.0)


def test_arrhenius_factor_matches_closed_form():
    ea, tj, tref = 0.7, 135.0, 125.0
    expected = np.exp(ea / BOLTZMANN_EV_PER_K * (1 / (tref + 273.15) - 1 / (tj + 273.15)))
    assert arrhenius_acceleration_factor(ea, junction_temp_c=tj, reference_temp_c=tref) == pytest.approx(expected)


def test_arrhenius_factor_grows_with_activation_energy_when_hotter_than_reference():
    low = arrhenius_acceleration_factor(0.3, junction_temp_c=130.0, reference_temp_c=125.0)
    high = arrhenius_acceleration_factor(2.0, junction_temp_c=130.0, reference_temp_c=125.0)
    assert 1.0 < low < high


def test_arrhenius_factor_below_one_when_cooler_than_reference():
    assert arrhenius_acceleration_factor(1.0, junction_temp_c=120.0, reference_temp_c=125.0) < 1.0


def test_arrhenius_rejects_non_positive_activation_energy():
    with pytest.raises(ValueError):
        arrhenius_acceleration_factor(0.0, junction_temp_c=125.0, reference_temp_c=125.0)


def test_arrhenius_rejects_temperature_at_or_below_absolute_zero():
    with pytest.raises(ValueError):
        arrhenius_acceleration_factor(1.0, junction_temp_c=-273.15, reference_temp_c=125.0)


def test_defective_parts_record_activation_energy_within_config_range():
    config = ScreeningConfig(defect_prevalence_range=(1.0, 1.0))
    lo, hi = config.activation_energy_range_eV
    lot = _lot(n_parts=300, seed=15, config=config)
    energies = [p.activation_energy_eV for p in lot.parts]
    assert all(lo <= ea <= hi for ea in energies)
    assert len(set(energies)) == len(energies)  # randomized per defect instance (context.md 3.3)


def test_recorded_acceleration_factor_is_consistent_with_recorded_ea_and_junction_temp():
    lot = _lot(n_parts=100, seed=16, config=ALL_DEFECTIVE)
    ref = TrajectoryParams().reference_temp_c
    for p in lot.parts:
        expected = arrhenius_acceleration_factor(p.activation_energy_eV, p.junction_temp_c, ref)
        assert p.acceleration_factor == pytest.approx(expected)


def test_every_defective_part_has_a_known_archetype_and_all_archetypes_occur():
    lot = _lot(n_parts=600, seed=17, config=ALL_DEFECTIVE)
    types = {p.defect_type for p in lot.parts}
    assert types == set(DEFECT_ARCHETYPES)


def test_post_24h_archetype_exists_and_is_invisible_at_or_before_24h():
    # E1 step 5: "some defect archetypes activate only after the 24h checkpoint".
    late = [name for name, a in DEFECT_ARCHETYPES.items() if a.onset_range_hours[0] >= 24.0]
    assert late, "at least one archetype must activate only after the 24h checkpoint"

    lot = _lot(n_parts=600, seed=18, config=ALL_DEFECTIVE)
    late_parts = [p for p in lot.parts if p.defect_type in late]
    assert late_parts
    for part in late_parts:
        assert part.defect_onset_hours > 24.0
        for name in PARAMETERS:
            for t, v in zip(lot.checkpoint_hours, part.values[name]):
                healthy = part.baseline[name] + part.drift_amplitude[name] * t ** part.drift_exponent[name]
                if t <= 24.0:
                    assert v == pytest.approx(healthy, rel=1e-12)  # defect term exactly zero
                elif t > part.defect_onset_hours:
                    assert v > healthy


def test_defect_term_is_added_on_top_of_healthy_drift():
    lot = _lot(n_parts=200, seed=19, config=ALL_DEFECTIVE)
    for part in lot.parts:
        for name in PARAMETERS:
            v168 = part.values[name][3]
            healthy_168 = part.baseline[name] + part.drift_amplitude[name] * 168.0 ** part.drift_exponent[name]
            assert v168 > healthy_168


# --- the divergence test (P1.2's named deliverable) --------------------------------

def test_defective_parts_diverge_from_healthy_parts_by_168h():
    parts = _mixed_lot().parts
    healthy = [p for p in parts if not p.is_defective]
    defective = [p for p in parts if p.is_defective]
    assert len(healthy) > 500 and len(defective) > 200

    for name in PARAMETERS:
        h = np.array([_rel_drift(p, name, 3) for p in healthy])
        d = np.array([_rel_drift(p, name, 3) for p in defective])
        healthy_p95 = np.percentile(h, 95)
        # Median defective drift sits well beyond the healthy tail, and most defectives clear it.
        assert np.median(d) > 2.0 * healthy_p95, name
        assert np.mean(d > healthy_p95) > 0.75, name


def test_early_archetypes_already_diverge_at_24h():
    parts = _mixed_lot(seed=21).parts
    healthy = [p for p in parts if not p.is_defective]
    early = [p for p in parts if p.is_defective and DEFECT_ARCHETYPES[p.defect_type].onset_range_hours[1] == 0.0]
    assert early
    h = np.array([_rel_drift(p, "iddq", 1) for p in healthy])
    e = np.array([_rel_drift(p, "iddq", 1) for p in early])
    assert np.median(e) > np.percentile(h, 95)


def test_healthy_parts_do_not_diverge_from_each_other():
    # The flip side of divergence: healthy relative drift stays in a tight, bounded band.
    parts = _lot(n_parts=1000, seed=22, config=ALL_HEALTHY).parts
    for name in PARAMETERS:
        rel = np.array([_rel_drift(p, name, 3) for p in parts])
        assert np.all(rel > 0)
        assert np.percentile(rel, 99) < 0.5, name


# --- E1 step 6: shared defect-severity correlation ----------------------------------

def test_defect_severity_is_correlated_across_parameters_for_defective_parts():
    parts = _lot(n_parts=1500, seed=23, config=ALL_DEFECTIVE).parts
    sev = {name: [p.defect_severity[name] for p in parts] for name in PARAMETERS}
    names = list(PARAMETERS)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            rho, _ = spearmanr(sev[names[i]], sev[names[j]])
            assert rho > 0.6, (names[i], names[j], rho)


def test_severity_correlation_knob_can_decorrelate_defects():
    # P1.3's "altered parameter-correlation structure" held-out family turns this knob.
    config = ALL_DEFECTIVE
    baselines = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=1500, seed=24, config=config)
    lot = generate_lot_trajectories(baselines, seed=24, config=config, params=TrajectoryParams(severity_correlation=0.0))
    iddq = [p.defect_severity["iddq"] for p in lot.parts]
    leak = [p.defect_severity["leakage"] for p in lot.parts]
    rho, _ = spearmanr(iddq, leak)
    assert abs(rho) < 0.1


def test_full_severity_correlation_gives_identical_severity_ranks():
    baselines = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=300, seed=25, config=ALL_DEFECTIVE)
    lot = generate_lot_trajectories(
        baselines, seed=25, config=ALL_DEFECTIVE, params=TrajectoryParams(severity_correlation=1.0)
    )
    iddq = [p.defect_severity["iddq"] for p in lot.parts]
    delay = [p.defect_severity["prop_delay"] for p in lot.parts]
    rho, _ = spearmanr(iddq, delay)
    assert rho == pytest.approx(1.0)


# --- edge cases ---------------------------------------------------------------------

def test_single_part_lot():
    lot = _lot(n_parts=1, seed=26)
    assert len(lot.parts) == 1


def test_all_healthy_and_all_defective_lots():
    assert not any(p.is_defective for p in _lot(n_parts=50, config=ALL_HEALTHY).parts)
    assert all(p.is_defective for p in _lot(n_parts=50, config=ALL_DEFECTIVE).parts)


def test_single_checkpoint_at_zero():
    baselines = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=5, seed=27)
    lot = generate_lot_trajectories(baselines, seed=27, checkpoint_hours=(0.0,))
    assert all(len(s) == 1 for p in lot.parts for s in p.values.values())


def test_accepts_numpy_integer_seed_and_matches_python_int():
    baselines = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=10, seed=28)
    assert generate_lot_trajectories(baselines, seed=np.int64(28)) == generate_lot_trajectories(baselines, seed=28)


def test_accepts_list_of_checkpoints_and_stores_tuple():
    baselines = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=3, seed=29)
    lot = generate_lot_trajectories(baselines, seed=29, checkpoint_hours=[0, 24, 168])
    assert lot.checkpoint_hours == (0.0, 24.0, 168.0)


@pytest.fixture
def baselines():
    return generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=5, seed=1)


def test_rejects_wrong_type_lot():
    with pytest.raises(TypeError):
        generate_lot_trajectories({"lot_id": "L1"}, seed=1)


@pytest.mark.parametrize("seed", [1.5, "1", True, None])
def test_rejects_non_integer_seed(baselines, seed):
    with pytest.raises(TypeError):
        generate_lot_trajectories(baselines, seed=seed)


def test_rejects_negative_seed(baselines):
    with pytest.raises(ValueError):
        generate_lot_trajectories(baselines, seed=-1)


def test_rejects_wrong_type_config_and_params(baselines):
    with pytest.raises(TypeError):
        generate_lot_trajectories(baselines, seed=1, config={"power_law_exponent_range": (0.1, 0.2)})
    with pytest.raises(TypeError):
        generate_lot_trajectories(baselines, seed=1, params={"severity_correlation": 0.5})


@pytest.mark.parametrize(
    "hours",
    [
        (),  # empty
        (0.0, 24.0, 24.0),  # not strictly increasing
        (24.0, 0.0),  # decreasing
        (-1.0, 24.0),  # negative elapsed time
        (0.0, float("nan")),
        (0.0, float("inf")),
        ("0", "24"),
        (0.0, True),
    ],
)
def test_rejects_invalid_checkpoints(baselines, hours):
    with pytest.raises((ValueError, TypeError)):
        generate_lot_trajectories(baselines, seed=1, checkpoint_hours=hours)


@pytest.mark.parametrize("rng", [(0.0, 0.3), (-0.1, 0.3), (0.3, 0.15), (0.2, 1.0), (0.1, float("nan"))])
def test_rejects_invalid_power_law_exponent_range(baselines, rng):
    # n must lie in (0, 1): n <= 0 is no drift / decay, n >= 1 is no longer sub-linear NBTI drift.
    with pytest.raises(ValueError):
        generate_lot_trajectories(baselines, seed=1, config=ScreeningConfig(power_law_exponent_range=rng))


@pytest.mark.parametrize("rng", [(0.0, 1.0), (-0.3, 1.0), (2.0, 0.3), (0.3, float("inf"))])
def test_rejects_invalid_activation_energy_range(baselines, rng):
    with pytest.raises(ValueError):
        generate_lot_trajectories(baselines, seed=1, config=ScreeningConfig(activation_energy_range_eV=rng))


def test_accepts_degenerate_ranges_lo_equals_hi():
    config = ScreeningConfig(
        defect_prevalence_range=(1.0, 1.0), power_law_exponent_range=(0.25, 0.25), activation_energy_range_eV=(0.7, 0.7)
    )
    lot = _lot(n_parts=20, seed=30, config=config)
    assert {p.drift_exponent["iddq"] for p in lot.parts} == {0.25}
    assert {p.activation_energy_eV for p in lot.parts} == {0.7}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"severity_correlation": -0.1},
        {"severity_correlation": 1.1},
        {"severity_correlation": float("nan")},
        {"severity_median": 0.0},
        {"severity_log_sigma": -0.1},
        {"reference_temp_c": -300.0},
        {"lot_temp_tolerance_c": -1.0},
        {"self_heating_range_c": (5.0, 1.0)},
        {"self_heating_range_c": (-1.0, 5.0)},
    ],
)
def test_rejects_invalid_trajectory_params(kwargs):
    with pytest.raises(ValueError):
        TrajectoryParams(**kwargs)


def test_ground_truth_fields_are_not_production_schema_fields():
    from contracts import LotDataset, Reading

    for field in ("is_defective", "defect_type", "activation_energy_eV", "defect_severity"):
        assert field not in Reading.model_fields
        assert field not in LotDataset.model_fields
