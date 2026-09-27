from fastapi import APIRouter, HTTPException, status, Depends
from contracts import (
    LoginRequest, TokenResponse, DispositionRequest, DispositionRecord,
    SettingsResponse, SettingsProposalRequest, SettingsSignoffRequest, Account,
    PendingSettingChange, ScreeningConfig
)
from identity.auth import create_access_token, verify_pin, get_current_account
from storage.repository import (
    query_account, save_disposition_signoff, query_disposition_signoffs,
    log_event, query_events
)
from datetime import datetime, UTC
import threading

router = APIRouter(tags=["Auth", "Settings", "Disposition"])
disposition_lock = threading.Lock()
settings_lock = threading.Lock()

@router.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest):
    account = query_account(request.account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid account ID or PIN",
        )

    if not verify_pin(request.pin, account.pin_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid account ID or PIN",
        )

    token = create_access_token(account.account_id, account.role)
    return TokenResponse(
        access_token=token,
        account_id=account.account_id,
        role=account.role,
    )

@router.post("/parts/{component_id}/disposition", response_model=DispositionRecord)
def create_disposition(
    component_id: str,
    project_id: str,
    analysis_run_id: str,
    request: DispositionRequest,
    account: Account = Depends(get_current_account)
):
    with disposition_lock:
        signoffs = query_disposition_signoffs(project_id=project_id, component_id=component_id)
        
        if request.verdict == "REJECT":
            reject_signoffs = [s for s in signoffs if s.verdict == "REJECT" and s.analysis_run_id == analysis_run_id]
            if reject_signoffs:
                first_signoff = reject_signoffs[-1] # get the latest
                if first_signoff.account_id == account.account_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Dual sign-off requires two distinct account IDs, not two role labels"
                    )
                
                # Check timing flag
                if first_signoff.timestamp.tzinfo is None:
                    time_diff = (datetime.now(UTC) - first_signoff.timestamp.replace(tzinfo=UTC)).total_seconds()
                else:
                    time_diff = (datetime.now(UTC) - first_signoff.timestamp).total_seconds()
                
                if time_diff < 120:
                    # TEMP: Using config_change since disposition event type doesn't exist
                    log_event(
                        project_id=project_id,
                        account_id=account.account_id,
                        event_type="config_change",
                        payload={"timing_flag": True, "message": "Sign-offs occurred < 2 minutes apart."}
                    )

        record = save_disposition_signoff(
            project_id=project_id,
            component_id=component_id,
            analysis_run_id=analysis_run_id,
            account_id=account.account_id,
            verdict=request.verdict,
            rationale=request.rationale
        )
        
        return DispositionRecord(
            project_id=record.project_id,
            component_id=record.component_id,
            account_id=record.account_id,
            verdict=record.verdict,
            rationale=record.rationale,
            timestamp=record.timestamp,
            analysis_run_id=record.analysis_run_id
        )

def _get_current_settings_state():
    config = ScreeningConfig()
    current_values = {
        "fn_fp_cost_ratio": config.fn_fp_cost_ratio,
        "pda_threshold": config.pda_threshold,
        "confirmed_outcome_fn_ceiling": config.confirmed_outcome_fn_ceiling
    }
    pending_changes = {}
    
    # In a real app we'd query across all projects or have a global event project_id. 
    # For now, we query all events without a project_id. 
    # Wait, events require a project_id in the DB. 
    # But Settings are global. How are global config_change events logged?
    # Let's query all events for now, since it's a prototype.
    all_events = query_events()
    config_events = [e for e in all_events if e.event_type == "config_change"]
    
    for event in config_events:
        payload = event.payload
        if payload.get("action") == "propose":
            field = payload.get("field")
            pending_changes[field] = PendingSettingChange(
                field=field,
                proposed_value=payload.get("proposed_value"),
                proposed_by=event.account_id,
                signed_off_by=None
            )
        elif payload.get("action") == "signoff":
            field = payload.get("field")
            if field in pending_changes:
                pending_changes[field].signed_off_by = event.account_id
                current_values[field] = pending_changes[field].proposed_value
                del pending_changes[field]
                
    return current_values, list(pending_changes.values())

@router.get("/settings", response_model=SettingsResponse)
def get_settings(account: Account = Depends(get_current_account)):
    current_values, pending = _get_current_settings_state()
    return SettingsResponse(
        fn_fp_cost_ratio=current_values["fn_fp_cost_ratio"],
        pda_threshold=current_values["pda_threshold"],
        confirmed_outcome_fn_ceiling=current_values["confirmed_outcome_fn_ceiling"],
        pending_changes=pending
    )

@router.post("/settings/propose", response_model=PendingSettingChange)
def propose_setting(
    request: SettingsProposalRequest,
    account: Account = Depends(get_current_account)
):
    with settings_lock:
        current_values, pending = _get_current_settings_state()
        for p in pending:
            if p.field == request.field:
                raise HTTPException(status_code=400, detail="Change already pending for this field")
        
        # log_event requires project_id. We use a dummy global project ID.
        log_event(
            project_id="GLOBAL_SETTINGS",
            account_id=account.account_id,
            event_type="config_change",
            payload={
                "action": "propose",
                "field": request.field,
                "proposed_value": request.proposed_value
            }
        )
        return PendingSettingChange(
            field=request.field,
            proposed_value=request.proposed_value,
            proposed_by=account.account_id,
            signed_off_by=None
        )

@router.post("/settings/signoff", response_model=SettingsResponse)
def signoff_setting(
    request: SettingsSignoffRequest,
    account: Account = Depends(get_current_account)
):
    with settings_lock:
        current_values, pending = _get_current_settings_state()
        pending_change = next((p for p in pending if p.field == request.field), None)
        
        if not pending_change:
            raise HTTPException(status_code=400, detail="No pending change for this field")
            
        if pending_change.proposed_by == account.account_id:
            raise HTTPException(status_code=400, detail="Dual sign-off requires two distinct account IDs, not two role labels")
            
        log_event(
            project_id="GLOBAL_SETTINGS",
            account_id=account.account_id,
            event_type="config_change",
            payload={
                "action": "signoff",
                "field": request.field,
                "proposed_value": pending_change.proposed_value
            }
        )
        
        new_values, new_pending = _get_current_settings_state()
        return SettingsResponse(
            fn_fp_cost_ratio=new_values["fn_fp_cost_ratio"],
            pda_threshold=new_values["pda_threshold"],
            confirmed_outcome_fn_ceiling=new_values["confirmed_outcome_fn_ceiling"],
            pending_changes=new_pending
        )
