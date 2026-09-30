"""Block 4c Part 2 (profiling: CONTRACT_CHANGES.md 2026-09-30): explain.cache.ExplainCache - a
per-run cache object (never module-level state) so fit_mcd/fit_ecod/TreeExplainer construction are
each done once per (lot, checkpoint)/(lot, parameter)/fitted-model-object and reused across every
flagged part in a run, instead of refit once per part. Passed to explain_mcd/explain_ecod/
explain_module_b as an optional `cache` argument; default None reproduces the pre-optimization
behavior exactly (a fresh fit on every call) so existing callers/tests are unaffected.
"""
import numpy as np
import pytest

from contracts import FeatureFrame, to_module_b_input
from explain.cache import ExplainCache
from explain.ecod import explain_ecod
from explain.mcd import explain_mcd
from explain.shap_b import explain_module_b
from generator.lot import generate_lot
from features.compute import compute
from module_b.calibration import calibrate_drift_models


def _frame(component_id, parameter, value_0h, lot_median_0h, lot_size=35):
    return FeatureFrame(
        component_id=component_id, lot_id="LOT001", part_number="PN-1", parameter=parameter,
        value_0h=value_0h, value_24h=value_0h + 1.0, value_96h=None, value_168h=None,
        delta_24h=1.0, delta_96h=None, delta_168h=None,
        lot_median_0h=lot_median_0h, lot_median_24h=lot_median_0h + 1.0,
        robust_z={"0h": value_0h - lot_median_0h, "24h": value_0h - lot_median_0h},
        lot_size=lot_size, used_pooled_fallback=False, elapsed_hours={"0h": 0.0, "24h": 24.0},
    )


def _mcd_eligible_lot(n=35, parameters=("iddq", "leakage")):
    rng = np.random.default_rng(11)
    frames = []
    for param_idx, parameter in enumerate(parameters):
        vals = 10.0 + param_idx * 5 + rng.normal(0, 0.5, n)
        med = float(np.median(vals))
        for i in range(n):
            frames.append(_frame(f"C{i:03d}", parameter, float(vals[i]), med, lot_size=n))
    for parameter in parameters:
        offset = 20.0 if parameter == parameters[0] else 0.0
        frames.append(_frame("OUTLIER", parameter, 10.0 + offset, 10.0, lot_size=n + 1))
    return frames


def test_explain_mcd_with_cache_fits_mcd_once_for_repeated_calls_at_the_same_checkpoint(monkeypatch):
    import module_a.detect as module_a_detect_mod
    import explain.mcd as explain_mcd_mod

    calls = []
    orig = module_a_detect_mod.fit_mcd

    def counting_fit_mcd(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    monkeypatch.setattr(explain_mcd_mod, "fit_mcd", counting_fit_mcd)

    frames = _mcd_eligible_lot()
    cache = ExplainCache()
    r1 = explain_mcd(frames, "0h", "OUTLIER", cache=cache)
    r2 = explain_mcd(frames, "0h", "OUTLIER", cache=cache)
    assert len(calls) == 1  # second call reused the cached fit
    assert r1 == r2


def test_explain_mcd_without_cache_still_fits_every_call_old_behavior(monkeypatch):
    import module_a.detect as module_a_detect_mod
    import explain.mcd as explain_mcd_mod

    calls = []
    orig = module_a_detect_mod.fit_mcd

    def counting_fit_mcd(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    monkeypatch.setattr(explain_mcd_mod, "fit_mcd", counting_fit_mcd)

    frames = _mcd_eligible_lot()
    explain_mcd(frames, "0h", "OUTLIER")
    explain_mcd(frames, "0h", "OUTLIER")
    assert len(calls) == 2  # no cache passed -> old behavior, unchanged


def test_explain_mcd_cached_and_uncached_results_are_numerically_identical():
    frames = _mcd_eligible_lot()
    cache = ExplainCache()
    cached = explain_mcd(frames, "0h", "OUTLIER", cache=cache)
    uncached = explain_mcd(frames, "0h", "OUTLIER")
    assert cached == uncached


def test_explain_ecod_with_cache_fits_ecod_once_for_repeated_calls_at_the_same_parameter(monkeypatch):
    import module_a.detect as module_a_detect_mod
    import explain.ecod as explain_ecod_mod

    calls = []
    orig = module_a_detect_mod.fit_ecod

    def counting_fit_ecod(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    monkeypatch.setattr(explain_ecod_mod, "fit_ecod", counting_fit_ecod)

    frames = _mcd_eligible_lot()
    cache = ExplainCache()
    r1 = explain_ecod(frames, "iddq", "OUTLIER", cache=cache)
    r2 = explain_ecod(frames, "iddq", "OUTLIER", cache=cache)
    assert len(calls) == 1
    assert r1 == r2


def test_explain_ecod_cached_and_uncached_results_are_numerically_identical():
    frames = _mcd_eligible_lot()
    cache = ExplainCache()
    cached = explain_ecod(frames, "iddq", "OUTLIER", cache=cache)
    uncached = explain_ecod(frames, "iddq", "OUTLIER")
    assert cached == uncached


PART_NUMBER = "PN-CACHE"


@pytest.fixture(scope="module")
def models():
    lots = [generate_lot(f"{PART_NUMBER}-L{s}", PART_NUMBER, s, account_id="a") for s in range(14)]
    frames = [f for g in lots for f in compute(g.dataset)]
    return calibrate_drift_models(frames)


@pytest.fixture(scope="module")
def sample_inputs(models):
    lot = generate_lot(f"{PART_NUMBER}-CHECK", PART_NUMBER, 999, account_id="a")
    frames = compute(lot.dataset)
    iddq_frames = [f for f in frames if f.parameter == "iddq"][:3]
    return [to_module_b_input(f) for f in iddq_frames]


def test_explain_module_b_with_cache_builds_tree_explainer_once_per_booster(monkeypatch, models, sample_inputs):
    import explain.shap_b as explain_shap_b_mod

    calls = []
    orig = explain_shap_b_mod.shap.TreeExplainer

    def counting_tree_explainer(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    monkeypatch.setattr(explain_shap_b_mod.shap, "TreeExplainer", counting_tree_explainer)

    model = models[(PART_NUMBER, "iddq")]
    cache = ExplainCache()
    results = [explain_module_b(inp, model, cache=cache) for inp in sample_inputs]
    assert len(calls) == 1  # same booster (same part_number/parameter/horizon) - one construction
    assert len(results) == len(sample_inputs)


def test_explain_module_b_without_cache_builds_tree_explainer_every_call_old_behavior(monkeypatch, models, sample_inputs):
    import explain.shap_b as explain_shap_b_mod

    calls = []
    orig = explain_shap_b_mod.shap.TreeExplainer

    def counting_tree_explainer(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    monkeypatch.setattr(explain_shap_b_mod.shap, "TreeExplainer", counting_tree_explainer)

    model = models[(PART_NUMBER, "iddq")]
    for inp in sample_inputs:
        explain_module_b(inp, model)
    assert len(calls) == len(sample_inputs)  # no cache -> old behavior, unchanged


def test_explain_module_b_cached_and_uncached_results_are_numerically_identical(models, sample_inputs):
    model = models[(PART_NUMBER, "iddq")]
    cache = ExplainCache()
    inp = sample_inputs[0]
    cached = explain_module_b(inp, model, cache=cache)
    uncached = explain_module_b(inp, model)
    assert cached == uncached
