"""Edge cases for E1 steps 4-6 beyond test_trajectories.py, organized around the Generator's 7.3 row:

- determinism (same seed -> identical output), including a pinned golden snapshot so the output
  can't drift silently between machines or refactors (AGENTS.md rule 9);
- ground-truth never leaking into any production-facing contract (models *and* DB columns);
- held-out family knobs that exist at this stage, plus a strict-xfail placeholder for the full
  five-family registry, which lands in P1.3;
- numerical robustness (overflow, non-finite values), malformed hand-built inputs, and aliasing.
"""
import dataclasses
import math
from itertools import pairwise

import numpy as np
import pytest
from pydantic import BaseModel
from scipy.stats import spearmanr

import contracts
from contracts import ScreeningConfig
from generator.baselines import generate_lot_baselines
from generator.parameters import PARAMETERS
from generator.schema import LotBaseline, PartBaseline
from generator.trajectories import (
    TrajectoryParams,
    arrhenius_acceleration_factor,
    generate_lot_trajectories,
)

ALL_DEFECTIVE = ScreeningConfig(defect_prevalence_range=(1.0, 1.0))
ALL_HEALTHY = ScreeningConfig(defect_prevalence_range=(0.0, 0.0))

GROUND_TRUTH_FIELDS = {
    "is_defective", "defect_type", "activation_energy_eV", "acceleration_factor", "defect_onset_hours",
    "defect_severity", "drift_exponent", "drift_amplitude", "junction_temp_c", "chamber_temp_c",
}


def _baselines(n_parts=20, seed=1, config=None):
    return generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=n_parts, seed=seed,
                                  config=config or ScreeningConfig())


def _healthy_component(part, name, t):
    return part.baseline[name] + part.drift_amplitude[name] * t ** part.drift_exponent[name]


def _hand_built_lot(parts):
    return LotBaseline(lot_id="L1", part_number="PN-1", lot_center={}, lot_die_sigma={},
                       defect_prevalence=0.0, parts=parts)


def _part(component_id="L1-0000", baseline=None, lot_id="L1", part_number="PN-1", is_defective=False):
    baseline = baseline if baseline is not None else {"iddq": 10.0, "leakage": 5.0, "prop_delay": 5.0}
    return PartBaseline(component_id=component_id, lot_id=lot_id, part_number=part_number,
                        baseline=baseline, is_defective=is_defective)


# =============================================================================================
# Determinism (7.3)
# =============================================================================================

# Pinned from seed=2026, 6 parts, prevalence (0.5, 0.5). If this changes, every downstream artifact
# built from a "same seed" (harness held-out sets, demo lots) silently changes too - so a change here
# must be deliberate, and the snapshot updated in the same commit that explains why.
GOLDEN_SEED = 2026
GOLDEN_CONFIG = ScreeningConfig(defect_prevalence_range=(0.5, 0.5))


def _golden_snapshot():
    config = GOLDEN_CONFIG
    lot = generate_lot_trajectories(_baselines(6, GOLDEN_SEED, config), seed=GOLDEN_SEED, config=config)
    return lot.chamber_temp_c, [(p.is_defective, p.defect_type, p.values["iddq"][-1], p.values["prop_delay"][1])
                                for p in lot.parts]


PINNED_CHAMBER_TEMP_C = 126.02667688357026
PINNED_PARTS = [
    (True, "latent_post_24h", 15.137954999983315, 2.7487590927366896),
    (False, None, 7.827527732426707, 2.829864468626934),
    (True, "early_saturating", 8.840885382617223, 3.2726485713709415),
    (False, None, 8.117347203187983, 3.0074527177876),
    (False, None, 12.742857768152378, 3.258314132232079),
    (False, None, 6.582174484473533, 2.640969878966952),
]


def test_golden_snapshot_is_pinned():
    chamber, parts = _golden_snapshot()
    assert chamber == pytest.approx(PINNED_CHAMBER_TEMP_C, rel=1e-12)
    assert len(parts) == len(PINNED_PARTS)
    for got, want in zip(parts, PINNED_PARTS):
        assert got[:2] == want[:2]
        assert got[2] == pytest.approx(want[2], rel=1e-9)
        assert got[3] == pytest.approx(want[3], rel=1e-9)


