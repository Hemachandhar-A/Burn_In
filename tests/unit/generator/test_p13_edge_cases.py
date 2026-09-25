"""Edge cases for P1.3 (E1 steps 7-9) found on review: measurement robustness on hand-built or
extreme inputs, clean quantized output, picklability for a parallel harness, family provenance,
per-lot seeding, and text inputs that would break a downstream JSON/CSV consumer."""
import copy
import dataclasses
import json
import math
import os
import pickle
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from contracts import LotDataset
from generator.families import FAMILIES
from generator.lot import generate_lot
from generator.measurement import MeasurementParams, measure_lot
from generator.parameters import PARAMETERS

REPO_ROOT = Path(__file__).resolve().parents[3]


def _per_param(value):
    return {name: value for name in PARAMETERS}


def _lot(**kwargs):
    kwargs.setdefault("lot_id", "L1")
    kwargs.setdefault("part_number", "PN-1")
    kwargs.setdefault("seed", 42)
    kwargs.setdefault("account_id", "acct-test")
    return generate_lot(**kwargs)


def _traj(n_parts=3, **kwargs):
    return _lot(n_parts=n_parts, **kwargs).ground_truth.trajectories


def _decimals(step):
    from decimal import Decimal
    return max(0, -Decimal(repr(step)).normalize().as_tuple().exponent)


# --- measure_lot on hand-built / malformed trajectories -------------------------------

def test_duplicate_component_ids_rejected_not_silently_collapsed():
    traj = _traj()
    dup = dataclasses.replace(traj, parts=(traj.parts[0], traj.parts[0]))
    with pytest.raises(ValueError, match="duplicate"):
        measure_lot(dup, seed=1)


def test_series_length_must_match_checkpoint_count():
    traj = _traj()
    with pytest.raises(ValueError):
        measure_lot(dataclasses.replace(traj, checkpoint_hours=(0.0, 24.0)), seed=1)
    with pytest.raises(ValueError):
        measure_lot(dataclasses.replace(traj, checkpoint_hours=(0.0, 24.0, 96.0, 168.0, 300.0)), seed=1)


def test_one_shot_iterable_parts_rejected():
    traj = _traj()
    with pytest.raises(TypeError):
        measure_lot(dataclasses.replace(traj, parts=(p for p in traj.parts)), seed=1)


def test_non_part_entries_rejected():
    traj = _traj()
    with pytest.raises(TypeError):
        measure_lot(dataclasses.replace(traj, parts=("not a part",)), seed=1)


def _with_values(part, name, series):
    return dataclasses.replace(part, values={**part.values, name: series})


@pytest.mark.parametrize("bad", [math.nan, math.inf, 0.0, -1.0])
def test_non_finite_or_non_positive_true_values_rejected_cleanly(bad):
    traj = _traj()
    part = _with_values(traj.parts[0], "iddq", (bad,) * 4)
    with pytest.raises(ValueError, match="iddq"):
        measure_lot(dataclasses.replace(traj, parts=(part,)), seed=1)


def test_missing_or_extra_parameter_rejected():
    traj = _traj()
    part = traj.parts[0]
    missing = dataclasses.replace(part, values={k: v for k, v in part.values.items() if k != "leakage"})
    extra = _with_values(part, "vth", (1.0,) * 4)
    for p in (missing, extra):
        with pytest.raises(ValueError):
            measure_lot(dataclasses.replace(traj, parts=(p,)), seed=1)


def test_invalid_checkpoint_hours_on_hand_built_trajectories_rejected():
    traj = _traj()
    with pytest.raises(ValueError):
        measure_lot(dataclasses.replace(traj, checkpoint_hours=(0.0, 96.0, 24.0, 168.0)), seed=1)


def test_empty_component_id_rejected():
    traj = _traj()
    part = dataclasses.replace(traj.parts[0], component_id="  ")
    with pytest.raises((TypeError, ValueError)):
        measure_lot(dataclasses.replace(traj, parts=(part,)), seed=1)


