from contracts import LotDataset, ScreeningConfig, AnalysisResults, RiskAssessment, LotDisposition

def run_full_pipeline(lot: LotDataset, config: ScreeningConfig) -> AnalysisResults:
    """
    Callable stub of fusion.run_full_pipeline.
    Returns fixed AnalysisResults matching the frozen contract.
    """
    assessment = RiskAssessment(
        component_id="COMP-001",
        lot_id=lot.lot_id,
        verdict="PASS",
        module_a_rank=1.0,
        module_b_rank=1.0,
        worst_parameter="iddq"
    )
    
    disposition = LotDisposition(
        lot_id=lot.lot_id,
        status="COMPLETE",
        pda_result=0.01,
        verdict="ACCEPT",
        is_forecast=False
    )
    
    return AnalysisResults(
        assessments=[assessment],
        disposition=disposition
    )