def test_repeated_calls_in_one_process_are_identical():
    baselines = _baselines(50, 3)
    runs = [generate_lot_trajectories(baselines, seed=3) for _ in range(5)]
    assert all(r == runs[0] for r in runs)


def test_determinism_with_very_large_seed():
    seed = 2**100
    baselines = _baselines(10, 1)
    assert generate_lot_trajectories(baselines, seed=seed) == generate_lot_trajectories(baselines, seed=seed)
    assert generate_lot_trajectories(baselines, seed=seed) != generate_lot_trajectories(baselines, seed=seed + 1)


def test_healthy_component_is_unaffected_by_defect_status():
    # Flipping a part's defect status (e.g. a different prevalence draw) must not reshuffle its healthy
    # drift - both populations draw the same random sequence, and the defect term is purely additive.
    baselines = _baselines(30, 4, ALL_HEALTHY)
    flipped = dataclasses.replace(
        baselines, parts=[dataclasses.replace(p, is_defective=True) for p in baselines.parts]
    )
    healthy = generate_lot_trajectories(baselines, seed=4)
    defective = generate_lot_trajectories(flipped, seed=4)
    for h, d in zip(healthy.parts, defective.parts):
        assert h.drift_exponent == d.drift_exponent
        assert h.drift_amplitude == d.drift_amplitude
        assert h.junction_temp_c == d.junction_temp_c
        for name in PARAMETERS:
            assert all(dv >= hv for hv, dv in zip(h.values[name], d.values[name]))


def test_healthy_trajectories_unaffected_by_defect_only_config_fields():
    # Changing the activation-energy range only changes defect draws, never healthy ones.
    baselines = _baselines(30, 5, ALL_HEALTHY)
    a = generate_lot_trajectories(baselines, seed=5, config=ScreeningConfig(activation_energy_range_eV=(0.3, 2.0)))
    b = generate_lot_trajectories(baselines, seed=5, config=ScreeningConfig(activation_energy_range_eV=(0.5, 0.6)))
    assert [p.values for p in a.parts] == [p.values for p in b.parts]


def test_healthy_trajectories_unaffected_by_severity_params():
    baselines = _baselines(30, 6, ALL_HEALTHY)
    a = generate_lot_trajectories(baselines, seed=6)
    b = generate_lot_trajectories(baselines, seed=6, params=TrajectoryParams(severity_median=5.0,
                                                                              severity_correlation=0.1))
    assert [p.values for p in a.parts] == [p.values for p in b.parts]


def test_trajectory_stream_is_independent_of_the_baseline_stream():
    # Same integer seed feeds both stages; the trajectory draws must come from a different stream,
    # otherwise e.g. a part's baseline and its drift exponent would be the same underlying draw.
    baselines = _baselines(2000, 7, ALL_HEALTHY)
    lot = generate_lot_trajectories(baselines, seed=7)
    rho, _ = spearmanr([p.baseline["iddq"] for p in lot.parts], [p.drift_exponent["iddq"] for p in lot.parts])
    assert abs(rho) < 0.1


def test_checkpoint_input_type_does_not_change_output():
    baselines = _baselines(10, 8)
    ref = generate_lot_trajectories(baselines, seed=8, checkpoint_hours=(0.0, 24.0, 96.0, 168.0))
    for hours in ([0, 24, 96, 168], np.array([0.0, 24.0, 96.0, 168.0]), (np.float32(0), 24, 96.0, np.int64(168))):
        assert generate_lot_trajectories(baselines, seed=8, checkpoint_hours=hours) == ref


def test_checkpoint_hours_stored_as_plain_python_floats():
    lot = generate_lot_trajectories(_baselines(3, 9), seed=9, checkpoint_hours=np.array([0, 24, 168]))
    assert all(type(h) is float for h in lot.checkpoint_hours)
    assert all(type(v) is float for p in lot.parts for s in p.values.values() for v in s)


def test_negative_zero_checkpoint_is_normalized():
    lot = generate_lot_trajectories(_baselines(3, 10), seed=10, checkpoint_hours=(-0.0, 24.0))
    assert math.copysign(1.0, lot.checkpoint_hours[0]) == 1.0
    for part in lot.parts:
        for name in PARAMETERS:
            assert part.values[name][0] == pytest.approx(part.baseline[name], rel=1e-12)