def test_measure_lot_does_not_mutate_its_input():
    traj = _traj()
    before = copy.deepcopy(traj)
    measure_lot(traj, seed=1)
    assert traj == before


# --- overflow / extreme knobs surface as one clean ValueError --------------------------

def test_huge_tester_offset_is_a_clean_error_not_overflow():
    params = MeasurementParams(tester_offset_sigma={**_per_param(0.1), "iddq": 1e308})
    with pytest.raises(ValueError, match="finite"):
        measure_lot(_traj(), seed=1, params=params)


def test_finite_but_swamping_offset_rejected_not_silently_garbage():
    # 1e15 offset doesn't overflow, but at 0.01 resolution the true ~12 uA is lost in float rounding.
    params = MeasurementParams(tester_offset_sigma={**_per_param(0.1), "iddq": 1e15})
    with pytest.raises(ValueError, match="precision"):
        measure_lot(_traj(), seed=1, params=params)


def test_moderately_large_offset_still_corrected_exactly():
    params = MeasurementParams(noise_frac=_per_param(0.0), tester_offset_sigma=_per_param(1e4))
    traj = _traj()
    measured = measure_lot(traj, seed=1, params=params)
    for part in traj.parts:
        for name in PARAMETERS:
            step = params.resolution[name]
            for true, got in zip(part.values[name], measured.values[part.component_id][name]):
                assert abs(got - true) <= step / 2 + 1e-9


def test_subnormal_resolution_is_a_clean_error_not_overflow():
    params = MeasurementParams(resolution={**_per_param(0.01), "iddq": 5e-324})
    with pytest.raises(ValueError, match="resolution"):
        measure_lot(_traj(), seed=1, params=params)


def test_huge_true_value_overflowing_under_noise_is_a_clean_error():
    traj = _traj()
    part = _with_values(traj.parts[0], "iddq", (1.7e308,) * 4)
    params = MeasurementParams(noise_frac=_per_param(0.5))
    with pytest.raises(ValueError):
        measure_lot(dataclasses.replace(traj, parts=(part,)), seed=1, params=params)


# --- quantized output is the clean grid value -----------------------------------------

@pytest.mark.parametrize("step", [0.01, 0.003, 0.001, 0.5, 1e-6])
def test_quantized_readings_are_clean_decimals_at_any_magnitude(step):
    # 1e6-scale values are where n * step picks up float error (1234567.8900000001).
    traj = _traj(n_parts=20)
    scaled = dataclasses.replace(traj, parts=tuple(
        dataclasses.replace(p, values={k: tuple(v * 1e5 for v in s) for k, s in p.values.items()})
        for p in traj.parts
    ))
    params = MeasurementParams(resolution=_per_param(step))
    measured = measure_lot(scaled, seed=1, params=params)
    digits = _decimals(step)
    for series_by_param in measured.values.values():
        for series in series_by_param.values():
            for v in series:
                assert round(v, digits) == v
                # relative: at v/step ~ 1e12 the division itself carries ~1e-4 units of float error
                assert abs(v / step - round(v / step)) <= 1e-12 * max(1.0, abs(v / step))


def test_readings_json_has_no_float_noise_digits():
    payload = json.loads(_lot().dataset.model_dump_json())
    for r in payload["readings"]:
        step = MeasurementParams().resolution[r["parameter"]]
        assert len(repr(r["value"]).split(".")[-1]) <= _decimals(step)


# --- heavy-tailed noise never produces a non-positive reading ---------------------------

def test_noise_family_readings_always_positive_across_many_lots():
    for seed in range(15):
        lot = _lot(seed=seed, family="different_noise_regime")
        assert all(r.value > 0 and math.isfinite(r.value) for r in lot.dataset.readings)


