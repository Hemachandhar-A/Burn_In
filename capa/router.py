import csv
from io import StringIO
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from typing import List

from contracts import (
    Account, ConfirmedOutcomeRecord, ConfirmedOutcomeRequest, CorrectiveStatusResponse, ScreeningConfig,
)
from identity.auth import get_current_account
from identity.router import get_current_settings_state
from capa.models import TEMP_CapaRecord, TEMP_ResolveRequest
from capa.logic import compute_corrective_status, find_latest_run_for_component, get_all_capas
from storage.repository import log_event, query_events, save_confirmed_outcome

router = APIRouter(tags=["CAPA", "Audit"])

# Block 4a: the four E13 routes IMPLEMENTATION_PLAN.md Part 5.6's route table actually names for
# capa/router.py. Kept on a separate router object from `router` above (which carries this file's
# three pre-existing, unplanned TEMP_ routes - GET /capa, POST /capa/{id}/resolve, GET /audit/export -
# never in the plan's route table) so api/main.py can register only what the plan specifies, per this
# session's Part 6a, without touching the TEMP_ routes' own existing tests (tests/unit/capa/test_capa.py
# imports `router` directly and still exercises them).
planned_router = APIRouter(tags=["CAPA"])


@planned_router.post("/parts/{component_id}/confirmed-outcome", response_model=ConfirmedOutcomeRecord)
def create_confirmed_outcome(
    component_id: str,
    request: ConfirmedOutcomeRequest,
    lot_id: str | None = None,
    account: Account = Depends(get_current_account),
) -> ConfirmedOutcomeRecord:
    """E13 step 1: records a confirmed real-world outcome for a part, linked to the analysis_run_id
    of the latest stored run containing it (never the disposition itself - this measures whether the
    model's verdict tier was right, a different question from whether the human's disposition was).
    Append-only: never touches disposition_signoffs. No event is logged - see CONTRACT_CHANGES.md,
    this block: none of the five event_type literal values fits this action, and AGENTS.md rule 3
    forbids inventing a new one here."""
    match = find_latest_run_for_component(component_id, lot_id)
    if match is None:
        detail = f"component '{component_id}' not found"
        if lot_id is not None:
            detail += f" in lot '{lot_id}'"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    project, row, _results = match

    outcome = save_confirmed_outcome(
        project_id=project.project_id,
        component_id=component_id,
        analysis_run_id=row.analysis_run_id,
        account_id=account.account_id,
        confirmed_outcome=request.confirmed_outcome,
        note=request.note,
    )
    return ConfirmedOutcomeRecord(
        project_id=outcome.project_id,
        component_id=outcome.component_id,
        account_id=outcome.account_id,
        confirmed_outcome=outcome.confirmed_outcome,
        note=outcome.note,
        recorded_at=outcome.recorded_at,
        analysis_run_id=outcome.analysis_run_id,
    )


@planned_router.get("/settings/corrective-status", response_model=CorrectiveStatusResponse)
def get_corrective_status(account: Account = Depends(get_current_account)) -> CorrectiveStatusResponse:
    """E13 steps 6-8: live-computed on every call, nothing stored, nothing to dismiss. The ceiling
    read here is the live Settings value (post dual sign-off), via identity.router's own state
    function - never re-derived from raw events a second time."""
    current_values, _pending = get_current_settings_state()
    config = ScreeningConfig()
    return compute_corrective_status(
        ceiling=current_values["confirmed_outcome_fn_ceiling"],
        min_confirmed_outcomes=config.min_confirmed_outcomes_for_ceiling,
    )

@router.get("/capa", response_model=List[TEMP_CapaRecord])
def list_capas(account: Account = Depends(get_current_account)):
    return get_all_capas()

@router.post("/capa/{id}/resolve", response_model=TEMP_CapaRecord)
def resolve_capa(
    id: str,
    request: TEMP_ResolveRequest,
    account: Account = Depends(get_current_account)
):
    capas = get_all_capas()
    capa = next((c for c in capas if c.id == id), None)
    if not capa:
        raise HTTPException(status_code=404, detail="CAPA not found")
        
    if capa.status == "RESOLVED":
        raise HTTPException(status_code=400, detail="CAPA already resolved")
        
    log_event(
        project_id=capa.project_id,
        account_id=account.account_id,
        event_type="config_change",
        payload={
            "capa_action": "resolve",
            "capa_id": capa.id,
            "rationale": request.rationale
        }
    )
    
    # Reload state
    capas_reloaded = get_all_capas()
    updated_capa = next((c for c in capas_reloaded if c.id == id), None)
    return updated_capa

@router.get("/audit/export", response_class=PlainTextResponse)
def export_audit_log(account: Account = Depends(get_current_account)):
    events = query_events()
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["event_id", "project_id", "account_id", "event_type", "timestamp", "payload"])
    
    for e in events:
        writer.writerow([
            e.event_id,
            e.project_id,
            e.account_id,
            e.event_type,
            e.timestamp.isoformat(),
            str(e.payload)
        ])
        
    return output.getvalue()