# =============================================================================================
# Ground truth never leaks into the production schema (7.3)
# =============================================================================================

def _production_models():
    return [obj for obj in vars(contracts).values()
            if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel]


def test_no_production_pydantic_model_has_a_ground_truth_field():
    models = _production_models()
    assert contracts.Reading in models and contracts.LotDataset in models
    for model in models:
        leaked = GROUND_TRUTH_FIELDS & set(model.model_fields)
        assert not leaked, f"{model.__name__} exposes ground truth: {leaked}"


def test_no_database_table_has_a_ground_truth_column():
    for table in contracts.Base.metadata.tables.values():
        leaked = GROUND_TRUTH_FIELDS & {c.name for c in table.columns}
        assert not leaked, f"table {table.name} exposes ground truth: {leaked}"


def test_trajectory_structures_still_carry_ground_truth_for_the_sidecar():
    # The flip side: the harness needs these, so they must exist on the internal structures.
    from generator.schema import LotTrajectories, PartTrajectory

    internal = {f.name for f in dataclasses.fields(PartTrajectory)} | {f.name for f in dataclasses.fields(LotTrajectories)}
    assert GROUND_TRUTH_FIELDS <= internal


def test_trajectories_are_not_production_models():
    lot = generate_lot_trajectories(_baselines(3, 11), seed=11)
    assert not isinstance(lot, BaseModel)
    assert not isinstance(lot.parts[0], BaseModel)


def test_trajectory_values_carry_no_ground_truth_labels():
    # The per-checkpoint value payload is exactly {parameter: floats} - nothing that labels the part.
    for part in generate_lot_trajectories(_baselines(20, 12, ALL_DEFECTIVE), seed=12, config=ALL_DEFECTIVE).parts:
        assert set(part.values) == set(PARAMETERS)
        assert all(isinstance(v, float) for s in part.values.values() for v in s)


# =============================================================================================
# Held-out families (7.3) - the knobs this stage owns, plus the P1.3 registry placeholder
# =============================================================================================

@pytest.mark.xfail(raises=ImportError, strict=True,
                   reason="Five-family registry is E1 step 9 - lands in P1.3. Strict: remove this marker then.")
def test_all_five_held_out_families_present():
    from generator.families import HELD_OUT_FAMILIES

    assert set(HELD_OUT_FAMILIES) == {
        "baseline", "wider_drift_exponent", "higher_defect_prevalence", "different_noise_regime",
        "altered_correlation",
    }


def test_wider_exponent_family_knob_widens_exponent_spread():
    narrow = generate_lot_trajectories(_baselines(500, 13, ALL_HEALTHY), seed=13, config=ScreeningConfig())
    wide_cfg = ScreeningConfig(power_law_exponent_range=(0.05, 0.6))
    wide = generate_lot_trajectories(_baselines(500, 13, ALL_HEALTHY), seed=13, config=wide_cfg)
    assert np.std([p.drift_exponent["iddq"] for p in wide.parts]) > 2 * np.std(
        [p.drift_exponent["iddq"] for p in narrow.parts])


def test_higher_prevalence_family_knob_yields_more_defective_trajectories():
    low_cfg = ScreeningConfig(defect_prevalence_range=(0.01, 0.08))
    high_cfg = ScreeningConfig(defect_prevalence_range=(0.2, 0.3))
    low = generate_lot_trajectories(_baselines(1000, 14, low_cfg), seed=14, config=low_cfg)
    high = generate_lot_trajectories(_baselines(1000, 14, high_cfg), seed=14, config=high_cfg)
    assert sum(p.is_defective for p in high.parts) > 2 * sum(p.is_defective for p in low.parts)


def test_altered_correlation_family_knob_is_monotone():
    baselines = _baselines(1500, 15, ALL_DEFECTIVE)
    rhos = []
    for corr in (0.0, 0.4, 0.8, 1.0):
        lot = generate_lot_trajectories(baselines, seed=15, config=ALL_DEFECTIVE,
                                        params=TrajectoryParams(severity_correlation=corr))
        rho, _ = spearmanr([p.defect_severity["iddq"] for p in lot.parts],
                           [p.defect_severity["leakage"] for p in lot.parts])
        rhos.append(rho)
    assert all(b > a for a, b in pairwise(rhos))


