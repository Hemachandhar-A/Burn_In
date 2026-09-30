"""Block 3B Part 2b: contracts.py's additive PartExplanation/AnalysisResults/PartDetailResponse
fields (explain/models.py's own local models are covered by test_shap_b.py, test_mcd.py,
test_zscore.py, test_ecod.py - these are the *contracts.py* API-facing row types Part 2a adds).
Every addition here has a default, so an old stored row (pre-Block-3B) must still parse, and every
new model must round-trip through model_dump_json/model_validate_json."""
import json

from contracts import (
    AnalysisResults, ConfirmedOutcomeRecord, DispositionRecord, EcodDimensionRow,
    LotDisposition, MCDContributionRow, ModuleAResult, ModuleBResult, PartDetailResponse,
    PartExplanation, RiskAssessment, ShapContributionRow, ZScoreTableRow,
)


def _module_a_result(component_id="C1", lot_id="L1", parameter="leakage"):
    return ModuleAResult(
        component_id=component_id, lot_id=lot_id, parameter=parameter, robust_z=1.0,
        mcd_distance=None, isolation_forest_score=None, ecod_score=0.5,
        explainable_tags={"robust_z": True, "mcd": False, "isolation_forest": False, "ecod": False},
        direction="above_median", severity_tier="REJECT", severity_cap_reason=None,
        combined_severity=0.9, explainable_corroboration=True,
    )


def _module_b_result(component_id="C1", lot_id="L1", parameter="leakage"):
    return ModuleBResult(
        component_id=component_id, lot_id=lot_id, parameter=parameter, predicted_168h=50.0,
        interval_lower=45.0, interval_upper=55.0, physics_baseline_prediction=48.0,
        physics_disagreement_gap=2.0, drift_rate=1.0, exceeds_safety_slope=True, safety_slope=0.5,
        lower_bound_exceeds_safety_slope=True, forecast_unavailable=False,
    )


def _risk_assessment(component_id="C1", lot_id="L1"):
    return RiskAssessment(
        component_id=component_id, lot_id=lot_id, verdict="REJECT", module_a_rank=1.0,
        module_b_rank=1.0, worst_parameter="leakage", module_a_ran=True, module_b_ran=True,
        predicted_168h=50.0, actual_168h=None, explanation_sentence=None,
    )


def _lot_disposition(lot_id="L1"):
    return LotDisposition(lot_id=lot_id, status="COMPLETE", pda_result=0.1, verdict="HOLD", is_forecast=False)


def test_old_analysis_results_json_without_new_fields_parses():
    """A results_json row stored before Block 3B (no part_explanations/explanation_summary keys)
    must still parse - both are additive with defaults."""
    old_shape = {
        "assessments": [_risk_assessment().model_dump(mode="json")],
        "disposition": _lot_disposition().model_dump(mode="json"),
    }
    parsed = AnalysisResults.model_validate_json(json.dumps(old_shape))
    assert parsed.part_explanations == {}
    assert parsed.explanation_summary == ""
    assert parsed.insufficient_data_components == []


def test_analysis_results_with_part_explanations_round_trips():
    explanation = PartExplanation(
        shap_contributions=[ShapContributionRow(feature="delta_24h", value=1.5, shap_value=0.8)],
        mcd_contributions=[MCDContributionRow(parameter="leakage", contribution=3.2)],
        ecod_dimensions=[EcodDimensionRow(dimension="value_24h", score=0.4)],
        zscore_table=[ZScoreTableRow(parameter="leakage", value=45.0, lot_median=10.0, z=4.2)],
        explanation_sentence="Part C1: leakage at 24h is 4.2 robust-sigma above lot median.",
        confidence_qualifier="high confidence",
        severity_cap_note=None,
        unavailable_forecast_note=None,
    )
    results = AnalysisResults(
        assessments=[_risk_assessment()],
        disposition=_lot_disposition(),
        part_explanations={"C1": explanation},
        explanation_summary="1 of 1 parts flagged, concentrated in leakage current.",
    )
    round_tripped = AnalysisResults.model_validate_json(results.model_dump_json())
    assert round_tripped == results
    assert round_tripped.part_explanations["C1"].mcd_contributions[0].parameter == "leakage"


def test_old_part_detail_response_json_without_explanation_field_parses():
    old_shape = {
        "module_a": _module_a_result().model_dump(mode="json"),
        "module_b": _module_b_result().model_dump(mode="json"),
        "explanation_sentence": "within normal range",
        "confidence_qualifier": "high confidence",
        "severity_cap_note": None,
        "unavailable_forecast_note": None,
        "staleness_note": None,
        "disposition_history": [],
        "confirmed_outcomes": [],
    }
    parsed = PartDetailResponse.model_validate_json(json.dumps(old_shape))
    assert parsed.explanation is None


def test_part_detail_response_with_explanation_round_trips():
    explanation = PartExplanation(
        explanation_sentence="Part C1: leakage at 24h is 4.2 robust-sigma above lot median.",
        confidence_qualifier="high confidence",
    )
    detail = PartDetailResponse(
        module_a=_module_a_result(), module_b=_module_b_result(),
        explanation_sentence="Part C1: leakage at 24h is 4.2 robust-sigma above lot median.",
        confidence_qualifier="high confidence", severity_cap_note=None,
        unavailable_forecast_note=None, staleness_note=None,
        disposition_history=[], confirmed_outcomes=[], explanation=explanation,
    )
    round_tripped = PartDetailResponse.model_validate_json(detail.model_dump_json())
    assert round_tripped == detail
    assert round_tripped.explanation.confidence_qualifier == "high confidence"
