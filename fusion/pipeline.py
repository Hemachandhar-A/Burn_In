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
        worst_parameter="iddq",
        module_a_ran=True,  # the stub stands in for both modules running
        module_b_ran=True,
        predicted_168h=None,
        actual_168h=None,
        explanation_sentence=None,
    )
    
    is_forecast = lot.status == "IN_PROGRESS"
    verdict = "LOT_ON_TRACK" if is_forecast else "ACCEPT"
    
    disposition = LotDisposition(
        lot_id=lot.lot_id,
        status=lot.status,
        pda_result=0.01,
        verdict=verdict,
        is_forecast=is_forecast
    )
    
    return AnalysisResults(
        assessments=[assessment],
        disposition=disposition
    )