# =============================================================================================
# Numerical robustness
# =============================================================================================

def test_huge_checkpoint_hours_raise_clean_value_error_not_overflow():
    with pytest.raises(ValueError):
        generate_lot_trajectories(_baselines(20, 16, ALL_DEFECTIVE), seed=16, config=ALL_DEFECTIVE,
                                  checkpoint_hours=(0.0, 1e300))


def test_long_but_realistic_campaign_stays_finite():
    lot = generate_lot_trajectories(_baselines(100, 17, ALL_DEFECTIVE), seed=17, config=ALL_DEFECTIVE,
                                    checkpoint_hours=(0.0, 24.0, 168.0, 1000.0, 10000.0))
    assert all(math.isfinite(v) and v > 0 for p in lot.parts for s in p.values.values() for v in s)


def test_tiny_nonzero_checkpoint_is_finite_and_near_baseline():
    lot = generate_lot_trajectories(_baselines(20, 18, ALL_DEFECTIVE), seed=18, config=ALL_DEFECTIVE,
                                    checkpoint_hours=(1e-300, 1e-9))
    for part in lot.parts:
        for name in PARAMETERS:
            assert part.values[name][0] == pytest.approx(part.baseline[name], rel=1e-6)


def test_extreme_severity_sigma_raises_instead_of_emitting_inf():
    with pytest.raises(ValueError):
        generate_lot_trajectories(_baselines(50, 19, ALL_DEFECTIVE), seed=19, config=ALL_DEFECTIVE,
                                  params=TrajectoryParams(severity_log_sigma=400.0))


def test_extreme_activation_energy_raises_instead_of_overflowing():
    config = ScreeningConfig(defect_prevalence_range=(1.0, 1.0), activation_energy_range_eV=(1e6, 1e6))
    with pytest.raises(ValueError):
        generate_lot_trajectories(_baselines(5, 20, config), seed=20, config=config,
                                  params=TrajectoryParams(self_heating_range_c=(50.0, 50.0)))


def test_defective_trajectories_are_monotone_non_decreasing():
    lot = generate_lot_trajectories(_baselines(600, 21, ALL_DEFECTIVE), seed=21, config=ALL_DEFECTIVE,
                                    checkpoint_hours=tuple(float(h) for h in range(0, 170, 4)))
    for part in lot.parts:
        for series in part.values.values():
            assert all(b >= a for a, b in pairwise(series))


def test_zero_temperature_tolerance_and_no_self_heating_pin_junction_to_reference():
    params = TrajectoryParams(lot_temp_tolerance_c=0.0, self_heating_range_c=(0.0, 0.0))
    lot = generate_lot_trajectories(_baselines(20, 22, ALL_DEFECTIVE), seed=22, config=ALL_DEFECTIVE, params=params)
    assert lot.chamber_temp_c == pytest.approx(params.reference_temp_c)
    for part in lot.parts:
        assert part.acceleration_factor == pytest.approx(1.0)


def test_zero_severity_sigma_gives_identical_severity_everywhere():
    lot = generate_lot_trajectories(_baselines(20, 23, ALL_DEFECTIVE), seed=23, config=ALL_DEFECTIVE,
                                    params=TrajectoryParams(severity_log_sigma=0.0, severity_median=2.0))
    assert {v for p in lot.parts for v in p.defect_severity.values()} == {2.0}


def test_default_junction_temperature_within_declared_bounds():
    params = TrajectoryParams()
    lo = params.reference_temp_c - params.lot_temp_tolerance_c + params.self_heating_range_c[0]
    hi = params.reference_temp_c + params.lot_temp_tolerance_c + params.self_heating_range_c[1]
    for seed in range(20):
        lot = generate_lot_trajectories(_baselines(20, seed), seed=seed)
        assert all(lo <= p.junction_temp_c <= hi for p in lot.parts)


def test_latent_onset_is_strictly_after_24h_and_at_most_96h_across_many_draws():
    lot = generate_lot_trajectories(_baselines(3000, 24, ALL_DEFECTIVE), seed=24, config=ALL_DEFECTIVE)
    onsets = [p.defect_onset_hours for p in lot.parts if p.defect_type == "latent_post_24h"]
    assert len(onsets) > 500
    assert all(24.0 < t <= 96.0 for t in onsets)


