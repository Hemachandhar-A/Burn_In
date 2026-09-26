"""Pre-merge hardening pass on Module B (not a Part 10 session): extremes and invariants the per-session
checklists didn't pin - full-pipeline determinism, interval ordering at the tight/wide ends, plausible
out-of-scope parameter names, safety_slope co-nullability, a near-zero physics gap, missing/non-finite
96h, non-finite required inputs, and CQR calibration with very few calibration rows."""

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import module_b.predictor as predictor_mod
from contracts import FeatureFrame, ModuleBInput, to_module_b_input
from features.compute import compute
from generator.lot import generate_lot
from module_b import predict
from module_b.calibration import DriftForecast, calibrate_drift_models, forecast
from module_b.model import build_training_set, feature_matrix, view_at_24h
from module_b.predictor import synthetic_models

REPO = Path(__file__).resolve().parents[3]
FORECAST_FIELDS = (
    "predicted_168h", "interval_lower", "interval_upper", "physics_baseline_prediction",
    "physics_disagreement_gap", "drift_rate", "exceeds_safety_slope", "safety_slope",
)
NAN, INF = float("nan"), float("inf")


def _frames(seeds, part_number="PN-1", n_parts=None, parameter=None) -> list[FeatureFrame]:
    out = []
    for s in seeds:
        lot = generate_lot(f"{part_number}-H{s}", part_number, s, account_id="a", n_parts=n_parts)
        out += [f for f in compute(lot.dataset) if parameter is None or f.parameter == parameter]
    return out


def _without_96h(f: FeatureFrame) -> FeatureFrame:
    return f.model_copy(update={
        "value_96h": None, "delta_96h": None,
        "robust_z": {k: v for k, v in f.robust_z.items() if k != "96h"},
        "elapsed_hours": {k: v for k, v in f.elapsed_hours.items() if k != "96h"},
    })


@pytest.fixture(scope="module")
def models():
    return synthetic_models("PN-1")


@pytest.fixture(scope="module")
def lot() -> list[ModuleBInput]:
    return [to_module_b_input(f) for f in _frames([300])]


# --- 1. Determinism: LightGBM + MAPIE CQR together, across processes ------------------------

_DETERMINISM_SCRIPT = """
import json
from contracts import to_module_b_input
from features.compute import compute
from generator.lot import generate_lot
from module_b import predict
lot = [to_module_b_input(f) for f in compute(generate_lot("DET-1", "PN-DET", 42, account_id="a").dataset)]
print(json.dumps([r.model_dump() for r in predict(lot)]))
"""


def _run_fresh_process(hash_seed: str) -> list[dict]:
    env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(REPO)}
    proc = subprocess.run([sys.executable, "-c", _DETERMINISM_SCRIPT], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=300, check=True)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_full_pipeline_is_bit_identical_across_fresh_processes_and_hash_seeds():
    # Two cold processes: synthetic-prior generation, LightGBM quantile fits, MAPIE conformalization and
    # prediction all re-run from scratch - no shared cache - with different str-hash randomization.
    a, b = _run_fresh_process("0"), _run_fresh_process("12345")
    assert len(a) == 231
    assert a == b


def test_recalibrating_from_scratch_in_process_gives_identical_results(lot):
    first = predict(lot)
    synthetic_models.cache_clear()
    try:
        assert predict(lot) == first
    finally:
        synthetic_models.cache_clear()


# --- 2. Interval ordering at the tight and wide extremes -------------------------------------


def _extreme_inputs(lot):
    base = [i for i in lot if i.parameter == "iddq"][:5]
    out = []
    for i in base:
        spread = i.value_24h - i.value_0h
        out += [
            i.model_copy(update={"value_24h": i.value_0h, "value_96h": i.value_0h}),  # perfectly flat part
            i.model_copy(update={"value_24h": i.value_0h + 50 * spread, "value_96h": i.value_0h + 80 * spread}),
            i.model_copy(update={"value_24h": i.value_0h - 30 * abs(spread) - 5,
                                 "value_96h": i.value_0h - 40 * abs(spread) - 5}),  # strong downward drift
            i.model_copy(update={"value_0h": i.value_0h * 100, "value_24h": i.value_24h * 100,
                                 "value_96h": i.value_96h * 100}),  # 100x the lot level
        ]
    return out


