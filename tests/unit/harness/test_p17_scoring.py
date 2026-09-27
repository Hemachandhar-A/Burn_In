"""P1.7: E5 steps 4-5 - Module A scoring against held-out ground truth, Module B against the physics baselines
(harness/scoring.py). Fast tests use hand-built tables; the tests that call the real module_a.detect() and
module_b.predict() use one small held-out set, generated once per module.
"""
import math

import numpy as np
import pandas as pd
import pytest

from contracts import ModuleAResult, ScreeningConfig
from harness import scoring
from harness.golden import GOLDEN_COMPONENT_ID, GOLDEN_LOT_ID, golden_feature_frames
from harness.held_out import generate_held_out_set


def _result(cid, param, *, lot="L1", z=0.0, mcd=None, iso=None, ecod=0.0, direction="above_median"):
    return ModuleAResult(
        component_id=cid, lot_id=lot, parameter=param, robust_z=z, mcd_distance=mcd,
        isolation_forest_score=iso, ecod_score=ecod,
        explainable_tags={"robust_z": True, "mcd": mcd is not None, "isolation_forest": False, "ecod": False},
        direction=direction, severity_tier="PASS", severity_cap_reason=None,
        combined_severity=1.0, explainable_corroboration=True,
    )


# --- cost function and threshold search (E5 step 4: one locked cost function) -------------------------------

def test_expected_cost_weights_a_miss_by_the_locked_ratio():
    y = np.array([1, 0, 0, 0])
    assert scoring.expected_cost(y, np.array([False, False, False, False]), 10.0) == pytest.approx(10 / 4)
    assert scoring.expected_cost(y, np.array([True, True, False, False]), 10.0) == pytest.approx(1 / 4)


def test_default_cost_ratio_is_the_screening_config_default_not_a_new_number():
    assert scoring.FN_FP_COST_RATIO == ScreeningConfig().fn_fp_cost_ratio == 10.0


def test_tune_threshold_minimises_cost_and_places_the_cut_between_scores():
    scores = np.array([0.9, 0.8, 0.7, 0.2, 0.1])
    y = np.array([1, 1, 0, 1, 0])
    # 10:1 - catching the 0.2 defect costs one false alarm (0.7), worth it: cut between 0.2 and 0.1
    t = scoring.tune_threshold(scores, y, 10.0)
    assert 0.1 < t <= 0.2
    # 1:4 (a false alarm is dearer than a miss): flag only the top two
    t = scoring.tune_threshold(scores, y, 0.25)
    assert 0.7 < t <= 0.8


def test_tune_threshold_ties_resolve_toward_recall():
    # Flagging the 0.5 part costs one FP and saves one FN: equal at 1:1 - the lower threshold (more recall) wins
    scores = np.array([0.9, 0.5, 0.5])
    y = np.array([1, 1, 0])
    assert scoring.tune_threshold(scores, y, 1.0) <= 0.5


def test_tune_threshold_with_no_defects_flags_nothing():
    t = scoring.tune_threshold(np.array([0.3, 0.9]), np.array([0, 0]), 10.0)
    assert t > 0.9


def test_tune_threshold_rejects_mismatched_or_empty_input():
    with pytest.raises(ValueError):
        scoring.tune_threshold(np.array([]), np.array([]), 10.0)
    with pytest.raises(ValueError):
        scoring.tune_threshold(np.array([0.1, 0.2]), np.array([1]), 10.0)
    with pytest.raises(ValueError):
        scoring.tune_threshold(np.array([0.1, math.nan]), np.array([1, 0]), 10.0)


def test_classification_metrics_include_f2_for_monitoring():
    m = scoring.classification_metrics(np.array([1, 1, 0, 0]), np.array([True, False, True, False]), 10.0)
    assert m["recall"] == 0.5 and m["precision"] == 0.5
    assert m["f2"] == pytest.approx(0.5)
    assert m["flag_rate"] == 0.5
    assert m["cost"] == pytest.approx((10 + 1) / 4)


def test_recall_at_fixed_flag_rates_flags_the_top_fraction():
    scores = np.arange(100, dtype=float)
    y = np.zeros(100, dtype=int)
    y[-5:] = 1   # the five highest scores are the defects
    table = scoring.recall_at_flag_rates(scores, y, (0.05, 0.10))
    row5 = table.set_index("flag_rate").loc[0.05]
    assert row5["recall"] == 1.0 and row5["precision"] == 1.0 and row5["n_flagged"] == 5
    assert table.set_index("flag_rate").loc[0.10, "precision"] == 0.5


# --- the TEMP percentile mirror of module_a's step 5 --------------------------------------------------------

def test_detector_percentiles_are_lot_relative_and_absent_scores_tie_at_zero():
    lot1 = [_result("A", "iddq", z=5.0, ecod=3.0), _result("B", "iddq", z=1.0, ecod=1.0)]
    lot2 = [_result("A", "iddq", lot="L2", z=0.1, ecod=9.0, iso=-0.7),
            _result("B", "iddq", lot="L2", z=0.2, ecod=0.0, iso=-0.4)]
    pct = scoring.TEMP_detector_percentiles(lot1 + lot2).set_index(["lot_id", "component_id"])
    assert pct.loc[("L1", "A"), "robust_z"] == 1.0 and pct.loc[("L1", "B"), "robust_z"] == 0.5
    # component IDs reused across lots never collide - ranks are per lot
    assert pct.loc[("L2", "A"), "robust_z"] == 0.5
    # absent MCD / cold-start IF -> every part tied at the average rank
    assert pct.loc[("L1", "A"), "mcd"] == pct.loc[("L1", "B"), "mcd"] == 0.75
    # IF: sklearn's lower-is-more-anomalous is negated, like module_a
    assert pct.loc[("L2", "A"), "isolation_forest"] == 1.0


