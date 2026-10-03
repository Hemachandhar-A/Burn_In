"""scripts/module_b_mae.py: metric functions on hand-computed examples, baselines reproduce their formulas,
the disjointness guard, and a tiny end-to-end run."""
import time

import numpy as np
import pandas as pd
import pytest

from contracts import ModuleBInput
from scripts import module_b_mae as m


def _inp(v0, v24, v96=None, *, lot="L", cid="C1", t24=24.0, t96=96.0) -> ModuleBInput:
    el = {"0h": 0.0, "24h": t24}
    if v96 is not None:
        el["96h"] = t96
    return ModuleBInput(component_id=cid, lot_id=lot, part_number="PN", parameter="iddq", value_0h=v0, value_24h=v24,
                        value_96h=v96, delta_24h=v24 - v0, delta_96h=None if v96 is None else v96 - v0,
                        lot_median_0h=v0, lot_median_24h=v24, robust_z={"0h": 0.0}, lot_size=30,
                        used_pooled_fallback=False, elapsed_hours=el)


def test_abs_and_rel_error_hand_computed():
    pred, actual = [11.0, 8.0, 5.0], [10.0, 10.0, 4.0]
    assert m.abs_error(pred, actual).tolist() == [1.0, 2.0, 1.0]
    assert m.abs_error(pred, actual).mean() == pytest.approx(4 / 3)
    assert m.rel_error(pred, actual).tolist() == pytest.approx([0.1, 0.2, 0.25])


def test_cluster_bootstrap_mean_is_exact_mean_and_ci_brackets_it():
    values = np.array([1.0, 3.0, 2.0, 2.0, 5.0, 5.0])
    lots = np.array(["a", "a", "b", "b", "c", "c"])
    mean, lo, hi = m.cluster_bootstrap_mean(values, lots, reps=500)
    assert mean == pytest.approx(3.0)
    assert lo <= mean <= hi
    assert 2.0 - 1e-9 <= lo and hi <= 5.0 + 1e-9  # lot means are 2, 2, 5
    assert m.cluster_bootstrap_mean(values, lots, reps=500) == (mean, lo, hi)  # deterministic


def test_cluster_bootstrap_single_lot_is_degenerate():
    assert m.cluster_bootstrap_mean([1.0, 3.0], ["a", "a"]) == (2.0, 2.0, 2.0)


def test_baselines_reproduce_their_formulas_24h_mode():
    f = _inp(10.0, 12.0)  # drift +2 over 24h; ratio (168-0)/(24-0) = 7
    assert m.persistence_168h(f) == 12.0
    assert m.linear_168h(f) == pytest.approx(10.0 + 2.0 * 7)
    assert m.fixed_power_law_168h(f) == pytest.approx(10.0 + 2.0 * 7 ** 0.22)
    assert m.fixed_power_law_168h(f, 1.0) == pytest.approx(m.linear_168h(f))


def test_baselines_use_the_96h_reading_when_present():
    f = _inp(10.0, 12.0, 13.0)  # latest = 96h, ratio 168/96 = 1.75
    assert m.persistence_168h(f) == 13.0
    assert m.linear_168h(f) == pytest.approx(10.0 + 3.0 * 1.75)


def test_lot_median_relative_drift_formula():
    frames = [_inp(10.0, 11.0, cid="a"), _inp(10.0, 12.0, cid="b"), _inp(20.0, 20.0 * 1.5, cid="c")]
    # relative drifts: 0.1, 0.2, 0.5 -> lot median 0.2; ratio 7
    pred = m.lot_median_drift_168h(frames)
    g = 7 ** 0.22
    assert pred[("L", "a", "iddq")] == pytest.approx(10.0 * (1 + 0.2 * g))
    assert pred[("L", "c", "iddq")] == pytest.approx(20.0 * (1 + 0.2 * g))  # ignores the part's own drift


def test_lot_median_is_per_lot():
    frames = [_inp(10.0, 11.0, lot="X", cid="a"), _inp(10.0, 15.0, lot="Y", cid="a")]
    pred = m.lot_median_drift_168h(frames)
    g = 7 ** 0.22
    assert pred[("X", "a", "iddq")] == pytest.approx(10.0 * (1 + 0.1 * g))
    assert pred[("Y", "a", "iddq")] == pytest.approx(10.0 * (1 + 0.5 * g))


