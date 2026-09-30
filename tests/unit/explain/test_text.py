"""Block 3B Part 3: E4 steps 5-10's text/notes, pure functions over already-computed values
(AGENTS.md rule 1 - nothing here re-derives a detector's own math). Fixed inputs only, no randomness
(rule 9)."""
from contracts import ModuleBResult, RiskAssessment
from explain.text import confidence_qualifier, explanation_sentence, explanation_summary, severity_cap_note


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


# --- Part 3b: confidence_qualifier (E4 step 6) ----------------------------------------------------

def _module_b(**overrides):
    base = dict(
        component_id="C1", lot_id="L1", parameter="leakage", predicted_168h=50.0,
        interval_lower=45.0, interval_upper=55.0, physics_baseline_prediction=48.0,
        physics_disagreement_gap=2.0, drift_rate=1.5, exceeds_safety_slope=True, safety_slope=1.0,
        lower_bound_exceeds_safety_slope=True, forecast_unavailable=False,
    )
    base.update(overrides)
    return ModuleBResult(**base)


def test_confidence_qualifier_none_when_module_b_did_not_run():
    assert confidence_qualifier(None) is None


def test_confidence_qualifier_none_when_forecast_unavailable():
    module_b = _module_b(
        forecast_unavailable=True, predicted_168h=None, interval_lower=None, interval_upper=None,
        physics_baseline_prediction=None, physics_disagreement_gap=None, drift_rate=None,
        exceeds_safety_slope=None, safety_slope=None, lower_bound_exceeds_safety_slope=None,
    )
    assert confidence_qualifier(module_b) is None


def test_confidence_qualifier_high_confidence_when_both_signals_agree():
    # interval_lower/upper agree with the point estimate (both True), physics gap (2.0) within
    # half the interval width (5.0) * the multiplier.
    module_b = _module_b(exceeds_safety_slope=True, lower_bound_exceeds_safety_slope=True,
                          interval_lower=45.0, interval_upper=55.0, physics_disagreement_gap=2.0)
    assert confidence_qualifier(module_b) == "high confidence"


def test_confidence_qualifier_borderline_when_interval_band_disagrees():
    # Point estimate says exceeds, but the interval's lower bound does not - the interval is wide
    # enough that narrowing it slightly could flip the call.
    module_b = _module_b(exceeds_safety_slope=True, lower_bound_exceeds_safety_slope=False)
    assert confidence_qualifier(module_b) == "borderline - recommend retest"


def test_confidence_qualifier_borderline_when_physics_disagreement_exceeds_half_interval_width():
    # interval width 10.0 -> half-width 5.0; physics gap 5.01 is just past the boundary.
    module_b = _module_b(exceeds_safety_slope=True, lower_bound_exceeds_safety_slope=True,
                          interval_lower=45.0, interval_upper=55.0, physics_disagreement_gap=5.01)
    assert confidence_qualifier(module_b) == "borderline - recommend retest"


def test_confidence_qualifier_high_confidence_exactly_at_physics_boundary():
    # physics gap exactly equal to half-width * multiplier is still "agrees" (<=), not borderline.
    module_b = _module_b(exceeds_safety_slope=True, lower_bound_exceeds_safety_slope=True,
                          interval_lower=45.0, interval_upper=55.0, physics_disagreement_gap=5.0)
    assert confidence_qualifier(module_b) == "high confidence"


# --- Part 3c: explanation_summary (E4 step 7) -----------------------------------------------------

def _assessment(cid, verdict, worst_parameter, lot_id="L1"):
    return RiskAssessment(
        component_id=cid, lot_id=lot_id, verdict=verdict, module_a_rank=1.0, module_b_rank=1.0,
        worst_parameter=worst_parameter, module_a_ran=True, module_b_ran=True,
        predicted_168h=None, actual_168h=None, explanation_sentence=None,
    )


def test_explanation_summary_on_the_golden_lot():
    """Real numbers from the golden pipeline (harness.golden.run_golden_pipeline): 77 parts, 5
    flagged (2 WATCH, 3 REJECT), worst_parameter tied 2-2 between iddq and prop_delay (leakage=1) -
    alphabetical tie-break picks iddq."""
    from harness.golden import run_golden_pipeline

    result = run_golden_pipeline()
    summary = explanation_summary(result.assessments, result.insufficient_data_components)
    assert summary == "5 of 77 parts flagged, concentrated in iddq, 2 crossing REVIEW only."


def test_explanation_summary_no_flags():
    assessments = [_assessment("C1", "PASS", "iddq"), _assessment("C2", "PASS", "leakage")]
    assert explanation_summary(assessments, []) == "0 of 2 parts flagged."


def test_explanation_summary_zero_assessments():
    assert explanation_summary([], []) == "No parts analysed."


def test_explanation_summary_appends_missing_components_sentence():
    assessments = [_assessment("C1", "REJECT", "leakage")]
    summary = explanation_summary(assessments, ["C9", "C7"])
    assert summary == (
        "1 of 1 parts flagged, concentrated in leakage. "
        "2 components have insufficient data and were not analysed: C7, C9."
    )


def test_explanation_summary_missing_components_singular_wording():
    summary = explanation_summary([], ["C7"])
    assert summary == "No parts analysed. 1 component has insufficient data and was not analysed: C7."


# --- Part 3d: severity_cap_note (E4 step 8) -------------------------------------------------------

def test_severity_cap_note_none_when_no_cap():
    assert severity_cap_note(None, "REJECT") is None
    assert severity_cap_note(None, "WATCH") is None


def test_severity_cap_note_explainability_gate_held_down_to_watch():
    note = severity_cap_note("explainability_gate", "WATCH")
    assert "unexplainable detector" in note
    assert "Isolation Forest" in note and "ECOD" in note
    assert "Module B" not in note


def test_severity_cap_note_explainability_gate_but_final_reject_via_module_b():
    """E12 step 2's non-obvious composition: Module A capped, but Module B independently
    corroborates so the fused verdict is still REJECT - the note must say the REJECT relies on
    Module B, not silently disappear just because the final verdict looks unaffected."""
    note = severity_cap_note("explainability_gate", "REJECT")
    assert "unexplainable detector" in note
    assert "Module B" in note and "REJECT" in note


def test_severity_cap_note_direction_awareness_cap():
    note = severity_cap_note("below_median_direction_cap", "WATCH")
    assert "below the lot median" in note
    assert "direction-awareness" in note


def test_severity_cap_note_unrecognized_reason_raises():
    import pytest
    with pytest.raises(ValueError):
        severity_cap_note("some_new_reason_nobody_told_this_file_about", "WATCH")
