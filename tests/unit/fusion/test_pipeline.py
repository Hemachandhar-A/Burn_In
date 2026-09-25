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
