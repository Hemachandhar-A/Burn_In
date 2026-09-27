"""Session P5.3: fusion/router.py - Lot Dashboard live computation."""
import json
from fastapi import APIRouter, HTTPException

from contracts import LotSummaryResponse, LotDataset, ScreeningConfig, RiskAssessment, LotDisposition
from storage.repository import query_projects, query_latest_project_data

router = APIRouter(tags=["fusion"])

@router.get("/lots/{lot_id}", response_model=LotSummaryResponse)
def get_lot_summary(lot_id: str) -> LotSummaryResponse:
    matches = [p for p in query_projects() if p.lot_id == lot_id]
    if not matches:
        raise HTTPException(status_code=404, detail=f"no project found for lot '{lot_id}'")
    project = matches[0]
    
    latest_data = query_latest_project_data(project.project_id)
    if not latest_data:
        raise HTTPException(status_code=404, detail=f"No analysis run found for lot {lot_id}")
        
    results_dict = json.loads(latest_data.results_json)
    
    assessments = []
    for comp_id, data in results_dict.get("per_component", {}).items():
        assessments.append(RiskAssessment(
            component_id=comp_id,
            lot_id=lot_id,
            verdict=data.get("verdict"),
            module_a_rank=0.0,
            module_b_rank=0.0,
            worst_parameter="unknown",
            module_a_ran=data.get("module_a_ran", False),
            module_b_ran=data.get("module_b_ran", False),
            predicted_168h=data.get("predicted_168h"),
            actual_168h=data.get("actual_168h"),
            explanation_sentence=data.get("explanation_sentence")
        ))
        
    disp_dict = results_dict.get("lot_disposition") or {}
    disposition = LotDisposition(
        lot_id=lot_id,
        status=disp_dict.get("status", "IN_PROGRESS"),
        pda_result=disp_dict.get("pda_result", 0.0),
        verdict=disp_dict.get("verdict", "LOT_ON_TRACK"),
        is_forecast=disp_dict.get("is_forecast", True)
    )
    
    return LotSummaryResponse(
        assessments=assessments,
        disposition=disposition
    )