def test_max_noise_frac_readings_still_positive():
    params = MeasurementParams(noise_frac=_per_param(0.5))
    measured = measure_lot(_traj(n_parts=200), seed=3, params=params)
    assert all(v > 0 for s in measured.values.values() for series in s.values() for v in series)


# --- picklability (a parallel harness ships families/params/lots between processes) ------

def test_measurement_params_pickle_and_deepcopy_round_trip():
    params = MeasurementParams(noise_tail_df=5.0, n_reference_parts=3)
    for clone in (pickle.loads(pickle.dumps(params)), copy.deepcopy(params)):
        assert clone == params and hash(clone) == hash(params)
        with pytest.raises(TypeError):
            clone.noise_frac["iddq"] = 0.3  # still read-only after the round trip


@pytest.mark.parametrize("name", list(FAMILIES))
def test_every_family_pickles_and_deepcopies(name):
    family = FAMILIES[name]
    assert pickle.loads(pickle.dumps(family)) == family
    assert copy.deepcopy(family) == family


def test_generated_lot_pickles():
    lot = _lot(n_parts=5)
    assert pickle.loads(pickle.dumps(lot)) == lot


def test_dataclasses_replace_on_measurement_params():
    params = dataclasses.replace(MeasurementParams(), n_reference_parts=9)
    assert params.n_reference_parts == 9
    assert params.noise_frac == MeasurementParams().noise_frac


def test_measurement_params_equality_ignores_key_order():
    a = MeasurementParams(noise_frac={"iddq": 0.01, "leakage": 0.02, "prop_delay": 0.003})
    b = MeasurementParams(noise_frac={"prop_delay": 0.003, "leakage": 0.02, "iddq": 0.01})
    assert a == b and hash(a) == hash(b)


# --- family provenance -----------------------------------------------------------------

def test_custom_family_reusing_a_registered_name_with_different_settings_rejected():
    impostor = dataclasses.replace(FAMILIES["higher_defect_prevalence"], name="baseline")
    with pytest.raises(ValueError, match="baseline"):
        _lot(family=impostor)


def test_identical_copy_of_registered_family_accepted():
    assert _lot(family=copy.deepcopy(FAMILIES["baseline"])).ground_truth.family == "baseline"


def test_custom_family_with_new_name_recorded():
    custom = dataclasses.replace(FAMILIES["baseline"], name="my_custom", description="test family")
    assert _lot(family=custom).ground_truth.family == "my_custom"


@pytest.mark.parametrize("field,value", [
    ("name", 123),
    ("name", ""),
    ("description", None),
    ("description", "  "),
    ("config", {}),
    ("trajectory_params", None),
    ("measurement_params", {}),
    ("die_correlation", 1.5),
    ("die_correlation", math.nan),
    ("die_correlation", True),
])
def test_invalid_family_fields_rejected_at_construction(field, value):
    with pytest.raises((TypeError, ValueError)):
        dataclasses.replace(FAMILIES["baseline"], **{field: value})


def test_generate_lot_rejects_none_family():
    with pytest.raises(TypeError):
        _lot(family=None)


# --- per-lot seeding ----------------------------------------------------------------------

def _values(lot):
    return [r.value for r in lot.dataset.readings]


def test_same_seed_different_lot_id_gives_different_data():
    # A multi-lot run using one seed must not silently produce copies of the same lot.
    assert _values(_lot(lot_id="A")) != _values(_lot(lot_id="B"))


def test_same_seed_different_part_number_gives_different_data():
    assert _values(_lot(part_number="PN-A")) != _values(_lot(part_number="PN-B"))


def test_per_lot_seeding_is_still_deterministic_and_records_the_caller_seed():
    a, b = _lot(lot_id="A", seed=9), _lot(lot_id="A", seed=9)
    assert a == b
    assert a.ground_truth.seed == 9