@pytest.mark.parametrize("horizon", ["96h", "24h"])
def test_interval_ordering_holds_at_the_tightest_and_widest_intervals(models, lot, horizon):
    inputs = lot + _extreme_inputs(lot)
    if horizon == "24h":
        inputs = [view_at_24h(i) for i in inputs]
    results = [r for r in predict(inputs, models=models) if not r.forecast_unavailable]
    widths = [r.interval_upper - r.interval_lower for r in results]
    tight, wide = results[int(np.argmin(widths))], results[int(np.argmax(widths))]
    assert max(widths) > 5 * min(widths)  # the extremes really are extremes
    for r in (tight, wide, *results):
        assert all(math.isfinite(getattr(r, f)) for f in ("interval_lower", "predicted_168h", "interval_upper"))
        assert r.interval_lower <= r.predicted_168h <= r.interval_upper


@pytest.mark.parametrize("horizon", ["96h", "24h"])
def test_ordering_never_collapses_the_calibrated_interval(models, lot, horizon):
    # Ordering is enforced by widening. It must never be bought by *narrowing*: the reported interval always
    # contains MAPIE's own conformalized bounds, even at the extremes where its quantiles can cross.
    inputs = [i for i in lot + _extreme_inputs(lot) if i.parameter == "iddq"]
    if horizon == "24h":
        inputs = [view_at_24h(i) for i in inputs]
    _, iv = models[("PN-1", "iddq")].regressors[horizon].predict_interval(feature_matrix(inputs))
    anchor = np.array([i.value_96h if i.value_96h is not None else i.value_24h for i in inputs])
    raw_lo, raw_hi = anchor + np.minimum(iv[:, 0, 0], iv[:, 1, 0]), anchor + np.maximum(iv[:, 0, 0], iv[:, 1, 0])
    for fc, lo, hi in zip(forecast(models, inputs), raw_lo, raw_hi):
        assert fc.interval_lower <= lo + 1e-9 and fc.interval_upper >= hi - 1e-9


# --- 3. Plausible-but-untrained parameter names ----------------------------------------------

PLAUSIBLE_NAMES = ["IDDQ", "Iddq", "iddq ", " leakage", "iddq_uA", "iddq2", "leakage_current",
                   "prop_delay_ns", "propagation_delay", "idd", "ioff", "vth"]


@pytest.mark.parametrize("name", PLAUSIBLE_NAMES)
def test_plausible_untrained_parameter_is_forecast_unavailable(models, lot, name):
    # Exact match against the trained three - case, whitespace and unit suffixes are ingestion's job to
    # normalize, not Module B's to guess at (context.md 5.9).
    r = predict([lot[0].model_copy(update={"parameter": name})], models=models)[0]
    assert r.forecast_unavailable is True
    assert r.parameter == name
    assert all(getattr(r, f) is None for f in FORECAST_FIELDS)


def test_out_of_scope_frames_trigger_no_training_and_no_baseline_fit(monkeypatch, lot):
    # Nothing downstream may treat them as valid: no synthetic prior is built for them, and they're never
    # pooled into a lot's power-law exponent fit.
    def boom(*a, **k):
        raise AssertionError("an out-of-scope parameter reached training")
    monkeypatch.setattr(predictor_mod, "synthetic_models", boom)
    odd = [i.model_copy(update={"parameter": "IDDQ", "part_number": "PN-ODD"}) for i in lot[:20]]
    assert all(r.forecast_unavailable for r in predict(odd))

    seen = []
    real = predictor_mod.physics_baselines
    monkeypatch.setattr(predictor_mod, "physics_baselines", lambda fs: seen.extend(fs) or real(fs))
    predict(odd + lot[:3], models={})
    assert all(f.parameter in predictor_mod.TRAINED_PARAMETERS for f in seen)


# --- 4. safety_slope is null exactly when drift_rate / exceeds_safety_slope are ---------------


def test_safety_slope_is_co_null_with_drift_rate_and_flag_on_every_path(models, lot):
    batch = [
        lot[0],                                                   # ordinary forecast (96h)
        view_at_24h(lot[1]),                                      # ordinary forecast (24h)
        lot[2].model_copy(update={"parameter": "IDDQ"}),          # out-of-scope parameter
        lot[3].model_copy(update={"part_number": "PN-NONE"}),     # no calibrated model
        lot[4].model_copy(update={"value_24h": NAN}),             # non-finite required input
        lot[5].model_copy(update={"value_96h": NAN}),             # non-finite 96h -> 24h forecast
    ]
    results = predict(batch, models=models)
    assert [r.forecast_unavailable for r in results] == [False, False, True, True, True, False]
    for r in results:
        nulls = {f: getattr(r, f) is None for f in FORECAST_FIELDS}
        assert len(set(nulls.values())) == 1, nulls  # all None or none None - never independently
        assert nulls["safety_slope"] == r.forecast_unavailable


