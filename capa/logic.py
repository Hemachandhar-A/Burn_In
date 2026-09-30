import uuid
from datetime import UTC, datetime
from capa.models import TEMP_CapaRecord
from storage.repository import query_events, log_event, query_disposition_signoffs

def evaluate_capa_trigger(project_id: str):
    # Check how many REJECT verdicts exist for this lot/project
    signoffs = query_disposition_signoffs(project_id=project_id)
    rejects = [s for s in signoffs if s.verdict == "REJECT"]
    
    # Threshold default is 3
    if len(rejects) >= 3:
        # Check if CAPA already opened for this project to prevent duplicates
        events = query_events(project_id=project_id)
        already_triggered = any(
            e.event_type == "config_change" and e.payload.get("capa_action") == "trigger"
            for e in events
        )
        if not already_triggered:
            # Trigger CAPA
            log_event(
                project_id=project_id,
                account_id="SYSTEM",  # SYSTEM user
                event_type="config_change",
                payload={
                    "capa_action": "trigger",
                    "capa_id": f"capa-{uuid.uuid4().hex[:12]}",
                    "trigger_reason": f"Lot reject count {len(rejects)} crossed threshold 3",
                    "status": "OPEN",
                    "owner_account_id": None
                }
            )

def get_all_capas() -> list[TEMP_CapaRecord]:
    events = query_events()
    
    capas = {}
    
    # Reconstruct state from events
    for e in events:
        if e.event_type == "config_change" and "capa_action" in e.payload:
            payload = e.payload
            capa_id = payload.get("capa_id")
            
            if payload["capa_action"] == "trigger":
                capas[capa_id] = TEMP_CapaRecord(
                    id=capa_id,
                    project_id=e.project_id,
                    trigger_reason=payload.get("trigger_reason", ""),
                    status="OPEN",
                    owner_account_id=payload.get("owner_account_id"),
                    created_at=e.timestamp.replace(tzinfo=UTC) if e.timestamp.tzinfo is None else e.timestamp,
                    resolved_at=None
                )
            elif payload["capa_action"] == "resolve" and capa_id in capas:
                capas[capa_id].status = "RESOLVED"
                capas[capa_id].resolved_at = e.timestamp.replace(tzinfo=UTC) if e.timestamp.tzinfo is None else e.timestamp
                
    return list(capas.values())