def test_families_share_the_underlying_lot_for_the_same_inputs():
    # Common random numbers across families: same lot/seed, only the family's knob changes the data.
    base = _lot(family="baseline").ground_truth.baselines
    prevalent = _lot(family="higher_defect_prevalence").ground_truth.baselines
    assert [p.baseline for p in base.parts] == [p.baseline for p in prevalent.parts]
    defective_base = {p.component_id for p in base.parts if p.is_defective}
    defective_prev = {p.component_id for p in prevalent.parts if p.is_defective}
    assert defective_base <= defective_prev


def test_determinism_across_processes_with_different_hash_seeds():
    code = (
        "import hashlib;from generator.lot import generate_lot;"
        "g=generate_lot('L1','PN-1',5,account_id='a',family='altered_correlation',checkpoint_jitter_hours=1.0);"
        "print(hashlib.sha256(g.dataset.model_dump_json().encode()).hexdigest())"
    )
    digests = set()
    for hash_seed in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        out = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env,
                             capture_output=True, text=True, check=True)
        digests.add(out.stdout.strip())
    assert len(digests) == 1


# --- text inputs that would break downstream serialization -----------------------------

@pytest.mark.parametrize("field", ["lot_id", "part_number", "account_id", "manufacturer", "date_code"])
@pytest.mark.parametrize("bad", ["bad\ud800id", "line\nbreak", "tab\tsep", "nul\x00"])
def test_unencodable_or_control_character_text_rejected(field, bad):
    with pytest.raises(ValueError):
        _lot(**{field: bad})


@pytest.mark.parametrize("field", ["account_id", "manufacturer", "date_code"])
def test_non_string_text_rejected(field):
    with pytest.raises(TypeError):
        _lot(**{field: 2601})


def test_unicode_text_accepted_and_serializable():
    lot = _lot(lot_id="LOT-é-1", manufacturer="Fábrica")
    assert LotDataset.model_validate_json(lot.dataset.model_dump_json()) == lot.dataset


# --- schedule inputs ---------------------------------------------------------------------

def test_integer_checkpoint_hours_become_floats():
    lot = _lot(checkpoint_hours=(0, 24, 96, 168))
    assert lot.dataset.status == "COMPLETE"
    assert all(type(r.checkpoint_hour) is float for r in lot.dataset.readings)
    assert lot.ground_truth.nominal_checkpoint_hours == (0.0, 24.0, 96.0, 168.0)


def test_numpy_and_iterator_checkpoint_hours_accepted():
    ref = _lot().dataset
    assert _lot(checkpoint_hours=np.array([0.0, 24.0, 96.0, 168.0])).dataset == ref
    assert _lot(checkpoint_hours=iter([0.0, 24.0, 96.0, 168.0])).dataset == ref


def test_duplicate_checkpoint_hours_rejected():
    with pytest.raises(ValueError):
        _lot(checkpoint_hours=(0.0, 24.0, 24.0, 168.0))


def test_single_zero_hour_checkpoint_lot():
    lot = _lot(checkpoint_hours=(0.0,), checkpoint_jitter_hours=5.0)
    assert lot.dataset.status == "IN_PROGRESS"
    assert {r.checkpoint_hour for r in lot.dataset.readings} == {0.0}


def test_single_late_checkpoint_jitter_bounded_by_its_own_hour():
    with pytest.raises(ValueError):
        _lot(checkpoint_hours=(24.0,), checkpoint_jitter_hours=30.0)
    lot = _lot(checkpoint_hours=(168.0,), checkpoint_jitter_hours=10.0)
    assert lot.dataset.status == "COMPLETE"


@pytest.mark.parametrize("jitter", [None, "1.0", np.nan])
def test_jitter_wrong_type_or_nan_rejected(jitter):
    with pytest.raises((TypeError, ValueError)):
        _lot(checkpoint_jitter_hours=jitter)


def test_numpy_seed_and_n_parts_normalized():
    lot = _lot(seed=np.int64(42), n_parts=np.int32(5))
    assert type(lot.ground_truth.seed) is int
    assert lot == _lot(seed=42, n_parts=5)


