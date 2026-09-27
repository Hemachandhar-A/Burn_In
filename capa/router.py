import csv
from io import StringIO
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from typing import List

from contracts import Account
from identity.auth import get_current_account
from capa.models import TEMP_CapaRecord, TEMP_ResolveRequest
from capa.logic import get_all_capas
from storage.repository import log_event, query_events

router = APIRouter(tags=["CAPA", "Audit"])

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