def test_part_scores_take_the_worst_parameter_per_detector():
    results = [_result("A", "iddq", z=5.0), _result("A", "leakage", z=0.1, ecod=4.0),
               _result("B", "iddq", z=1.0), _result("B", "leakage", z=0.2, ecod=1.0)]
    parts = scoring.part_detector_scores(results).set_index("component_id")
    assert parts.loc["A", "robust_z"] == 1.0          # iddq's rank, the worst of A's two parameters
    assert parts.loc["A", "ecod"] == 1.0              # leakage's rank
    assert list(parts.columns[-4:]) == list(scoring.DETECTORS)


def test_percentile_mirror_matches_module_a_internal_combined_score():
    """The re-derivation must agree with module_a's own combined score, observable through its direction cap:
    a below-median frame is capped exactly when its max-combined percentile >= module_a's cap threshold."""
    from module_a.detect import _CAP_PERCENTILE_THRESHOLD, detect
    results = detect(golden_feature_frames())
    pct = scoring.TEMP_detector_percentiles(results)
    combined = pct[list(scoring.DETECTORS)].max(axis=1).to_numpy()
    below = np.array([r.direction == "below_median" for r in results])
    capped = np.array([r.severity_cap_reason is not None for r in results])
    assert below.any()
    np.testing.assert_array_equal(capped, below & (combined >= _CAP_PERCENTILE_THRESHOLD))


# --- real module calls on a small held-out set --------------------------------------------------------------

@pytest.fixture(scope="module")
def small_set():
    return generate_held_out_set("higher_defect_prevalence", seed=11, min_per_archetype=2, min_lots=3)


def test_run_module_a_calls_detect_once_per_lot_with_earlier_lots_as_history(small_set, monkeypatch):
    import module_a.detect as module_a_detect
    calls = []
    real = module_a_detect.detect

    def spy(frames, prior_frames=None):
        calls.append(({f.lot_id for f in frames}, {f.lot_id for f in (prior_frames or [])}))
        return real(frames, prior_frames)

    monkeypatch.setattr(module_a_detect, "detect", spy)
    scoring.run_module_a(small_set)
    ids = small_set.lot_ids
    assert [c[0] for c in calls] == [{i} for i in ids]
    assert [c[1] for c in calls] == [set(ids[:k]) for k in range(len(ids))]  # cold start on the first lot


def test_module_a_table_joins_every_part_to_its_ground_truth(small_set):
    table = scoring.module_a_table(small_set)
    assert len(table) == small_set.n_parts
    assert table["is_defective"].sum() == small_set.n_defective
    assert not table[list(scoring.DETECTORS)].isna().any().any()
    assert table[["lot_id", "component_id"]].duplicated().sum() == 0


def test_module_a_table_is_deterministic(small_set):
    pd.testing.assert_frame_equal(scoring.module_a_table(small_set), scoring.module_a_table(small_set))


def test_module_b_table_scores_both_horizons_against_the_real_168h(small_set):
    table = scoring.module_b_table(small_set)
    assert set(table["horizon"]) == {"96h", "24h"}
    one_lot = small_set.lots[0]
    truth = {(r.component_id, r.parameter): r.value for r in one_lot.dataset.readings if r.checkpoint_hour == 168.0}
    rows = table[(table["lot_id"] == one_lot.dataset.lot_id)]
    for row in rows.head(20).itertuples():
        assert row.actual_168h == truth[(row.component_id, row.parameter)]
    available = table[~table["forecast_unavailable"]]
    assert len(available) > 0
    assert (available["interval_lower"] <= available["interval_upper"]).all()
    for col in ("persistence", "linear", "power_law"):
        assert table[col].notna().all()


def test_module_b_summary_reports_mae_and_coverage_against_each_baseline(small_set):
    summary = scoring.summarize_module_b(scoring.module_b_table(small_set))
    for col in ("mae_model", "mae_persistence", "mae_linear", "mae_power_law", "coverage", "target_coverage"):
        assert col in summary.columns
    assert summary["coverage"].between(0, 1).all()
    assert (summary["target_coverage"] == 0.90).all()


def test_module_b_mae_by_hand():
    table = pd.DataFrame({
        "family": "f", "parameter": "iddq", "horizon": "96h", "lot_id": "L", "component_id": ["a", "b"],
        "actual_168h": [10.0, 20.0], "predicted_168h": [11.0, 18.0], "interval_lower": [9.0, 19.0],
        "interval_upper": [12.0, 19.5], "persistence": [10.0, 10.0], "linear": [10.0, 20.0],
        "power_law": [12.0, 20.0], "forecast_unavailable": False, "exceeds_safety_slope": [False, True],
        "is_defective": [False, True],
    })
    row = scoring.summarize_module_b(table).iloc[0]
    assert row["mae_model"] == 1.5 and row["mae_persistence"] == 5.0 and row["mae_linear"] == 0.0
    assert row["coverage"] == 0.5
    assert row["best_baseline"] == "linear" and not row["model_beats_best_baseline"]


def test_golden_part_scores_top_of_its_lot():
    from module_a.detect import detect
    parts = scoring.part_detector_scores(detect(golden_feature_frames()))
    golden = parts[(parts["lot_id"] == GOLDEN_LOT_ID) & (parts["component_id"] == GOLDEN_COMPONENT_ID)]
    assert golden[list(scoring.DETECTORS)].max(axis=1).iloc[0] == 1.0