def _toy_raw(model_err: float, base_err: float) -> pd.DataFrame:
    rows = []
    for fam in ("baseline", "wider_drift_exponent"):
        for lot in ("l1", "l2"):
            for k in range(4):
                actual = 100.0
                row = {"family": fam, "lot_id": f"{fam}-{lot}", "component_id": f"c{k}", "parameter": "iddq",
                       "mode": "24h", "is_defective": k == 0, "defect_type": None, "measured_168h": actual,
                       "true_168h": actual, "forecast_unavailable": False, "interval_lower": 90.0,
                       "interval_upper": 110.0, "pred_model": actual + model_err}
                for b in m.BASELINES:
                    row[f"pred_{b}"] = actual + base_err
                rows.append(row)
    return pd.DataFrame(rows)


def test_summary_and_verdict_on_toy_input():
    raw = _toy_raw(model_err=5.0, base_err=10.0)
    s = m.summarize(raw, reps=50)
    pooled = s[(s["family"] == "ALL") & (s["parameter"] == "ALL") & (s["method"] == "model")].iloc[0]
    assert pooled["mae"] == pytest.approx(5.0) and pooled["rel_mae_pct"] == pytest.approx(5.0)
    assert pooled["coverage"] == 1.0 and pooled["mean_interval_width"] == pytest.approx(20.0)
    v = m.verdict(s)["strict_a_to_e"]
    assert v["improvement_pct"] == pytest.approx(50.0) and v["M1_PASS"] is True


def test_verdict_fails_when_gain_under_10_percent():
    v = m.verdict(m.summarize(_toy_raw(9.5, 10.0), reps=50))["strict_a_to_e"]
    assert v["beats_by_10pct"] is False and v["M1_PASS"] is False


def test_verdict_fails_when_a_held_out_family_loses_by_more_than_10_percent():
    raw = _toy_raw(5.0, 10.0)
    raw.loc[raw["family"] == "wider_drift_exponent", "pred_model"] = 100.0 + 12.0
    v = m.verdict(m.summarize(raw, reps=50))["strict_a_to_e"]
    assert v["held_out"]["wider_drift_exponent"]["loses_by_more_than_10pct"] is True
    assert v["M1_PASS"] is False


def test_unavailable_forecasts_are_excluded_for_every_method():
    raw = _toy_raw(5.0, 10.0)
    raw.loc[raw.index[:3], "forecast_unavailable"] = True
    s = m.summarize(raw, reps=20)
    n = s[(s["family"] == "ALL") & (s["parameter"] == "ALL")]["n"]
    assert set(n) == {len(raw) - 3}


def test_disjointness_guard_passes_and_trips():
    info = m.assert_disjoint_from_training(["baseline"], 3, m.DEFAULT_SEED)
    assert info["derived_lot_seed_overlap"] == 0
    with pytest.raises(RuntimeError):
        m.assert_disjoint_from_training(["baseline"], 3, 5)  # a training seed


def test_tiny_run_end_to_end_under_30_seconds():
    from generator.lot import generate_lot

    m.assert_disjoint_from_training(["baseline"], 1, m.DEFAULT_SEED)
    import module_b.predictor as predictor
    predictor.synthetic_models(m.PART_NUMBER)  # the one-off prior training is not what is timed
    t = time.time()
    lot = generate_lot("M1-baseline-0000", m.PART_NUMBER, m.DEFAULT_SEED, account_id=m.ACCOUNT_ID, family="baseline")
    raw = m.score_lot(lot, "baseline")
    assert time.time() - t < 30
    assert set(raw["mode"]) == {"24h", "96h"} and set(raw["parameter"]) == set(m.PARAMETERS)
    assert raw[[f"pred_{x}" for x in m.BASELINES]].notna().all().all()
    ok = raw[~raw["forecast_unavailable"]]
    assert ok["pred_model"].notna().all() and (ok["interval_lower"] <= ok["interval_upper"]).all()
    s = m.summarize(raw, reps=20)
    assert {"model", *m.BASELINES} <= set(s["method"])
