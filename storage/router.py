"""Session P2.8 (IMPLEMENTATION_PLAN.md Part 10): projects, events, disposition-signoffs
read routes - backs E6's Project Browser (list of `projects`) and History screen
(`events` + `disposition_signoffs`), per essential-features.md E11 step 8.

Global `GET /events` and `GET /disposition-signoffs` added per CONTRACT_CHANGES.md 2026-09-26
"Routers registered; P2.8's storage routes differ from Part 5.6" (Lead resolution: keep the
per-project routes, add the global ones alongside them - the History screen needs a single
timeline spanning multiple lots, the per-project ones don't).

`project_data`/`confirmed_outcomes` read routes (screens 3-4 reload, Part Detail's
confirmed-outcome history) are a later session - `project_data.results_json` is a pinned
(P2.7, see storage/repository.py's module docstring) but still plain-dict shape, not
`contracts.AnalysisResults`, so a route returning it as `ProjectDataResponse.results:
AnalysisResults` would still fail validation right now.

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
        manufacturer=project.manufacturer, date_code=project.date_code, test_date=project.test_date,
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


@router.get("/events", response_model=list[EventResponse])
async def get_all_events() -> list[EventResponse]:
    """Global feed across every project - History screen (E6 screen 6). CONTRACT_CHANGES.md
    2026-09-26 "Routers registered; P2.8's storage routes differ from Part 5.6" - added
    alongside the per-project route above, not instead of it."""
    return [_event_response(e) for e in repository.query_events()]


@router.get("/disposition-signoffs", response_model=list[DispositionRecord])
async def get_all_disposition_signoffs(component_id: str | None = None) -> list[DispositionRecord]:
    """Global feed across every project - History screen (E6 screen 6). Same resolution
    as get_all_events above."""
    return [_disposition_record(s) for s in repository.query_disposition_signoffs(component_id=component_id)]