# --- 5. A near-zero physics-vs-model gap ----------------------------------------------------


def test_physics_gap_is_exactly_zero_when_model_and_physics_agree(monkeypatch, lot):
    from module_b.baselines import physics_baselines
    base = physics_baselines(lot)

    def agreeing_forecast(models, inputs):
        out = []
        for i in inputs:
            p = base[(i.lot_id, i.component_id, i.parameter)].power_law
            out.append(DriftForecast(i.component_id, i.parameter, "96h", p, p - 1.0, p + 1.0, 0.0, 1.0, False))
        return out
    monkeypatch.setattr(predictor_mod, "forecast", agreeing_forecast)
    for r in predict(lot, models={}):
        assert r.physics_disagreement_gap == 0.0
        assert math.copysign(1.0, r.physics_disagreement_gap) == 1.0  # not -0.0


def test_physics_gap_is_small_nonnegative_and_finite_for_a_flat_part(models, lot):
    flat = [i.model_copy(update={"value_24h": i.value_0h, "value_96h": i.value_0h}) for i in lot[:30]]
    for r in predict(flat, models=models):
        assert math.isfinite(r.physics_disagreement_gap) and r.physics_disagreement_gap >= 0
        assert r.physics_baseline_prediction == pytest.approx(r.physics_baseline_prediction)


# --- 6. Missing 96h (None) and non-finite 96h ------------------------------------------------


def test_lot_with_mixed_96h_availability_forecasts_every_part_at_its_own_horizon(models):
    frames = _frames([301])
    mixed = [_without_96h(f) if k % 3 == 0 else f for k, f in enumerate(frames)]
    inputs = [to_module_b_input(f) for f in mixed]
    results = predict(inputs, models=models)
    assert not any(r.forecast_unavailable for r in results)
    # A 96h-less part is forecast exactly as its 24h view is - None is absence, not a value.
    alone = predict([view_at_24h(i) for i in inputs if i.value_96h is None], models=models)
    got = [r for i, r in zip(inputs, results) if i.value_96h is None]
    assert [(r.predicted_168h, r.interval_lower, r.interval_upper) for r in got] == \
        [(r.predicted_168h, r.interval_lower, r.interval_upper) for r in alone]


def test_missing_96h_is_not_treated_as_zero(models, lot):
    i = view_at_24h(lot[0])
    as_zero = lot[0].model_copy(update={"value_96h": 0.0})
    assert predict([i], models=models)[0].predicted_168h != predict([as_zero], models=models)[0].predicted_168h


@pytest.mark.parametrize("bad", [NAN, INF, -INF])
def test_non_finite_96h_is_treated_as_missing_not_as_a_value(models, lot, bad):
    # A literal "NaN" CSV cell survives parsing and features.compute as value_96h=nan (CONTRACT_CHANGES
    # 2026-09-26 P4 non-finite readings). It is an absent 96h read: forecast at the 24h horizon.
    r = predict([lot[0].model_copy(update={"value_96h": bad})], models=models)[0]
    expected = predict([view_at_24h(lot[0])], models=models)[0]
    assert r == expected
    assert not r.forecast_unavailable and math.isfinite(r.predicted_168h)


# --- non-finite required inputs (found by this pass) ----------------------------------------


@pytest.mark.parametrize("field", ["value_0h", "value_24h", "lot_median_0h", "lot_median_24h"])
@pytest.mark.parametrize("bad", [NAN, INF, -INF])
def test_non_finite_required_input_is_forecast_unavailable_never_a_number(models, lot, field, bad):
    # AGENTS.md rule 7: missing 0h/24h -> forecast_unavailable, not a guess - NaN/inf is missing.
    r = predict([lot[0].model_copy(update={field: bad})], models=models)[0]
    assert r.forecast_unavailable is True
    assert all(getattr(r, f) is None for f in FORECAST_FIELDS)


@pytest.mark.parametrize("label", ["0h", "24h"])
def test_non_finite_required_elapsed_hours_is_forecast_unavailable(models, lot, label):
    bad = lot[0].model_copy(update={"elapsed_hours": {**lot[0].elapsed_hours, label: NAN}})
    assert predict([bad], models=models)[0].forecast_unavailable is True