def test_early_archetypes_have_zero_onset():
    lot = generate_lot_trajectories(_baselines(300, 25, ALL_DEFECTIVE), seed=25, config=ALL_DEFECTIVE)
    for p in lot.parts:
        if p.defect_type != "latent_post_24h":
            assert p.defect_onset_hours == 0.0


def test_archetype_mix_is_roughly_uniform():
    lot = generate_lot_trajectories(_baselines(3000, 26, ALL_DEFECTIVE), seed=26, config=ALL_DEFECTIVE)
    counts = {}
    for p in lot.parts:
        counts[p.defect_type] = counts.get(p.defect_type, 0) + 1
    assert all(800 < c < 1200 for c in counts.values()), counts


# =============================================================================================
# Arrhenius function input validation
# =============================================================================================

@pytest.mark.parametrize("ea", [float("inf"), float("nan"), -1.0])
def test_arrhenius_rejects_non_finite_or_negative_energy(ea):
    with pytest.raises(ValueError):
        arrhenius_acceleration_factor(ea, junction_temp_c=130.0, reference_temp_c=125.0)


@pytest.mark.parametrize("ea", [True, "0.7", None])
def test_arrhenius_rejects_non_numeric_energy(ea):
    with pytest.raises(TypeError):
        arrhenius_acceleration_factor(ea, junction_temp_c=130.0, reference_temp_c=125.0)


@pytest.mark.parametrize("tj", [float("inf"), float("nan"), -300.0])
def test_arrhenius_rejects_bad_junction_temperature(tj):
    with pytest.raises(ValueError):
        arrhenius_acceleration_factor(0.7, junction_temp_c=tj, reference_temp_c=125.0)


def test_arrhenius_rejects_bad_reference_temperature():
    with pytest.raises(ValueError):
        arrhenius_acceleration_factor(0.7, junction_temp_c=130.0, reference_temp_c=float("nan"))


def test_arrhenius_overflow_raises_value_error():
    with pytest.raises(ValueError):
        arrhenius_acceleration_factor(1e6, junction_temp_c=400.0, reference_temp_c=125.0)


def test_arrhenius_returns_plain_float():
    assert type(arrhenius_acceleration_factor(np.float64(0.7), 130.0, 125.0)) is float


# =============================================================================================
# TrajectoryParams
# =============================================================================================

def test_params_are_hashable_and_list_heating_range_is_normalized_to_tuple():
    params = TrajectoryParams(self_heating_range_c=[0.0, 8.0])
    assert params.self_heating_range_c == (0.0, 8.0)
    hash(params)
    assert params == TrajectoryParams()


@pytest.mark.parametrize("heat", [(1.0,), (0.0, 1.0, 2.0), 5.0, None, "08"])
def test_params_reject_malformed_heating_range(heat):
    with pytest.raises((ValueError, TypeError)):
        TrajectoryParams(self_heating_range_c=heat)


@pytest.mark.parametrize("field", ["reference_temp_c", "lot_temp_tolerance_c", "severity_median",
                                   "severity_log_sigma", "severity_correlation"])
@pytest.mark.parametrize("bad", [True, "1.0", None, float("inf")])
def test_params_reject_non_numeric_or_non_finite_scalars(field, bad):
    with pytest.raises((ValueError, TypeError)):
        TrajectoryParams(**{field: bad})


def test_params_are_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        TrajectoryParams().severity_correlation = 0.1


def test_params_accept_numpy_scalars():
    TrajectoryParams(severity_correlation=np.float64(0.5), reference_temp_c=np.int64(125))


# =============================================================================================
# Checkpoint input shapes
# =============================================================================================

@pytest.mark.parametrize("hours", [{0.0, 24.0}, {0.0: 1, 24.0: 2}, frozenset({0.0, 24.0}), "024", 24.0, None,
                                   np.array([[0.0, 24.0]])])
def test_rejects_unordered_or_non_sequence_checkpoints(hours):
    with pytest.raises((TypeError, ValueError)):
        generate_lot_trajectories(_baselines(3, 27), seed=27, checkpoint_hours=hours)


def test_accepts_generator_of_checkpoints():
    lot = generate_lot_trajectories(_baselines(3, 28), seed=28, checkpoint_hours=(h for h in (0.0, 24.0)))
    assert lot.checkpoint_hours == (0.0, 24.0)


