"""P4.1 / E3 step 1: the three physics baselines any deployed Module B model must beat."""

import math

import numpy as np
import pytest

from contracts import ModuleBInput, to_module_b_input
from features.compute import compute
from generator.lot import generate_lot
from module_b.baselines import (
    DEFAULT_POWER_LAW_EXPONENT,
    HEALTHY_ROBUST_Z_MAX,
    fit_lot_exponent,
    linear,
    persistence,
    physics_baselines,
    power_law,
)


def _input(
    component_id="C1",
    v0=10.0,
    v24=11.0,
    v96=None,
    t24=24.0,
    t96=96.0,
    z=0.0,
    lot_id="L1",
    parameter="iddq",
    t0=0.0,
) -> ModuleBInput:
    elapsed = {"0h": t0, "24h": t24}
    robust_z = {"0h": z, "24h": z}
    if v96 is not None:
        elapsed["96h"] = t96
        robust_z["96h"] = z
    return ModuleBInput(
        component_id=component_id,
        lot_id=lot_id,
        part_number="PN-1",
        parameter=parameter,
        value_0h=v0,
        value_24h=v24,
        value_96h=v96,
        delta_24h=v24 - v0,
        delta_96h=None if v96 is None else v96 - v0,
        lot_median_0h=v0,
        lot_median_24h=v24,
        robust_z=robust_z,
        lot_size=77,
        used_pooled_fallback=False,
        elapsed_hours=elapsed,
    )


def _power_law_part(cid, v0, amp, n, t24=24.0, t96=96.0, with_96h=True, z=0.0, **kw):
    return _input(cid, v0=v0, v24=v0 + amp * t24**n, v96=v0 + amp * t96**n if with_96h else None,
                  t24=t24, t96=t96, z=z, **kw)


# --- persistence ----------------------------------------------------------------------------


def test_persistence_is_the_24h_reading_when_no_96h():
    assert persistence(_input(v0=10.0, v24=11.0)) == 11.0


def test_persistence_carries_the_latest_reading_forward_when_96h_exists():
    assert persistence(_input(v0=10.0, v24=11.0, v96=12.5)) == 12.5


# --- linear ---------------------------------------------------------------------------------


def test_linear_is_exact_on_a_straight_line_trajectory():
    # v(t) = 10 + 0.1 t  ->  v(168) = 26.8
    assert linear(_input(v0=10.0, v24=12.4)) == pytest.approx(26.8)
    assert linear(_input(v0=10.0, v24=12.4, v96=19.6)) == pytest.approx(26.8)


def test_linear_uses_actual_elapsed_hours_not_nominal():
    # A jittered 20h read on the same line: slope must use 20h, not an assumed 24h.
    assert linear(_input(v0=10.0, v24=12.0, t24=20.0)) == pytest.approx(26.8)


def test_linear_handles_decreasing_drift():
    assert linear(_input(v0=10.0, v24=9.0)) == pytest.approx(3.0)


# --- power law ------------------------------------------------------------------------------


def test_power_law_is_exact_given_the_true_exponent():
    part = _power_law_part("C1", v0=5.0, amp=0.4, n=0.25, with_96h=False)
    assert power_law(part, 0.25) == pytest.approx(5.0 + 0.4 * 168**0.25)


def test_power_law_with_exponent_one_equals_linear():
    part = _input(v0=10.0, v24=11.3, v96=13.1)
    assert power_law(part, 1.0) == pytest.approx(linear(part))


def test_power_law_undershoots_linear_for_sublinear_drift():
    # context.md 1.4: a straight line from 0h->24h overshoots healthy NBTI drift by ~4-5x.
    part = _power_law_part("C1", v0=5.0, amp=0.4, n=0.25, with_96h=False)
    truth = 5.0 + 0.4 * 168**0.25
    assert abs(power_law(part, 0.25) - truth) < abs(linear(part) - truth)
    assert (linear(part) - 5.0) / (truth - 5.0) > 4.0


def test_power_law_zero_drift_part_predicts_its_own_value():
    part = _input(v0=10.0, v24=10.0, v96=10.0)
    assert power_law(part, 0.25) == pytest.approx(10.0)


# --- exponent fit from the lot's healthy parts ----------------------------------------------


def test_exponent_is_recovered_from_a_lot_following_a_power_law():
    lot = [_power_law_part(f"C{i}", v0=10.0 + i * 0.01, amp=0.3 + 0.01 * i, n=0.22) for i in range(40)]
    assert fit_lot_exponent(lot) == pytest.approx(0.22, abs=1e-9)


def test_exponent_fit_uses_actual_elapsed_hours():
    lot = [_power_law_part(f"C{i}", v0=10.0, amp=0.5, n=0.3, t24=23.6, t96=97.1) for i in range(40)]
    assert fit_lot_exponent(lot) == pytest.approx(0.3, rel=1e-3)


