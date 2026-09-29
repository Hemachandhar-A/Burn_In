import pytest
from contracts import LotDataset, ScreeningConfig, Reading, AnalysisResults
from fusion.pipeline import run_full_pipeline

def test_run_full_pipeline_stub():
    """
    Verify that the stubbed pipeline returns valid, correctly shaped instances 
    of RiskAssessment, LotDisposition, and AnalysisResults matching contracts.py.
    """
    reading = Reading(
        component_id="COMP-001",
        lot_id="LOT-123",
        part_number="PN-ABC",
        manufacturer="MFG",
        date_code="2026",
        parameter="iddq",
        checkpoint_hour=0.0,
        value=1.5,
        unit="uA"
    )
    reading_24h = Reading(
        component_id="COMP-001",
        lot_id="LOT-123",
        part_number="PN-ABC",
        manufacturer="MFG",
        date_code="2026",
        parameter="iddq",
        checkpoint_hour=24.0,
        value=1.6,
        unit="uA"
    )
    reading_168h = Reading(
        component_id="COMP-001",
        lot_id="LOT-123",
        part_number="PN-ABC",
        manufacturer="MFG",
        date_code="2026",
        parameter="iddq",
        checkpoint_hour=168.0,
        value=2.0,
        unit="uA"
    )
    lot = LotDataset(
        lot_id="LOT-123",
        part_number="PN-ABC",
        status="COMPLETE",
        readings=[reading, reading_24h, reading_168h],
        account_id="ACC-001"
    )
    config = ScreeningConfig()
    
    result = run_full_pipeline(lot, config)
    
    # Verify shape
    assert isinstance(result, AnalysisResults)
    assert len(result.assessments) == 1
    
    assessment = result.assessments[0]
    assert assessment.component_id == "COMP-001"
    assert assessment.lot_id == "LOT-123"
    assert assessment.verdict == "PASS"
    
    disposition = result.disposition
    assert disposition.lot_id == "LOT-123"
    assert disposition.status == "COMPLETE"
    assert disposition.verdict == "ACCEPT"
    assert disposition.is_forecast is False

def test_run_full_pipeline_stub_in_progress():
    """
    Verify that an IN_PROGRESS input produces is_forecast=True and 
    forecast-vocabulary verdict.
    """
    reading = Reading(
        component_id="COMP-001",
        lot_id="LOT-456",
        part_number="PN-DEF",
        manufacturer="MFG",
        date_code="2026",
        parameter="iddq",
        checkpoint_hour=0.0,
        value=1.5,
        unit="uA"
    )
    reading_24h = Reading(
        component_id="COMP-001",
        lot_id="LOT-456",
        part_number="PN-DEF",
        manufacturer="MFG",
        date_code="2026",
        parameter="iddq",
        checkpoint_hour=24.0,
        value=1.6,
        unit="uA"
    )
    lot = LotDataset(
        lot_id="LOT-456",
        part_number="PN-DEF",
        status="IN_PROGRESS",
        readings=[reading, reading_24h],
        account_id="ACC-001"
    )
    config = ScreeningConfig()
    
    result = run_full_pipeline(lot, config)
    
    disposition = result.disposition
    assert disposition.status == "IN_PROGRESS"
    assert disposition.is_forecast is True
    assert disposition.verdict == "LOT_ON_TRACK"  # Forecast vocabulary


def test_run_full_pipeline_stub_edge_cases():
    """
    Test edge cases for the pipeline stub to ensure it handles 
    empty readings and special characters in lot_id safely.
    """
    # Edge case 1: Empty readings and special characters in lot_id
    lot_empty = LotDataset(
        lot_id="LOT!@#-$%^&*(",
        part_number="PN-EDGE",
        status="IN_PROGRESS",
        readings=[],
        account_id="ACC-002"
    )
    config = ScreeningConfig()
    
    result_empty = run_full_pipeline(lot_empty, config)
    assert len(result_empty.assessments) == 0
    assert result_empty.disposition.lot_id == "LOT!@#-$%^&*("
    assert result_empty.disposition.lot_id == "LOT!@#-$%^&*("
    
    # Edge case 2: Empty lot_id string
    lot_no_id = LotDataset(
        lot_id="",
        part_number="PN-EDGE",
        status="COMPLETE",
        readings=[],
        account_id="ACC-002"
    )
    result_no_id = run_full_pipeline(lot_no_id, config)
    assert len(result_no_id.assessments) == 0
    assert result_no_id.disposition.lot_id == ""
    assert result_no_id.disposition.lot_id == ""

from unittest.mock import patch
from contracts import ModuleBResult