def test_single_part_lot():
    lot = _lot(n_parts=1)
    assert len({r.component_id for r in lot.dataset.readings}) == 1


def test_very_large_seed_supported_and_deterministic():
    big = 2**100
    assert _lot(seed=big, n_parts=3) == _lot(seed=big, n_parts=3)
    assert _values(_lot(seed=big, n_parts=3)) != _values(_lot(seed=big + 1, n_parts=3))


@pytest.mark.parametrize("bad_seed", [-1, 1.0, True, None, "7"])
def test_invalid_seed_rejected_before_any_generation(bad_seed):
    with pytest.raises((TypeError, ValueError)):
        _lot(seed=bad_seed)


# --- second review pass -------------------------------------------------------------------

def test_measured_checkpoint_hours_normalized_for_hand_built_trajectories():
    # A hand-built lot with integer/list hours must come back as the validated float tuple, not echoed raw.
    traj = _traj()
    measured = measure_lot(dataclasses.replace(traj, checkpoint_hours=[0, 24, 96, 168]), seed=1)
    assert measured.checkpoint_hours == (0.0, 24.0, 96.0, 168.0)
    assert all(type(h) is float for h in measured.checkpoint_hours)


class _TunedParams(MeasurementParams):  # module level so pickle can find it by name
    pass


def test_measurement_params_subclass_survives_pickle():
    params = _TunedParams(n_reference_parts=4)
    for clone in (pickle.loads(pickle.dumps(params)), copy.deepcopy(params)):
        assert type(clone) is _TunedParams and clone == params


@pytest.mark.parametrize("field", ["lot_id", "part_number", "account_id", "manufacturer", "date_code"])
@pytest.mark.parametrize("padded", [" L1", "L1 ", " L1"])
def test_whitespace_padded_text_rejected(field, padded):
    # " L1" and "L1" would be different lots here but the same lot to any consumer that strips whitespace.
    with pytest.raises(ValueError):
        _lot(**{field: padded})


def test_inner_whitespace_allowed():
    assert _lot(manufacturer="ACME Sim Labs").dataset.readings[0].manufacturer == "ACME Sim Labs"


def test_ground_truth_records_the_full_family_spec_for_custom_families():
    # Two different custom families can share a name across runs; the sidecar must still say exactly what
    # generated the lot, and be enough to regenerate it.
    custom = dataclasses.replace(FAMILIES["baseline"], name="custom", description="custom test family",
                                 die_correlation=0.3)
    lot = _lot(family=custom)
    assert lot.ground_truth.family_spec == custom
    gt = lot.ground_truth
    again = generate_lot(gt.baselines.lot_id, gt.baselines.part_number, gt.seed, account_id="acct-test",
                         family=gt.family_spec, checkpoint_hours=gt.nominal_checkpoint_hours)
    assert again.dataset == lot.dataset


def test_ground_truth_family_spec_matches_registry_for_named_families():
    for name, family in FAMILIES.items():
        assert _lot(family=name, n_parts=2).ground_truth.family_spec == family


def test_family_descriptions_state_their_actual_settings():
    wide = FAMILIES["wider_drift_exponent"]
    lo, hi = wide.config.power_law_exponent_range
    assert f"[{lo:.2f}, {hi:.2f}]" in wide.description
    prev = FAMILIES["higher_defect_prevalence"]
    assert f"{prev.config.defect_prevalence_range[0]:.0%}".rstrip("%") in prev.description
    noise = FAMILIES["different_noise_regime"].measurement_params
    assert f"df={noise.noise_tail_df:g}" in FAMILIES["different_noise_regime"].description
    assert f"only {noise.n_reference_parts} reference parts" in FAMILIES["different_noise_regime"].description
    corr = FAMILIES["altered_correlation"]
    assert f"{corr.die_correlation:g})" in corr.description
    assert f"({corr.trajectory_params.severity_correlation:g})" in corr.description