def test_outlier_parts_do_not_move_the_fitted_exponent():
    healthy = [_power_law_part(f"C{i}", v0=10.0, amp=0.3, n=0.2) for i in range(40)]
    # Ten wildly superlinear outliers (well past the healthy robust-z cutoff).
    outliers = [
        _power_law_part(f"X{i}", v0=10.0, amp=0.001, n=2.0, z=HEALTHY_ROBUST_Z_MAX + 5.0) for i in range(10)
    ]
    assert fit_lot_exponent(healthy + outliers) == pytest.approx(0.2, abs=1e-9)


def test_exponent_falls_back_to_the_disclosed_default_without_96h():
    lot = [_power_law_part(f"C{i}", v0=10.0, amp=0.3, n=0.2, with_96h=False) for i in range(40)]
    assert fit_lot_exponent(lot) == DEFAULT_POWER_LAW_EXPONENT


def test_exponent_falls_back_when_drift_has_no_consistent_direction():
    # Median 0h->24h drift up, median 0h->96h drift down: no power law fits - never a NaN or a log error.
    lot = [_input(f"C{i}", v0=10.0, v24=11.0, v96=9.0) for i in range(40)]
    assert fit_lot_exponent(lot) == DEFAULT_POWER_LAW_EXPONENT


def test_exponent_falls_back_on_zero_median_drift():
    lot = [_input(f"C{i}", v0=10.0, v24=10.0, v96=10.0) for i in range(40)]
    assert fit_lot_exponent(lot) == DEFAULT_POWER_LAW_EXPONENT


def test_exponent_is_clipped_to_the_physical_range():
    # Superlinear lot (n=2) - clipped to linear, never extrapolated faster than a straight line.
    lot = [_power_law_part(f"C{i}", v0=10.0, amp=0.001, n=2.0) for i in range(40)]
    assert fit_lot_exponent(lot) == 1.0


def test_exponent_fit_rejects_mixed_lots_or_parameters():
    a = _power_law_part("C1", v0=10.0, amp=0.3, n=0.2)
    with pytest.raises(ValueError):
        fit_lot_exponent([a, _power_law_part("C2", 10.0, 0.3, 0.2, lot_id="L2")])
    with pytest.raises(ValueError):
        fit_lot_exponent([a, _power_law_part("C2", 10.0, 0.3, 0.2, parameter="leakage")])


def test_exponent_fit_on_empty_input_returns_default():
    assert fit_lot_exponent([]) == DEFAULT_POWER_LAW_EXPONENT


# --- physics_baselines: all three, per (lot, parameter) ----------------------------------


def test_physics_baselines_fits_one_exponent_per_lot_and_parameter():
    iddq = [_power_law_part(f"C{i}", 10.0, 0.3, 0.2, parameter="iddq") for i in range(30)]
    leak = [_power_law_part(f"C{i}", 10.0, 0.3, 0.3, parameter="leakage") for i in range(30)]
    out = physics_baselines(iddq + leak)
    assert len(out) == 60
    assert out[("L1", "C0", "iddq")].power_law_exponent == pytest.approx(0.2)
    assert out[("L1", "C0", "leakage")].power_law_exponent == pytest.approx(0.3)
    b = out[("L1", "C0", "iddq")]
    assert b.persistence == persistence(iddq[0])
    assert b.linear == linear(iddq[0])
    assert b.power_law == pytest.approx(power_law(iddq[0], 0.2))


def test_physics_baselines_is_deterministic_and_order_independent():
    lot = [_power_law_part(f"C{i}", 10.0 + i, 0.3 + 0.02 * i, 0.25) for i in range(30)]
    assert physics_baselines(lot) == physics_baselines(list(reversed(lot)))


def test_power_law_baseline_beats_linear_on_generated_healthy_parts():
    # Physics check on P1's generator (context.md 1.4): from 0h/24h only, a sublinear power law
    # beats a straight line at 168h.
    maes = {"linear": [], "power_law": []}
    for seed in range(3):
        g = generate_lot(f"L{seed}", "PN-1", seed, account_id="a")
        healthy = {p.component_id for p in g.ground_truth.baselines.parts if not p.is_defective}
        frames = [f for f in compute(g.dataset) if f.component_id in healthy]
        inputs = [to_module_b_input(f).model_copy(update={"value_96h": None, "delta_96h": None}) for f in frames]
        preds = physics_baselines(inputs)
        for f in frames:
            b = preds[(f.lot_id, f.component_id, f.parameter)]
            scale = abs(f.lot_median_0h) or 1.0
            maes["linear"].append(abs(b.linear - f.value_168h) / scale)
            maes["power_law"].append(abs(b.power_law - f.value_168h) / scale)
    assert np.mean(maes["power_law"]) < np.mean(maes["linear"])
    assert all(math.isfinite(v) for v in maes["power_law"])
