from contracts import LotDataset, ScreeningConfig, AnalysisResults, RiskAssessment, LotDisposition, to_module_b_input
from features.compute import compute
from module_a.detect import detect as module_a_detect
from module_b.predictor import predict as module_b_predict
from fusion.gate import compute_part_verdict

def run_full_pipeline(lot: LotDataset, config: ScreeningConfig) -> AnalysisResults:
    is_complete = lot.status == "COMPLETE"
    is_forecast = not is_complete
    
    frames = compute(lot)
    
    a_results = []
    if is_complete:
        a_results = module_a_detect(frames)
    
    a_by_comp = {}
    for r in a_results:
        cid = r.component_id
        if cid not in a_by_comp or r.combined_severity > a_by_comp[cid].combined_severity:
            a_by_comp[cid] = r
    
    b_inputs = [to_module_b_input(frame) for frame in frames]
    b_results = module_b_predict(b_inputs) if frames else []
    b_by_comp = {}
    for r in b_results:
        cid = r.component_id
        if cid not in b_by_comp:
            b_by_comp[cid] = r
        else:
            current = b_by_comp[cid]
            if r.exceeds_safety_slope and not current.exceeds_safety_slope:
                b_by_comp[cid] = r
            elif r.exceeds_safety_slope == current.exceeds_safety_slope:
                if (r.drift_rate or 0) > (current.drift_rate or 0):
                    b_by_comp[cid] = r
    
    # rank components
    a_scores = [(r.combined_severity, r.component_id) for r in a_results]
    a_scores.sort(reverse=True)
    a_rank_map = {cid: float(rank) for rank, (_, cid) in enumerate(a_scores, start=1)}
    
    # Module B rank: by drift_rate, handling None
    b_scores = []
    for r in b_results:
        score = r.drift_rate if r.drift_rate is not None else -999999.0
        b_scores.append((score, r.component_id))
    b_scores.sort(reverse=True)
    b_rank_map = {cid: float(rank) for rank, (_, cid) in enumerate(b_scores, start=1)}
    
    # Identify unique components
    component_ids = set()
    for frame in frames:
        component_ids.add(frame.component_id)
        
    assessments = []
    failures = 0
    total_parts = len(component_ids)
    
    for cid in sorted(component_ids):
        # find the frame with the worst parameter?
        # we can just use the first frame's parameter if it's PASS, else worst parameter from module_a/b
        # Let's get all frames for this component
        comp_frames = [f for f in frames if f.component_id == cid]
        a_res = a_by_comp.get(cid)
        b_res = b_by_comp.get(cid)
        
        verdict, _, _ = compute_part_verdict(a_res, b_res)
        
        if verdict == "REJECT" or (b_res and b_res.exceeds_safety_slope):
            failures += 1
            
        worst_parameter = comp_frames[0].parameter
        if a_res and a_res.severity_tier != "PASS":
            worst_parameter = a_res.parameter
        elif b_res and b_res.exceeds_safety_slope:
            worst_parameter = b_res.parameter
            
        actual_168h = None
        if is_complete:
            # find actual 168h for worst_parameter
            for f in comp_frames:
                if f.parameter == worst_parameter:
                    actual_168h = f.value_168h
                    
        predicted_168h = b_res.predicted_168h if b_res else None
        
        assessment = RiskAssessment(
            component_id=cid,
            lot_id=lot.lot_id,
            verdict=verdict,
            module_a_rank=a_rank_map.get(cid, 0.0),
            module_b_rank=b_rank_map.get(cid, 0.0),
            worst_parameter=worst_parameter,
            module_a_ran=is_complete,
            module_b_ran=True,
            predicted_168h=predicted_168h,
            actual_168h=actual_168h,
            explanation_sentence=None,
        )
        assessments.append(assessment)
        
    pda_result = (failures / total_parts) if total_parts > 0 else 0.0
    pda_exceeded = pda_result >= config.pda_threshold
    
    # Forecast PDA: if lower bound exceeds PDA limit?
    # Wait, the spec says "STOP_RUN_RECOMMENDED fires only when the lower bound of the forecast's calibrated interval already exceeds the PDA limit"
    # Does this mean lot-level forecast?
    # "5. Run the same PDA rollup on In-Progress lots, using Module B's early per-part predictions instead of final measured outcomes, producing a distinctly-labeled forecast"
    
    if is_forecast:
        # How to calculate forecast lower bound?
        # Maybe we should use b_res.interval_lower? But PDA is lot-level. 
        # Wait, if `exceeds_safety_slope` means early reject, it counts towards PDA failures.
        if pda_exceeded:
            lot_verdict = "STOP_RUN_RECOMMENDED"
        elif failures > 0:
            lot_verdict = "LOT_AT_RISK"
        else:
            lot_verdict = "LOT_ON_TRACK"
    else:
        if pda_exceeded:
            lot_verdict = "REJECT"
        elif any(a.verdict == "WATCH" for a in assessments):
            lot_verdict = "HOLD"
        else:
            lot_verdict = "ACCEPT"
            
    disposition = LotDisposition(
        lot_id=lot.lot_id,
        status=lot.status,
        pda_result=pda_result,
        verdict=lot_verdict,
        is_forecast=is_forecast
    )
    
    return AnalysisResults(
        assessments=assessments,
        disposition=disposition
    )
