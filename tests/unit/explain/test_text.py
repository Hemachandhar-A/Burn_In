"""Block 3B Part 3: E4 steps 5-10's text/notes, pure functions over already-computed values
(AGENTS.md rule 1 - nothing here re-derives a detector's own math). Fixed inputs only, no randomness
(rule 9)."""
from explain.text import explanation_sentence


def test_explanation_sentence_golden_part_module_a_and_b():
    """GOLDEN-045, leakage: Module A's z-score row (above-median, real numbers from the worked
    example) plus a Module B result and its top SHAP feature - both sentence clauses must appear,
    using the real numbers passed in, never a placeholder."""
    from explain.models import FeatureContribution, ShapExplanation, ZScoreRow
    from contracts import ModuleBResult

    zrow = ZScoreRow(parameter="leakage", value=45.0, lot_median=10.0, z=4.2)
    module_b = ModuleBResult(
        component_id="GOLDEN-045", lot_id="GOLDEN-LOT-01", parameter="leakage",
        predicted_168h=69.0, interval_lower=60.0, interval_upper=78.0,
        physics_baseline_prediction=65.0, physics_disagreement_gap=4.0,
        drift_rate=1.38, exceeds_safety_slope=True, safety_slope=1.0,
        lower_bound_exceeds_safety_slope=True, forecast_unavailable=False,
    )
    shap = ShapExplanation(
        component_id="GOLDEN-045", parameter="leakage", horizon="24h", base_value=10.0,
        model_prediction=45.0,
        contributions=[
            FeatureContribution(feature="delta_24h", value=35.0, shap_value=20.0),
            FeatureContribution(feature="value_0h", value=45.0, shap_value=5.0),
        ],
    )

    sentence = explanation_sentence("GOLDEN-045", zscore_row=zrow, module_b=module_b, shap=shap)

    assert sentence.startswith("Part GOLDEN-045:")
    assert "leakage at 24h is 4.2 robust-sigma above lot median" in sentence
    assert "median = 10" in sentence and "value = 45" in sentence
    assert "Predicted 168h drift exceeds the calibrated safety slope by 38%" in sentence
    assert "Primary driver: delta_24h" in sentence


def test_explanation_sentence_below_median_direction_worded_correctly():
    from explain.models import ZScoreRow

    zrow = ZScoreRow(parameter="leakage", value=5.0, lot_median=10.0, z=-3.1)
    sentence = explanation_sentence("C1", zscore_row=zrow, module_b=None, shap=None)
    assert "leakage at 24h is 3.1 robust-sigma below lot median" in sentence
    assert "median = 10" in sentence and "value = 5" in sentence


def test_explanation_sentence_module_b_only_part():
    """A Module-B-only part (e.g. an in-progress lot, Module A never ran): no z-score clause, only
    the drift-forecast clause and primary driver."""
    from explain.models import FeatureContribution, ShapExplanation
    from contracts import ModuleBResult

    module_b = ModuleBResult(
        component_id="C9", lot_id="L1", parameter="leakage", predicted_168h=50.0,
        interval_lower=45.0, interval_upper=55.0, physics_baseline_prediction=48.0,
        physics_disagreement_gap=2.0, drift_rate=1.38, exceeds_safety_slope=True, safety_slope=1.0,
        lower_bound_exceeds_safety_slope=True, forecast_unavailable=False,
    )
    shap = ShapExplanation(
        component_id="C9", parameter="leakage", horizon="24h", base_value=10.0, model_prediction=50.0,
        contributions=[FeatureContribution(feature="delta_24h", value=40.0, shap_value=25.0)],
    )
    sentence = explanation_sentence("C9", zscore_row=None, module_b=module_b, shap=shap)
    assert sentence == (
        "Part C9: Predicted 168h drift exceeds the calibrated safety slope by 38%. "
        "Primary driver: delta_24h."
    )


def test_explanation_sentence_module_b_under_slope_worded_correctly():
    from contracts import ModuleBResult

    module_b = ModuleBResult(
        component_id="C2", lot_id="L1", parameter="leakage", predicted_168h=20.0,
        interval_lower=15.0, interval_upper=25.0, physics_baseline_prediction=19.0,
        physics_disagreement_gap=1.0, drift_rate=0.5, exceeds_safety_slope=False, safety_slope=1.0,
        lower_bound_exceeds_safety_slope=False, forecast_unavailable=False,
    )
    sentence = explanation_sentence("C2", zscore_row=None, module_b=module_b, shap=None)
    assert "Predicted 168h drift is under the calibrated safety slope by 50%" in sentence
    assert "Primary driver" not in sentence


def test_explanation_sentence_module_a_only_part_no_module_b_clause():
    from explain.models import ZScoreRow

    zrow = ZScoreRow(parameter="iddq", value=12.0, lot_median=12.0, z=0.0)
    sentence = explanation_sentence("C3", zscore_row=zrow, module_b=None, shap=None)
    assert sentence == "Part C3: iddq at 24h is 0.0 robust-sigma above lot median (median = 12, value = 12)."


def test_explanation_sentence_forecast_unavailable_module_b_never_claimed():
    """rule 7/E4 step 9's discipline extends here: a module_b with forecast_unavailable=True must
    never contribute a drift clause, even if passed in - unavailable_forecast_note (3e) is the
    dedicated place for that, this sentence must simply omit it."""
    from explain.models import ZScoreRow
    from contracts import ModuleBResult

    zrow = ZScoreRow(parameter="custom_param", value=1.0, lot_median=1.0, z=0.0)
    module_b = ModuleBResult(
        component_id="C4", lot_id="L1", parameter="custom_param", predicted_168h=None,
        interval_lower=None, interval_upper=None, physics_baseline_prediction=None,
        physics_disagreement_gap=None, drift_rate=None, exceeds_safety_slope=None, safety_slope=None,
        lower_bound_exceeds_safety_slope=None, forecast_unavailable=True,
    )
    sentence = explanation_sentence("C4", zscore_row=zrow, module_b=module_b, shap=None)
    assert "Predicted 168h drift" not in sentence
