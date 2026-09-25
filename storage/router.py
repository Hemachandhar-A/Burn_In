"""Session P2.8 (IMPLEMENTATION_PLAN.md Part 10): projects, events, disposition-signoffs
read routes - backs E6's Project Browser (list of `projects`) and History screen
(`events` + `disposition_signoffs`), per essential-features.md E11 step 8.

Scoped to exactly these three read paths for this session; `project_data`/`confirmed_outcomes`
read routes (screens 3-4 reload, Part Detail's confirmed-outcome history) are a later session -
`project_data.results_json` is still a TEMP_ANALYSIS_RESULTS_DICT shape (see
storage/repository.py's module docstring) until E9/P2.7 pins the real one, so a route
returning it as `ProjectDataResponse.results: AnalysisResults` would fail validation right now.

No `Depends(get_current_account)` yet - `identity/` (P5.4) isn't merged, same interim as
ingestion/router.py. Responses are built field-by-field from the ORM rows `storage.repository`
returns, not `response_model.model_validate(row)`, because `contracts.py`'s Pydantic response
models don't declare `model_config = {"from_attributes": True}` and rule 3 forbids adding it.
"""
from fastapi import APIRouter, HTTPException

from contracts import DispositionRecord, EventResponse, ProjectSummary
from storage import repository

router = APIRouter(tags=["storage"])


def _project_summary(project) -> ProjectSummary:
    return ProjectSummary(
        project_id=project.project_id, lot_id=project.lot_id, part_number=project.part_number,
        created_at=project.created_at, created_by=project.created_by,
    )


def _event_response(event) -> EventResponse:
    return EventResponse(
        event_id=event.event_id, project_id=event.project_id, account_id=event.account_id,
        event_type=event.event_type, timestamp=event.timestamp, payload=event.payload,
    )


def _disposition_record(signoff) -> DispositionRecord:
    return DispositionRecord(
        project_id=signoff.project_id, component_id=signoff.component_id,
        account_id=signoff.account_id, verdict=signoff.verdict, rationale=signoff.rationale,
        timestamp=signoff.timestamp, analysis_run_id=signoff.analysis_run_id,
    )


def _require_project(project_id: str):
    project = repository.query_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project '{project_id}' not found")
    return project


@router.get("/projects", response_model=list[ProjectSummary])
async def list_projects() -> list[ProjectSummary]:
    return [_project_summary(p) for p in repository.query_projects()]


@router.get("/projects/{project_id}", response_model=ProjectSummary)
async def get_project(project_id: str) -> ProjectSummary:
    return _project_summary(_require_project(project_id))


@router.get("/projects/{project_id}/events", response_model=list[EventResponse])
async def get_project_events(project_id: str) -> list[EventResponse]:
    _require_project(project_id)
    return [_event_response(e) for e in repository.query_events(project_id)]


@router.get("/projects/{project_id}/disposition-signoffs", response_model=list[DispositionRecord])
async def get_disposition_signoffs(project_id: str, component_id: str | None = None) -> list[DispositionRecord]:
    _require_project(project_id)
    return [_disposition_record(s) for s in repository.query_disposition_signoffs(project_id, component_id)]
