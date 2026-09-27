import pytest
from contracts import ModuleAResult, ModuleBResult
from fusion.gate import compute_part_verdict

def test_explainability_gate_caps_unexplainable_reject():
    a_result = ModuleAResult(
        component_id="C1",
        lot_id="L1",
        parameter="iddq",
        robust_z=2.0,
        mcd_distance=None,
        isolation_forest_score=None,
        ecod_score=0.0,
        explainable_tags={"robust_z": True, "mcd": False, "isolation_forest": False, "ecod": False},
        direction="above_median",
        severity_tier="REJECT",
        severity_cap_reason=None,
        combined_severity=1.0,
        explainable_corroboration=False
    )
    b_result = ModuleBResult(
        component_id="C1",
        lot_id="L1",
        parameter="iddq",
        predicted_168h=None,
        interval_lower=None,
        interval_upper=None,
        physics_baseline_prediction=None,
        physics_disagreement_gap=None,
        drift_rate=None,
        exceeds_safety_slope=False, # B is PASS
        safety_slope=None,
        forecast_unavailable=False
    )
    verdict, cap_reason, a_tier = compute_part_verdict(a_result, b_result)
    assert a_tier == "REVIEW"
    assert cap_reason == "explainability_gate"
    assert verdict == "WATCH" # exactly one module past REVIEW -> WATCH

def test_composability_gate_b_reject_overrides_a_cap():
    a_result = ModuleAResult(
        component_id="C1",
        lot_id="L1",
        parameter="iddq",
        robust_z=2.0,
        mcd_distance=None,
        isolation_forest_score=None,
        ecod_score=0.0,
        explainable_tags={"robust_z": True, "mcd": False, "isolation_forest": False, "ecod": False},
        direction="above_median",
        severity_tier="REJECT",
        severity_cap_reason=None,
        combined_severity=1.0,
        explainable_corroboration=False
    )
    b_result = ModuleBResult(
        component_id="C1",
        lot_id="L1",
        parameter="iddq",
        predicted_168h=None,
        interval_lower=None,
        interval_upper=None,
        physics_baseline_prediction=None,
        physics_disagreement_gap=None,
        drift_rate=None,
        exceeds_safety_slope=True, # B is REJECT
        safety_slope=None,
        forecast_unavailable=False
    )
    verdict, cap_reason, a_tier = compute_part_verdict(a_result, b_result)
    assert a_tier == "REVIEW"
    assert cap_reason == "explainability_gate"
    assert verdict == "REJECT" # either module past REJECT (B is REJECT) -> REJECT

def test_direction_awareness_cap_preserved():
    # If Module A already capped it, fusion table uses the capped tier
    a_result = ModuleAResult(
        component_id="C1",
        lot_id="L1",
        parameter="iddq",
        robust_z=2.0,
        mcd_distance=None,
        isolation_forest_score=None,
        ecod_score=0.0,
        explainable_tags={"robust_z": True, "mcd": False, "isolation_forest": False, "ecod": False},
        direction="below_median",
        severity_tier="REVIEW",
        severity_cap_reason="below_median_direction_cap",
        combined_severity=1.0,
        explainable_corroboration=True
    )
    b_result = ModuleBResult(
        component_id="C1",
        lot_id="L1",
        parameter="iddq",
        predicted_168h=None,
        interval_lower=None,
        interval_upper=None,
        physics_baseline_prediction=None,
        physics_disagreement_gap=None,
        drift_rate=None,
        exceeds_safety_slope=False,
        safety_slope=None,
        forecast_unavailable=False
    )
    verdict, cap_reason, a_tier = compute_part_verdict(a_result, b_result)
    assert a_tier == "REVIEW"
    assert cap_reason == "below_median_direction_cap"
    assert verdict == "WATCH"

def test_both_pass():
    a_result = ModuleAResult(
        component_id="C1",
        lot_id="L1",
        parameter="iddq",
        robust_z=2.0,
        mcd_distance=None,
        isolation_forest_score=None,
        ecod_score=0.0,
        explainable_tags={"robust_z": True, "mcd": False, "isolation_forest": False, "ecod": False},
        direction="above_median",
        severity_tier="PASS",
        severity_cap_reason=None,
        combined_severity=0.5,
        explainable_corroboration=True
    )
    b_result = ModuleBResult(
        component_id="C1",
        lot_id="L1",
        parameter="iddq",
        predicted_168h=None,
        interval_lower=None,
        interval_upper=None,
        physics_baseline_prediction=None,
        physics_disagreement_gap=None,
        drift_rate=None,
        exceeds_safety_slope=False,
        safety_slope=None,
        forecast_unavailable=False
    )
    verdict, cap_reason, a_tier = compute_part_verdict(a_result, b_result)
    assert a_tier == "PASS"
    assert cap_reason is None
    assert verdict == "PASS"
