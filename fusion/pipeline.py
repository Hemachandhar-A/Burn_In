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
    
    # module_b_predict is called
    b_inputs = [to_module_b_input(frame) for frame in frames]
    b_results = module_b_predict(b_inputs) if frames else []
    
    # rank components for Module A: by combined_severity descending, component_id ascending
    a_scores = [(-r.combined_severity, r.component_id) for r in a_by_comp.values()]
    a_scores.sort()
    a_rank_map = {cid: float(rank) for rank, (_, cid) in enumerate(a_scores, start=1)}
    
    # rank components for Module B: by drift_rate / safety_slope, handling None
    # A component with no usable value ranks after every component that has one.
    # Group Module B results by component to find the max severity parameter per component.
    b_max_severity = {}
    b_worst_param = {}
    for r in b_results:
        cid = r.component_id
        if r.drift_rate is not None and r.safety_slope is not None and r.safety_slope > 0:
            severity = r.drift_rate / r.safety_slope
            if cid not in b_max_severity or severity > b_max_severity[cid]:
                b_max_severity[cid] = severity
                b_worst_param[cid] = r
                
    b_scores = []
    # Identify unique components from b_results
    b_cids = {r.component_id for r in b_results}
    for cid in b_cids:
        severity = b_max_severity.get(cid)
        if severity is not None:
            # -severity for descending, cid for ascending tie-break
            b_scores.append((-severity, cid))
        else:
            # Component has no usable value, sort it after usable ones
            b_scores.append((1e9, cid))
            
    b_scores.sort()
    b_rank_map = {cid: float(rank) for rank, (_, cid) in enumerate(b_scores, start=1)}
    
    # Update b_by_comp to match the worst parameter used for ranking
    b_by_comp = b_worst_param
    
    # Identify unique components
    component_ids = set()
    for frame in frames:
        component_ids.add(frame.component_id)
        
    assessments = []
    failures = 0
    lower_bound_failures = 0
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
            
        if is_forecast:
            if b_res and b_res.lower_bound_exceeds_safety_slope is True:
                lower_bound_failures += 1
        else:
            if verdict == "REJECT":
                lower_bound_failures += 1
            
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
            # Rank 0.0 is the "not ranked" sentinel. It may only appear with module_a_ran or module_b_ran False.
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
    
    lower_bound_pda = (lower_bound_failures / total_parts) if total_parts > 0 else 0.0
    lower_bound_pda_exceeded = lower_bound_pda >= config.pda_threshold
    
    if total_parts == 0:
        # D50: never reassure without data - a lot with nothing to assess is not "on track"/"accept"
        # by default. pda_result stays 0.0 (no failures counted, not "0% failure rate confirmed").
        lot_verdict = "LOT_AT_RISK" if is_forecast else "HOLD"
    elif is_forecast:
        if lower_bound_pda_exceeded:
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
