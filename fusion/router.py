"""Session P5.3: fusion/router.py - Lot Dashboard live computation."""
import json
from fastapi import APIRouter, HTTPException

from contracts import LotSummaryResponse, LotDataset, ScreeningConfig
from storage.repository import query_projects, query_latest_project_data
from fusion.pipeline import run_full_pipeline

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
        
    raw_data = json.loads(latest_data.raw_data)
    dataset = LotDataset.model_validate(raw_data)
    
    results = run_full_pipeline(dataset, ScreeningConfig())
    return LotSummaryResponse(
        assessments=results.assessments,
        disposition=results.disposition
    )