def test_checkpoints_need_not_start_at_zero():
    lot = generate_lot_trajectories(_baselines(3, 29), seed=29, checkpoint_hours=(24.0, 168.0))
    for part in lot.parts:
        for name in PARAMETERS:
            assert part.values[name][0] > part.baseline[name]


# =============================================================================================
# Hand-built / malformed LotBaseline inputs
# =============================================================================================

def test_empty_lot_yields_empty_trajectories():
    lot = generate_lot_trajectories(_hand_built_lot([]), seed=1)
    assert lot.parts == ()


def test_rejects_part_missing_a_parameter():
    with pytest.raises(ValueError):
        generate_lot_trajectories(_hand_built_lot([_part(baseline={"iddq": 10.0, "leakage": 5.0})]), seed=1)


def test_rejects_part_with_unmodeled_parameter_rather_than_silently_dropping_it():
    # context.md 4.2c: the generator does not auto-scale beyond the three grounded parameters.
    baseline = {"iddq": 10.0, "leakage": 5.0, "prop_delay": 5.0, "vth": 0.4}
    with pytest.raises(ValueError):
        generate_lot_trajectories(_hand_built_lot([_part(baseline=baseline)]), seed=1)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_rejects_non_positive_or_non_finite_baseline(bad):
    baseline = {"iddq": bad, "leakage": 5.0, "prop_delay": 5.0}
    with pytest.raises(ValueError):
        generate_lot_trajectories(_hand_built_lot([_part(baseline=baseline)]), seed=1)


@pytest.mark.parametrize("bad", ["10", None, True])
def test_rejects_non_numeric_baseline(bad):
    baseline = {"iddq": bad, "leakage": 5.0, "prop_delay": 5.0}
    with pytest.raises(TypeError):
        generate_lot_trajectories(_hand_built_lot([_part(baseline=baseline)]), seed=1)


def test_rejects_duplicate_component_ids():
    with pytest.raises(ValueError):
        generate_lot_trajectories(_hand_built_lot([_part("L1-0000"), _part("L1-0000")]), seed=1)


def test_rejects_part_from_a_different_lot_or_part_number():
    with pytest.raises(ValueError):
        generate_lot_trajectories(_hand_built_lot([_part(lot_id="L2")]), seed=1)
    with pytest.raises(ValueError):
        generate_lot_trajectories(_hand_built_lot([_part(part_number="PN-2")]), seed=1)


def test_rejects_non_part_baseline_entries():
    with pytest.raises(TypeError):
        generate_lot_trajectories(_hand_built_lot([{"component_id": "L1-0000"}]), seed=1)


# =============================================================================================
# Aliasing - outputs must not share mutable state with inputs or with each other
# =============================================================================================

def test_mutating_trajectory_baseline_does_not_touch_input_lot():
    baselines = _baselines(5, 30)
    lot = generate_lot_trajectories(baselines, seed=30)
    original = dict(baselines.parts[0].baseline)
    lot.parts[0].baseline["iddq"] = -1.0
    assert baselines.parts[0].baseline == original


def test_per_part_dicts_are_not_aliased():
    lot = generate_lot_trajectories(_baselines(5, 31, ALL_DEFECTIVE), seed=31, config=ALL_DEFECTIVE)
    for field in ("baseline", "values", "drift_exponent", "drift_amplitude", "defect_severity"):
        ids = [id(getattr(p, field)) for p in lot.parts]
        assert len(set(ids)) == len(ids), field


def test_two_calls_do_not_share_objects():
    baselines = _baselines(5, 32)
    a = generate_lot_trajectories(baselines, seed=32)
    b = generate_lot_trajectories(baselines, seed=32)
    assert a == b
    assert all(pa.values is not pb.values for pa, pb in zip(a.parts, b.parts))


def test_input_lot_is_not_mutated():
    baselines = _baselines(10, 33)
    snapshot = dataclasses.replace(baselines, parts=[dataclasses.replace(p, baseline=dict(p.baseline))
                                                     for p in baselines.parts])
    generate_lot_trajectories(baselines, seed=33)
    assert baselines == snapshot


# =============================================================================================
# Final-review findings: silent fallbacks and silently-wrong hand-built inputs
# =============================================================================================

