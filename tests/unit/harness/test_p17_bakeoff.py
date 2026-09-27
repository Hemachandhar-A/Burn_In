"""P1.7: E5 step 6 - the Module A combination-strategy bake-off and config/harness_thresholds.yaml
(harness/bakeoff.py). Hand-built tables for the logic; one small real run for end-to-end determinism.
"""
import typing
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from contracts import HarnessThresholds
from harness import bakeoff, scoring
from harness.golden import GOLDEN_COMPONENT_ID, golden_feature_frames

REPO_ROOT = Path(__file__).resolve().parents[3]


def _table(n_per_family=300, families=("fa", "fb", "fc"), seed=0, informative=("robust_z",)):
    """Parts whose label is driven only by the `informative` detectors; the rest are noise."""
    rng = np.random.default_rng(seed)
    frames = []
    for fam in families:
        y = rng.random(n_per_family) < 0.08
        data = {"lot_id": f"{fam}-L", "component_id": [f"c{i}" for i in range(n_per_family)], "family": fam,
                "is_defective": y, "defect_type": np.where(y, "progressive", None)}
        for det in scoring.DETECTORS:
            base = rng.random(n_per_family) * 0.8
            data[det] = np.where(y, base + 0.2, base) if det in informative else rng.random(n_per_family)
        frames.append(pd.DataFrame(data))
    return pd.concat(frames, ignore_index=True)


def test_strategies_are_exactly_the_contracted_literal():
    literal = typing.get_args(HarnessThresholds.model_fields["combination_strategy"].annotation)
    assert bakeoff.STRATEGIES == literal


def test_max_strategy_is_module_a_default_combination():
    table = _table()
    fitted = bakeoff.fit_strategy("max", table)
    np.testing.assert_array_equal(fitted.score(table), table[list(scoring.DETECTORS)].max(axis=1).to_numpy())
    assert fitted.params == {}


def test_weighted_average_weights_are_a_grid_point_on_the_simplex_and_find_the_signal():
    table = _table(informative=("ecod",))
    fitted = bakeoff.fit_strategy("weighted_average", table)
    w = fitted.params["weights"]
    assert set(w) == set(scoring.DETECTORS)
    assert sum(w.values()) == pytest.approx(1.0)
    assert all(v >= 0 and round(v * 10) == pytest.approx(v * 10) for v in w.values())
    assert max(w, key=w.get) == "ecod"


def test_meta_model_is_deterministic_and_scores_are_probabilities():
    table = _table(informative=("mcd", "ecod"))
    a, b = bakeoff.fit_strategy("meta_model", table), bakeoff.fit_strategy("meta_model", table)
    np.testing.assert_array_equal(a.score(table), b.score(table))
    assert ((a.score(table) >= 0) & (a.score(table) <= 1)).all()
    assert set(a.params["coefficients"]) == set(scoring.DETECTORS)


def test_unknown_strategy_is_an_error():
    with pytest.raises(ValueError):
        bakeoff.fit_strategy("average_of_everything", _table())


def test_leave_one_family_out_never_fits_on_the_held_out_family(monkeypatch):
    table = _table()
    seen = []
    real = bakeoff.fit_strategy

    def spy(name, train, *args, **kwargs):
        seen.append(set(train["family"]))
        return real(name, train, *args, **kwargs)

    monkeypatch.setattr(bakeoff, "fit_strategy", spy)
    folds = bakeoff.leave_one_family_out(table)
    assert len(folds) == len(bakeoff.STRATEGIES) * 3
    for row in folds.itertuples():
        assert row.held_out_family not in seen[row.Index]
    assert set(folds.columns) >= {"strategy", "held_out_family", "threshold", "cost", "recall", "precision"}


def test_leave_one_family_out_needs_two_families():
    with pytest.raises(ValueError):
        bakeoff.leave_one_family_out(_table(families=("only",)))


def test_winner_is_lowest_mean_held_out_cost_with_ties_going_to_the_default():
    folds = pd.DataFrame({"strategy": ["max", "weighted_average", "meta_model"] * 2,
                          "held_out_family": ["a"] * 3 + ["b"] * 3,
                          "cost": [0.3, 0.2, 0.4, 0.3, 0.2, 0.4]})
    assert bakeoff.choose_winner(folds) == "weighted_average"
    tied = folds.assign(cost=0.25)
    assert bakeoff.choose_winner(tied) == "max"


def test_reject_at_the_locked_10_to_1_and_review_at_the_disclosed_20_to_1():
    """One cost ratio yields one cut; REVIEW and REJECT come from the same search at two ratios."""
    table = _table()
    th = bakeoff.derive_thresholds(table, "max")
    assert isinstance(th, HarnessThresholds)
    assert th.combination_strategy == "max"
    scores, y = table[list(scoring.DETECTORS)].max(axis=1), table["is_defective"]
    assert th.module_a_reject_threshold == scoring.tune_threshold(scores, y, 10.0)
    assert th.module_a_review_threshold == scoring.tune_threshold(scores, y, 20.0)
    assert th.module_a_review_threshold <= th.module_a_reject_threshold


