"""Edge cases for E1 steps 1-3 beyond the happy-path coverage in test_baselines.py:
input validation, config-boundary values, determinism robustness against global state,
and data-structure integrity (aliasing, immutability).
"""
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from contracts import ScreeningConfig
from generator.baselines import generate_lot_baselines
from generator.parameters import PARAMETERS

# --- n_parts validation -----------------------------------------------------

def test_rejects_zero_n_parts():
    with pytest.raises(ValueError):
        generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=0, seed=1)


def test_rejects_negative_n_parts():
    with pytest.raises(ValueError):
        generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=-5, seed=1)


def test_rejects_non_integer_n_parts():
    with pytest.raises(TypeError):
        generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=77.5, seed=1)


def test_rejects_string_n_parts():
    with pytest.raises(TypeError):
        generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts="77", seed=1)


def test_rejects_bool_n_parts():
    # bool is a subclass of int in Python - True would silently mean "generate 1 part".
    with pytest.raises(TypeError):
        generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=True, seed=1)


def test_accepts_n_parts_equal_one():
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=1, seed=1)
    assert len(lot.parts) == 1


def test_accepts_large_n_parts():
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=5000, seed=1)
    assert len(lot.parts) == 5000
    assert len({p.component_id for p in lot.parts}) == 5000


# --- seed validation ---------------------------------------------------------

def test_rejects_negative_seed():
    with pytest.raises(ValueError):
        generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=10, seed=-1)


def test_rejects_non_integer_seed():
    with pytest.raises(TypeError):
        generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=10, seed=1.5)


def test_rejects_bool_seed():
    with pytest.raises(TypeError):
        generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=10, seed=True)


def test_accepts_seed_zero():
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=10, seed=0)
    assert len(lot.parts) == 10


def test_accepts_very_large_seed():
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=10, seed=2**62)
    assert len(lot.parts) == 10


# --- lot_id / part_number validation -----------------------------------------

def test_rejects_empty_lot_id():
    with pytest.raises(ValueError):
        generate_lot_baselines(lot_id="", part_number="PN-1", n_parts=10, seed=1)


def test_rejects_whitespace_only_lot_id():
    with pytest.raises(ValueError):
        generate_lot_baselines(lot_id="   ", part_number="PN-1", n_parts=10, seed=1)


def test_rejects_empty_part_number():
    with pytest.raises(ValueError):
        generate_lot_baselines(lot_id="L1", part_number="", n_parts=10, seed=1)


def test_rejects_whitespace_only_part_number():
    with pytest.raises(ValueError):
        generate_lot_baselines(lot_id="L1", part_number="  ", n_parts=10, seed=1)


# --- config.defect_prevalence_range validation -------------------------------

def test_rejects_inverted_prevalence_range():
    config = ScreeningConfig(defect_prevalence_range=(0.5, 0.1))
    with pytest.raises(ValueError):
        generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=10, seed=1, config=config)


def test_rejects_negative_prevalence_range():
    config = ScreeningConfig(defect_prevalence_range=(-0.1, 0.5))
    with pytest.raises(ValueError):
        generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=10, seed=1, config=config)


def test_rejects_prevalence_range_above_one():
    config = ScreeningConfig(defect_prevalence_range=(0.5, 1.5))
    with pytest.raises(ValueError):
        generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=10, seed=1, config=config)


def test_accepts_fixed_prevalence_lo_equals_hi():
    config = ScreeningConfig(defect_prevalence_range=(0.05, 0.05))
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=50, seed=1, config=config)
    assert lot.defect_prevalence == 0.05


def test_accepts_zero_prevalence_all_healthy():
    config = ScreeningConfig(defect_prevalence_range=(0.0, 0.0))
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=200, seed=1, config=config)
    assert lot.defect_prevalence == 0.0
    assert all(not p.is_defective for p in lot.parts)


def test_accepts_near_certain_prevalence_mostly_defective():
    config = ScreeningConfig(defect_prevalence_range=(0.95, 1.0))
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=200, seed=1, config=config)
    defective_count = sum(p.is_defective for p in lot.parts)
    assert defective_count > 150  # overwhelmingly defective, not the hardcoded "healthy majority" case


# --- determinism robustness against global numpy state -----------------------

def test_determinism_unaffected_by_polluted_global_numpy_state():
    # AGENTS.md rule 9: same input, same seed, same output - must not depend on hidden
    # global RNG state that some other, unrelated code in the same process may have touched.
    baseline = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=30, seed=99)

    np.random.seed(12345)
    for _ in range(50):
        np.random.random()

    polluted = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=30, seed=99)

    assert baseline.lot_center == polluted.lot_center
    assert baseline.lot_die_sigma == polluted.lot_die_sigma
    assert baseline.defect_prevalence == polluted.defect_prevalence
    assert [p.baseline for p in baseline.parts] == [p.baseline for p in polluted.parts]


def test_same_seed_different_lot_labels_share_identical_statistics():
    # lot_id/part_number are labels only - they must not feed the RNG. Documenting this
    # explicitly so it isn't mistaken for a bug later.
    lot_a = generate_lot_baselines(lot_id="LOT-A", part_number="PN-1", n_parts=20, seed=5)
    lot_b = generate_lot_baselines(lot_id="LOT-B", part_number="PN-2", n_parts=20, seed=5)

    assert lot_a.lot_center == lot_b.lot_center
    assert lot_a.defect_prevalence == lot_b.defect_prevalence
    assert [p.is_defective for p in lot_a.parts] == [p.is_defective for p in lot_b.parts]
    # only the labels differ
    assert lot_a.parts[0].component_id != lot_b.parts[0].component_id


# --- data-structure integrity: aliasing and immutability ---------------------

def test_part_baseline_dicts_are_not_aliased():
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=5, seed=1)
    for i in range(len(lot.parts)):
        for j in range(i + 1, len(lot.parts)):
            assert lot.parts[i].baseline is not lot.parts[j].baseline


def test_two_calls_do_not_share_dict_objects():
    lot_a = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=5, seed=1)
    lot_b = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=5, seed=1)

    assert lot_a.lot_center is not lot_b.lot_center
    assert lot_a.lot_center == lot_b.lot_center  # equal values, distinct objects
    for pa, pb in zip(lot_a.parts, lot_b.parts):
        assert pa.baseline is not pb.baseline


def test_lot_baseline_is_immutable():
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=5, seed=1)
    with pytest.raises(FrozenInstanceError):
        lot.lot_id = "L2"


def test_part_baseline_is_immutable():
    lot = generate_lot_baselines(lot_id="L1", part_number="PN-1", n_parts=5, seed=1)
    with pytest.raises(FrozenInstanceError):
        lot.parts[0].is_defective = True


# --- PARAMETERS spec sanity (regression guard on physical grounding) --------

def test_parameters_cover_the_three_named_burn_in_measurements():
    assert set(PARAMETERS.keys()) == {"iddq", "leakage", "prop_delay"}


def test_parameter_specs_have_positive_finite_sigmas():
    for name, spec in PARAMETERS.items():
        assert np.isfinite(spec.lot_center_mu), name
        assert spec.lot_center_sigma > 0, name
        assert spec.die_sigma_base > 0, name
        assert spec.die_sigma_jitter > 0, name