@pytest.mark.parametrize("bad", [{}, 0, False, "", []])
def test_falsy_non_config_is_rejected_not_silently_replaced_by_defaults(bad):
    with pytest.raises(TypeError):
        generate_lot_trajectories(_baselines(3, 40), seed=40, config=bad)


@pytest.mark.parametrize("bad", [{}, 0, False, "", []])
def test_falsy_non_params_is_rejected_not_silently_replaced_by_defaults(bad):
    with pytest.raises(TypeError):
        generate_lot_trajectories(_baselines(3, 41), seed=41, params=bad)


@pytest.mark.parametrize("bad", [{}, 0, False, "", []])
def test_baselines_falsy_non_config_is_rejected_not_silently_replaced_by_defaults(bad):
    with pytest.raises(TypeError):
        generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=3, seed=1, config=bad)


def test_explicit_none_still_means_defaults():
    baselines = _baselines(3, 42)
    assert generate_lot_trajectories(baselines, seed=42, config=None, params=None) == \
        generate_lot_trajectories(baselines, seed=42)


def test_one_shot_iterable_parts_are_rejected_not_silently_emptied():
    baselines = _baselines(5, 43)
    lot = dataclasses.replace(baselines, parts=(p for p in baselines.parts))
    with pytest.raises(TypeError):
        generate_lot_trajectories(lot, seed=43)


def test_tuple_parts_are_accepted():
    baselines = _baselines(5, 44)
    as_tuple = dataclasses.replace(baselines, parts=tuple(baselines.parts))
    assert generate_lot_trajectories(as_tuple, seed=44) == generate_lot_trajectories(baselines, seed=44)


@pytest.mark.parametrize("bad", ["no", 1, 0, None, 1.0])
def test_non_boolean_defect_flag_is_rejected(bad):
    with pytest.raises(TypeError):
        generate_lot_trajectories(_hand_built_lot([_part(is_defective=bad)]), seed=1)


def test_numpy_boolean_defect_flag_is_accepted_and_stored_as_python_bool():
    lot = generate_lot_trajectories(_hand_built_lot([_part(is_defective=np.bool_(True))]), seed=1)
    assert type(lot.parts[0].is_defective) is bool and lot.parts[0].is_defective is True


@pytest.mark.parametrize("bad", ["", "   ", 7, None])
def test_invalid_component_id_is_rejected(bad):
    with pytest.raises((TypeError, ValueError)):
        generate_lot_trajectories(_hand_built_lot([_part(component_id=bad)]), seed=1)


def test_defect_archetypes_registry_is_read_only():
    from generator.trajectories import DEFECT_ARCHETYPES

    with pytest.raises(TypeError):
        DEFECT_ARCHETYPES["new_type"] = DEFECT_ARCHETYPES["progressive"]
    with pytest.raises(TypeError):
        del DEFECT_ARCHETYPES["progressive"]


# =============================================================================================
# Final-review round 2: integer overflow, silently-invisible defects, lot labels, pickling
# =============================================================================================

def test_integer_too_large_for_float_checkpoint_raises_value_error():
    with pytest.raises(ValueError):
        generate_lot_trajectories(_baselines(3, 50), seed=50, checkpoint_hours=(0, 10**400))


def test_integer_too_large_for_float_param_raises_value_error():
    with pytest.raises(ValueError):
        TrajectoryParams(severity_median=10**400)


def test_integer_too_large_for_float_activation_energy_raises_value_error():
    with pytest.raises(ValueError):
        arrhenius_acceleration_factor(10**400, junction_temp_c=130.0, reference_temp_c=125.0)


def test_integer_too_large_for_float_baseline_raises_value_error():
    baseline = {"iddq": 10**400, "leakage": 5.0, "prop_delay": 5.0}
    with pytest.raises(ValueError):
        generate_lot_trajectories(_hand_built_lot([_part(baseline=baseline)]), seed=1)


def test_severity_underflowing_to_zero_raises_instead_of_mislabeling_parts():
    # A part labeled defective must actually carry a defect term; a severity that underflows to 0
    # would silently produce "defective" ground truth with a perfectly healthy trajectory.
    with pytest.raises(ValueError):
        generate_lot_trajectories(_baselines(20, 51, ALL_DEFECTIVE), seed=51, config=ALL_DEFECTIVE,
                                  params=TrajectoryParams(severity_median=1e-320))


