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
        checkpoint_hour=24.0,
        value=1.5,
        unit="uA"
    )
    lot = LotDataset(
        lot_id="LOT-123",
        part_number="PN-ABC",
        status="COMPLETE",
        readings=[reading],
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
    assert result_empty.assessments[0].lot_id == "LOT!@#-$%^&*("
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
    assert result_no_id.assessments[0].lot_id == ""
    assert result_no_id.disposition.lot_id == ""