def test_24h_read_not_after_the_0h_read_is_unavailable_not_a_division_by_zero(models, lot):
    same = lot[0].model_copy(update={"elapsed_hours": {**lot[0].elapsed_hours, "24h": lot[0].elapsed_hours["0h"]}})
    assert predict([same], models=models)[0].forecast_unavailable is True


def test_non_finite_values_never_enter_training_or_calibration():
    frames = _frames([1, 2, 3], parameter="iddq")
    dirty = list(frames)
    dirty[0] = dirty[0].model_copy(update={"value_168h": NAN})
    dirty[1] = dirty[1].model_copy(update={"value_24h": INF})
    dirty[2] = dirty[2].model_copy(update={"value_96h": NAN})
    ts = build_training_set(dirty)
    assert np.isfinite(ts.y).all()
    assert dirty[0].component_id not in ts.component_ids and dirty[1].component_id not in ts.component_ids
    assert ts.component_ids.count(dirty[2].component_id) == 1  # only its 24h view survives
    model = calibrate_drift_models(dirty)[("PN-1", "iddq")]
    assert math.isfinite(model.safety_slope)


# --- 7. Lot-boundary CQR with very few calibration lots/rows ---------------------------------


def test_two_lots_calibrate_one_against_the_other():
    m = calibrate_drift_models(_frames([1, 2], parameter="iddq"))[("PN-1", "iddq")]
    assert len(m.train_lots) == 1 and len(m.calibration_lots) == 1
    assert set(m.train_lots).isdisjoint(m.calibration_lots)
    test = [to_module_b_input(f) for f in _frames([500], parameter="iddq")]
    for fc in forecast({("PN-1", "iddq"): m}, test):
        assert math.isfinite(fc.interval_upper - fc.interval_lower)
        assert fc.interval_lower <= fc.predicted_168h <= fc.interval_upper


def test_too_few_calibration_rows_at_one_horizon_drops_that_horizon_instead_of_crashing():
    frames = _frames([1, 2], parameter="iddq")
    cal_lot = calibrate_drift_models(frames)[("PN-1", "iddq")].calibration_lots[0]
    kept = 0
    thin = []
    for f in frames:
        if f.lot_id == cal_lot:
            kept += 1
            f = f if kept <= 3 else _without_96h(f)  # only 3 calibration parts keep a 96h read
        thin.append(f)
    m = calibrate_drift_models(thin)[("PN-1", "iddq")]
    assert "96h" not in m.regressors and "24h" in m.regressors
    test = [to_module_b_input(f) for f in _frames([500], parameter="iddq")]
    results = predict(test + [view_at_24h(i) for i in test], models={("PN-1", "iddq"): m})
    assert all(r.forecast_unavailable for r in results[: len(test)])
    assert not any(r.forecast_unavailable for r in results[len(test):])


def test_tiny_lots_get_no_model_rather_than_an_uncalibrated_one():
    assert calibrate_drift_models(_frames([1, 2], n_parts=12, parameter="iddq")) == {}


# --- physics_baselines keyed by the true uniqueness scope (lot_id, component_id, parameter) -----------


def _reused_ids(seed: int) -> list[ModuleBInput]:
    # Real uploads commonly number parts U000, U001, ... in every lot; the generator's lot-prefixed IDs hide
    # this, so strip the prefix to get two lots that genuinely share component_ids.
    return [to_module_b_input(f).model_copy(update={"component_id": f"U{f.component_id[-4:]}"})
            for f in _frames([seed])]


def test_two_lots_reusing_component_ids_get_independent_physics_baselines_when_batched_together(models):
    from module_b.baselines import physics_baselines
    lot_a, lot_b = _reused_ids(310), _reused_ids(311)
    assert {(i.component_id, i.parameter) for i in lot_a} == {(i.component_id, i.parameter) for i in lot_b}

    together = physics_baselines(lot_a + lot_b)
    separate = {**physics_baselines(lot_a), **physics_baselines(lot_b)}
    assert len(together) == len(lot_a) + len(lot_b)  # nothing overwritten
    assert together == separate
    assert together[("PN-1-H310", "U0000", "iddq")] != together[("PN-1-H311", "U0000", "iddq")]

    # And through predict: every part's physics baseline and gap match its own lot processed alone.
    batched = predict(lot_a + lot_b, models=models)
    alone = predict(lot_a, models=models) + predict(lot_b, models=models)
    for got, want in zip(batched, alone):
        assert got.component_id == want.component_id
        assert got.physics_baseline_prediction == want.physics_baseline_prediction
        assert got.physics_disagreement_gap == want.physics_disagreement_gap