@pytest.mark.parametrize("seed", [3, 5, 9, 10, 13, 15])  # seeds whose chamber runs below the reference
def test_acceleration_factor_underflowing_to_zero_raises_instead_of_mislabeling_parts(seed):
    # Ea of 1000 eV in a slightly cold chamber underflows AF to exactly 0: the defect never activates,
    # so the part would be labeled defective with a perfectly healthy trajectory. Must be a ValueError.
    params = TrajectoryParams(self_heating_range_c=(0.0, 0.0))
    precondition = generate_lot_trajectories(_baselines(1, seed), seed=seed, params=params)
    assert precondition.chamber_temp_c < params.reference_temp_c  # chamber depends on the seed only
    config = ScreeningConfig(defect_prevalence_range=(1.0, 1.0), activation_energy_range_eV=(1000.0, 1000.0))
    with pytest.raises(ValueError):
        generate_lot_trajectories(_baselines(5, seed, config), seed=seed, config=config,
                                  params=TrajectoryParams(self_heating_range_c=(0.0, 0.0)))


@pytest.mark.parametrize("severity_median", [1e-320, 1e-15])
def test_numerically_invisible_defect_raises_even_when_not_exactly_zero(severity_median):
    # 1e-320 is subnormal-but-nonzero, 1e-15 a normal float - both are lost when added to a baseline of
    # ~10, so the "defective" part would be indistinguishable from healthy.
    with pytest.raises(ValueError):
        generate_lot_trajectories(_baselines(20, 55, ALL_DEFECTIVE), seed=55, config=ALL_DEFECTIVE,
                                  params=TrajectoryParams(severity_median=severity_median))


def test_small_but_real_defect_is_still_allowed():
    lot = generate_lot_trajectories(_baselines(50, 56, ALL_DEFECTIVE), seed=56, config=ALL_DEFECTIVE,
                                    params=TrajectoryParams(severity_median=1e-3, severity_log_sigma=0.0))
    for p in lot.parts:
        healthy = p.baseline["iddq"] + p.drift_amplitude["iddq"] * 168.0 ** p.drift_exponent["iddq"]
        if p.defect_onset_hours < 168.0:
            assert p.values["iddq"][-1] > healthy


def test_healthy_parts_are_unaffected_by_the_defect_underflow_guard():
    # The guard is about defective parts only - an all-healthy lot with the same extreme params is fine.
    params = TrajectoryParams(severity_median=1e-320)
    lot = generate_lot_trajectories(_baselines(20, 52, ALL_HEALTHY), seed=52, config=ALL_HEALTHY, params=params)
    assert not any(p.is_defective for p in lot.parts)


def test_every_default_defective_part_has_positive_severity_and_acceleration():
    lot = generate_lot_trajectories(_baselines(2000, 53, ALL_DEFECTIVE), seed=53, config=ALL_DEFECTIVE)
    assert all(p.acceleration_factor > 0 for p in lot.parts)
    assert all(v > 0 for p in lot.parts for v in p.defect_severity.values())


@pytest.mark.parametrize("field,bad", [("lot_id", 123), ("lot_id", ""), ("lot_id", "  "), ("lot_id", None),
                                       ("part_number", None), ("part_number", ""), ("part_number", 7)])
def test_invalid_lot_labels_are_rejected_even_for_an_empty_lot(field, bad):
    lot = dataclasses.replace(_hand_built_lot([]), **{field: bad})
    with pytest.raises((TypeError, ValueError)):
        generate_lot_trajectories(lot, seed=1)


def test_trajectories_and_params_survive_pickle_and_deepcopy():
    # The P1.5 harness may fan lots out across processes - these must round-trip exactly.
    import copy
    import pickle

    lot = generate_lot_trajectories(_baselines(20, 54, ALL_DEFECTIVE), seed=54, config=ALL_DEFECTIVE)
    assert pickle.loads(pickle.dumps(lot)) == lot
    assert copy.deepcopy(lot) == lot
    params = TrajectoryParams(severity_correlation=0.3, self_heating_range_c=[1.0, 2.0])
    assert pickle.loads(pickle.dumps(params)) == params
    assert hash(pickle.loads(pickle.dumps(params))) == hash(params)
