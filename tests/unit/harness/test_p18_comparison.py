"""P1.8: E5 step 7 - comparison tables for the PPT's differentiation-versus-industry-baseline slide
(harness/comparison.py). Hand-built tables for the arithmetic; one small real held-out set end to end.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from contracts import HarnessThresholds
from harness import comparison
from harness.golden import golden_lot
from harness.held_out import generate_held_out_set

THRESHOLDS = HarnessThresholds(module_a_review_threshold=0.9, module_a_reject_threshold=0.95,
                               combination_strategy="max")


def _parts():
    """Six parts, two defective; hand-checkable flags per method."""
    return pd.DataFrame({
        "lot_id": "L", "component_id": [f"c{i}" for i in range(6)], "family": ["f1"] * 3 + ["f2"] * 3,
        "is_defective": [True, False, False, True, False, False],
        "defect_type": ["progressive", None, None, "latent_post_24h", None, None],
        "module_a_score": [0.99, 0.92, 0.10, 0.50, 0.20, 0.30],
        "static_limits_flagged": [False] * 6, "static_limits_score": [0.5] * 6,
        "static_limits_evaluable": [True] * 6,
        "fixed_delta_flagged": [True, True, False, False, False, False],
        "fixed_delta_score": [2.0, 1.5, 0.1, 0.2, 0.1, 0.1],
        "fixed_delta_evaluable": [True] * 6,
        "static_pat_flagged": [False] * 6, "static_pat_score": [np.nan] * 6,
        "static_pat_evaluable": [False] * 6,
        "dynamic_pat_flagged": [True, False, False, True, False, False],
        "dynamic_pat_score": [3.0, 0.1, 0.1, 1.2, 0.1, 0.1],
        "dynamic_pat_evaluable": [True] * 6,
    })


def test_methods_are_the_four_named_industry_baselines_then_module_a():
    assert comparison.BASELINES == ("static_limits", "fixed_delta", "static_pat", "dynamic_pat")
    assert comparison.METHODS == comparison.BASELINES + ("module_a_review", "module_a_reject")


def test_module_a_flags_come_from_the_committed_thresholds():
    parts = comparison.add_module_a_flags(_parts(), THRESHOLDS)
    assert parts["module_a_review_flagged"].tolist() == [True, True, False, False, False, False]
    assert parts["module_a_reject_flagged"].tolist() == [True, False, False, False, False, False]


def test_headline_table_by_hand():
    table = comparison.headline_table(comparison.add_module_a_flags(_parts(), THRESHOLDS)).set_index("method")
    assert list(table.index) == list(comparison.METHODS)
    delta = table.loc["fixed_delta"]
    assert delta["recall"] == 0.5 and delta["precision"] == 0.5 and delta["false_alarms"] == 1
    assert delta["flag_rate"] == pytest.approx(2 / 6)
    assert delta["cost_per_part"] == pytest.approx((10 * 1 + 1) / 6)  # the locked 10:1
    dpat = table.loc["dynamic_pat"]
    assert dpat["recall"] == 1.0 and dpat["false_alarms"] == 0


def test_a_method_that_cannot_judge_a_part_is_reported_never_counted_as_a_pass():
    table = comparison.headline_table(comparison.add_module_a_flags(_parts(), THRESHOLDS)).set_index("method")
    assert table.loc["static_pat", "evaluable_share"] == 0.0
    assert np.isnan(table.loc["static_pat", "recall"])
    assert table.loc["fixed_delta", "evaluable_share"] == 1.0


def test_per_archetype_recall_is_long_form_and_chart_ready():
    long = comparison.archetype_recall(comparison.add_module_a_flags(_parts(), THRESHOLDS))
    assert set(long.columns) == {"method", "defect_type", "n", "recall"}
    row = long[(long.method == "dynamic_pat") & (long.defect_type == "latent_post_24h")].iloc[0]
    assert row["n"] == 1 and row["recall"] == 1.0
    row = long[(long.method == "fixed_delta") & (long.defect_type == "latent_post_24h")].iloc[0]
    assert row["recall"] == 0.0


def test_matched_flag_budget_gives_module_a_exactly_each_baselines_flag_count():
    parts = comparison.add_module_a_flags(_parts(), THRESHOLDS)
    matched = comparison.matched_flag_budget(parts).set_index("baseline")
    row = matched.loc["fixed_delta"]
    assert row["n_flagged"] == 2
    assert row["baseline_recall"] == 0.5
    assert row["module_a_recall"] == 0.5  # Module A's top 2 are c0 (defective) and c1 (healthy)
    assert "static_pat" not in matched.index  # nothing evaluable: no budget to match
    assert "static_limits" not in matched.index  # flagged nothing: a zero budget is no comparison


def test_golden_example_table_names_what_each_method_does_with_the_worked_example():
    table = comparison.golden_example_table().set_index("method")
    assert not table.loc["static_limits", "flagged"]   # 45 uA under a 50 uA limit: the statement's point
    assert table.loc["static_limits", "score"] == pytest.approx(0.9)
    assert not table.loc["fixed_delta", "flagged"]     # a flat part never moves
    assert table.loc["dynamic_pat", "flagged"]
    assert not table.loc["static_pat", "evaluable"]    # no pooled reference for this part number
    assert table.loc["module_a", "flagged"] and table.loc["module_a", "tier"] == "REJECT"


def test_reference_lots_for_static_pat_never_overlap_the_held_out_sets():
    ref = comparison.reference_lots(seed=3, n_lots=3)
    held = generate_held_out_set("baseline", seed=3, min_per_archetype=1)
    assert not {d.lot_id for d in ref} & set(held.lot_ids)
    assert {d.part_number for d in ref} == {held.lots[0].dataset.part_number}


@pytest.fixture(scope="module")
def small_parts():
    sets = {"baseline": generate_held_out_set("baseline", seed=7, min_per_archetype=2, min_lots=3)}
    return comparison.part_table(sets, THRESHOLDS, seed=7, n_reference_lots=3)


def test_part_table_has_every_held_out_part_once_with_every_method(small_parts):
    assert small_parts[["lot_id", "component_id"]].duplicated().sum() == 0
    for method in comparison.METHODS:
        assert small_parts[f"{method}_flagged"].dtype == bool
    assert small_parts["is_defective"].sum() > 0


def test_write_outputs_produces_csv_and_markdown(small_parts, tmp_path):
    comparison.write_outputs(small_parts, tmp_path, module_b=None)
    for name in ("headline.csv", "archetype_recall.csv", "matched_flag_budget.csv", "golden_example.csv",
                 "comparison.md"):
        assert (tmp_path / name).is_file(), name
    md = (tmp_path / "comparison.md").read_text(encoding="utf-8")
    assert "static_limits" in md and "module_a_review" in md


def test_committed_outputs_exist_and_agree_with_the_committed_thresholds():
    root = Path(__file__).resolve().parents[3] / "harness" / "results" / "p18"
    headline = pd.read_csv(root / "headline.csv").set_index("method")
    assert list(headline.index) == list(comparison.METHODS)
    assert headline.loc["module_a_review", "recall"] >= headline.loc["module_a_reject", "recall"]
    golden = pd.read_csv(root / "golden_example.csv").set_index("method")
    assert bool(golden.loc["module_a", "flagged"])


def test_golden_lot_is_the_p16_fixture():
    assert golden_lot().lot_id == comparison.golden_example_table().attrs["lot_id"]