@patch('fusion.pipeline.module_b_predict')
def test_stop_run_recommended_lower_bound(mock_predict):
    from contracts import LotDataset, Reading, ScreeningConfig
    # We will test 3 conditions: (a) lower bound exceeds, (b) point exceeds but not lower bound, (c) all None
    lot = LotDataset(
        lot_id="LOT-FRC",
        part_number="PN-ABC",
        status="IN_PROGRESS",
        readings=[
            Reading(component_id="C1", lot_id="LOT-FRC", part_number="PN-ABC", manufacturer="M", date_code="D", parameter="p", checkpoint_hour=0.0, value=1.0, unit="uA"),
            Reading(component_id="C1", lot_id="LOT-FRC", part_number="PN-ABC", manufacturer="M", date_code="D", parameter="p", checkpoint_hour=24.0, value=1.5, unit="uA"),
        ],
        account_id="ACC-001"
    )
    config = ScreeningConfig(pda_threshold=0.5)

    # (a) lower bound exceeds
    mock_predict.return_value = [
        ModuleBResult(component_id="C1", lot_id="LOT-FRC", parameter="p", drift_rate=2.0, exceeds_safety_slope=True, safety_slope=1.0, lower_bound_exceeds_safety_slope=True, predicted_168h=5.0, interval_lower=4.0, interval_upper=6.0, physics_baseline_prediction=1.0, physics_disagreement_gap=0.0, forecast_unavailable=False)
    ]
    res_a = run_full_pipeline(lot, config)
    assert res_a.disposition.verdict == "STOP_RUN_RECOMMENDED"

    # (b) point exceeds but not lower bound -> LOT_AT_RISK
    mock_predict.return_value = [
        ModuleBResult(component_id="C1", lot_id="LOT-FRC", parameter="p", drift_rate=2.0, exceeds_safety_slope=True, safety_slope=1.0, lower_bound_exceeds_safety_slope=False, predicted_168h=5.0, interval_lower=4.0, interval_upper=6.0, physics_baseline_prediction=1.0, physics_disagreement_gap=0.0, forecast_unavailable=False)
    ]
    res_b = run_full_pipeline(lot, config)
    assert res_b.disposition.verdict == "LOT_AT_RISK"

    # (c) all None -> LOT_ON_TRACK
    mock_predict.return_value = [
        ModuleBResult(component_id="C1", lot_id="LOT-FRC", parameter="p", drift_rate=None, exceeds_safety_slope=None, safety_slope=None, lower_bound_exceeds_safety_slope=None, predicted_168h=None, interval_lower=None, interval_upper=None, physics_baseline_prediction=None, physics_disagreement_gap=None, forecast_unavailable=True)
    ]
    res_c = run_full_pipeline(lot, config)
    assert res_c.disposition.verdict == "LOT_ON_TRACK"

@patch('fusion.pipeline.module_b_predict')
@patch('fusion.pipeline.module_a_detect')
def test_rankings(mock_a, mock_b):
    from contracts import LotDataset, Reading, ScreeningConfig, ModuleAResult, ModuleBResult
    from fusion.pipeline import run_full_pipeline
    
    # 3 components, 3 parameters = 9 readings (0h and 24h)
    readings = []
    for c in ['C1', 'C2', 'C3']:
        for p in ['iddq', 'leakage', 'prop_delay']:
            readings.append(Reading(component_id=c, lot_id='LOT1', part_number='PN1', manufacturer='M', date_code='D', parameter=p, checkpoint_hour=0.0, value=1.0, unit='u'))
            readings.append(Reading(component_id=c, lot_id='LOT1', part_number='PN1', manufacturer='M', date_code='D', parameter=p, checkpoint_hour=24.0, value=2.0, unit='u'))
            
    lot = LotDataset(lot_id='LOT1', part_number='PN1', status='COMPLETE', readings=readings, account_id='ACC')
    config = ScreeningConfig()
    
    # Module A: C2 is worst (0.9), C1 is 0.8, C3 is 0.8. Ties broken by ID: C1 > C3?
    # Wait, 'Rank 1 = most severe. Ties are broken by component_id ascending.'
    # So C2=1, C1=2, C3=3.
    mock_a.return_value = [
        ModuleAResult(component_id='C1', lot_id='LOT1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='PASS', severity_cap_reason=None, combined_severity=0.8, explainable_corroboration=False),
        ModuleAResult(component_id='C2', lot_id='LOT1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='PASS', severity_cap_reason=None, combined_severity=0.9, explainable_corroboration=False),
        ModuleAResult(component_id='C3', lot_id='LOT1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='PASS', severity_cap_reason=None, combined_severity=0.8, explainable_corroboration=False),
    ]
    
    # Module B: C3 is worst (drift_rate/safety_slope = 3.0), C1 is 2.0, C2 has None.
    # C2 should rank 3.
    mock_b.return_value = [
        ModuleBResult(component_id='C1', lot_id='LOT1', parameter='iddq', drift_rate=2.0, safety_slope=1.0, exceeds_safety_slope=True, lower_bound_exceeds_safety_slope=False, predicted_168h=0, interval_lower=0, interval_upper=0, physics_baseline_prediction=0, physics_disagreement_gap=0, forecast_unavailable=False),
        ModuleBResult(component_id='C2', lot_id='LOT1', parameter='iddq', drift_rate=None, safety_slope=None, exceeds_safety_slope=None, lower_bound_exceeds_safety_slope=None, predicted_168h=0, interval_lower=0, interval_upper=0, physics_baseline_prediction=0, physics_disagreement_gap=0, forecast_unavailable=True),
        ModuleBResult(component_id='C3', lot_id='LOT1', parameter='iddq', drift_rate=6.0, safety_slope=2.0, exceeds_safety_slope=True, lower_bound_exceeds_safety_slope=False, predicted_168h=0, interval_lower=0, interval_upper=0, physics_baseline_prediction=0, physics_disagreement_gap=0, forecast_unavailable=False),
    ]
    
    res = run_full_pipeline(lot, config)
    
    # Check Module A
    a_ranks = {a.component_id: a.module_a_rank for a in res.assessments}
    assert a_ranks['C2'] == 1.0
    assert a_ranks['C1'] == 2.0
    assert a_ranks['C3'] == 3.0
    
    # Check Module B
    b_ranks = {a.component_id: a.module_b_rank for a in res.assessments}
    assert b_ranks['C3'] == 1.0
    assert b_ranks['C1'] == 2.0
    assert b_ranks['C2'] == 3.0