def test_cost_ratios_are_the_locked_default_and_the_disclosed_review_ratio():
    assert scoring.FN_FP_COST_RATIO == 10.0  # REJECT and the bake-off
    assert scoring.REVIEW_FN_FP_COST_RATIO == 20.0
    assert not hasattr(scoring, "REJECT_FN_FP_COST_RATIO")  # the unauthorized 1:1 never returns


def test_the_shipped_strategy_is_max_by_lead_decision():
    assert bakeoff.SHIPPED_STRATEGY == "max"


def test_thresholds_yaml_round_trips_with_exactly_the_contracted_keys(tmp_path):
    th = HarnessThresholds(module_a_review_threshold=0.9, module_a_reject_threshold=0.99,
                           combination_strategy="max")
    path = tmp_path / "harness_thresholds.yaml"
    bakeoff.write_harness_thresholds(th, path, provenance=["seed: 1"])
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert set(raw) == set(HarnessThresholds.model_fields)
    assert bakeoff.load_harness_thresholds(path) == th
    assert "# seed: 1" in path.read_text(encoding="utf-8")


def test_meta_model_score_equals_scikit_learn_predict_proba():
    from sklearn.linear_model import LogisticRegression
    table = _table(informative=("mcd",))
    X, y = table[list(scoring.DETECTORS)].to_numpy(float), table["is_defective"].to_numpy(bool)
    np.testing.assert_allclose(bakeoff.fit_strategy("meta_model", table).score(table),
                               LogisticRegression(max_iter=1000).fit(X, y).predict_proba(X)[:, 1])


def test_small_real_bakeoff_is_reproducible_and_ships_max_whatever_wins():
    kwargs = {"seed": 5, "families": ("baseline", "higher_defect_prevalence"), "min_per_archetype": 2, "min_lots": 3}
    a = bakeoff.run_bakeoff(**kwargs)
    b = bakeoff.run_bakeoff(**kwargs)
    assert a["empirical_winner"] == b["empirical_winner"]
    assert a["thresholds"] == b["thresholds"]
    assert a["thresholds"]["combination_strategy"] == "max"
    pd.testing.assert_frame_equal(pd.DataFrame(a["folds"]), pd.DataFrame(b["folds"]))


# --- the committed artifact P3.3 reads ----------------------------------------------------------------------

COMMITTED_PATH = REPO_ROOT / "config" / "harness_thresholds.yaml"


@pytest.fixture(scope="module")
def committed():
    return bakeoff.load_harness_thresholds(COMMITTED_PATH)


def test_committed_thresholds_file_is_in_the_contracted_shape(committed):
    assert isinstance(committed, HarnessThresholds)
    assert committed.combination_strategy == "max"
    assert 0.0 < committed.module_a_review_threshold < committed.module_a_reject_threshold <= 1.0
    raw = yaml.safe_load(COMMITTED_PATH.read_text(encoding="utf-8"))
    assert set(raw) == set(HarnessThresholds.model_fields)  # no TEMP_ key: max has no parameters


def test_committed_thresholds_file_names_no_rejected_strategy():
    text = COMMITTED_PATH.read_text(encoding="utf-8")
    assert "meta_model" not in text and "weighted_average" not in text and "TEMP_" not in text


def test_committed_thresholds_flag_the_golden_part_at_reject(committed):
    """AGENTS.md rule 5: once P3.3 applies these thresholds, the worked example must be flagged. Under max it
    scores 1.0 (top of its lot on the z-score), so it clears the 20:1 REVIEW and the 10:1 REJECT alike."""
    from module_a.detect import detect
    parts = scoring.part_detector_scores(detect(golden_feature_frames()))
    golden = parts[parts["component_id"] == GOLDEN_COMPONENT_ID]
    score = bakeoff.fit_strategy("max", golden).score(golden)[0]
    assert score == 1.0
    assert score >= committed.module_a_review_threshold
    assert score >= committed.module_a_reject_threshold


def test_committed_thresholds_match_the_committed_evaluation_report(committed):
    import json
    report = json.loads((REPO_ROOT / "harness" / "results" / "p17_evaluation.json").read_text(encoding="utf-8"))
    assert HarnessThresholds(**report["thresholds"]) == committed
    assert report["shipped_strategy"] == committed.combination_strategy == "max"
    assert report["empirical_winner"] == bakeoff.choose_winner(pd.DataFrame(report["folds"]))
