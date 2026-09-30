import uuid
from datetime import UTC, datetime
from typing import Literal, NamedTuple

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

# ---------------------------------------------------------------------------
# E13 step 2/3 (Block 4a Part 2, Lead ruling D70.2) - the confirmed-outcome vs. verdict-tier match
# definition and FN/FP rate computation. Pure - no I/O - so it is trivially unit-testable and reusable
# by both GET /settings/corrective-status (Part 3) and any future consumer, without re-deriving the
# match table. Two separate rates, never a blended accuracy (E13 step 3 / context.md's own citation of
# E5's harness discipline: a blended score can hide a bad FN rate behind a good FP rate).
# ---------------------------------------------------------------------------

MatchOutcome = Literal["miss", "caught", "false_alarm", "fine", "excluded"]
_CONFIRMED_OUTCOME_VALUES = {"Confirmed Good", "Confirmed Defective", "Unknown"}
_VERDICT_VALUES = {"PASS", "WATCH", "REJECT"}


def classify_confirmed_outcome_match(confirmed_outcome: str, verdict: str) -> MatchOutcome:
    """One cell of the 3x3 (confirmed_outcome x verdict) match table, per E13 step 2:
    Confirmed Defective + PASS = miss; + WATCH/REJECT = caught.
    Confirmed Good + REJECT = false_alarm; + PASS/WATCH = fine.
    Unknown + anything = excluded (never counted in either rate or the minimum count, E13 step 6)."""
    if confirmed_outcome not in _CONFIRMED_OUTCOME_VALUES:
        raise ValueError(f"Unrecognized confirmed_outcome {confirmed_outcome!r}; must be one of "
                         f"{sorted(_CONFIRMED_OUTCOME_VALUES)}")
    if verdict not in _VERDICT_VALUES:
        raise ValueError(f"Unrecognized verdict {verdict!r}; must be one of {sorted(_VERDICT_VALUES)}")

    if confirmed_outcome == "Unknown":
        return "excluded"
    if confirmed_outcome == "Confirmed Defective":
        return "miss" if verdict == "PASS" else "caught"
    return "false_alarm" if verdict == "REJECT" else "fine"  # Confirmed Good


class MatchRates(NamedTuple):
    fn_rate: float | None  # misses / confirmed-defective; None if that denominator is 0
    fp_rate: float | None  # false_alarms / confirmed-good; None if that denominator is 0
    confirmed_defective_count: int  # Confirmed Defective outcomes (miss + caught), Unknown excluded
    confirmed_good_count: int  # Confirmed Good outcomes (false_alarm + fine), Unknown excluded
    miss_count: int
    caught_count: int
    false_alarm_count: int
    fine_count: int


def compute_match_rates(pairs: list[tuple[str, str]]) -> MatchRates:
    """pairs: (confirmed_outcome, verdict) for every confirmed outcome to score. FN/FP rates are
    computed independently - never blended - and division by zero returns None, not 0 (AGENTS.md
    rule 7: a rate that cannot be computed is not the same fact as a rate of zero)."""
    classifications = [classify_confirmed_outcome_match(co, v) for co, v in pairs]
    miss = classifications.count("miss")
    caught = classifications.count("caught")
    false_alarm = classifications.count("false_alarm")
    fine = classifications.count("fine")
    defective_total = miss + caught
    good_total = false_alarm + fine
    return MatchRates(
        fn_rate=(miss / defective_total) if defective_total else None,
        fp_rate=(false_alarm / good_total) if good_total else None,
        confirmed_defective_count=defective_total,
        confirmed_good_count=good_total,
        miss_count=miss,
        caught_count=caught,
        false_alarm_count=false_alarm,
        fine_count=fine,
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
