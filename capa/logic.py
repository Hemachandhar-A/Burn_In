import logging
import uuid
from datetime import UTC, datetime
from typing import Literal, NamedTuple

from pydantic import ValidationError

from contracts import AnalysisResults, ConfirmedOutcome, CorrectiveStatusResponse, Project, ProjectData
from capa.models import TEMP_CapaRecord
from storage.repository import (
    query_confirmed_outcomes, query_events, log_event, query_disposition_signoffs, query_project_data,
    query_projects,
)

logger = logging.getLogger(__name__)

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
# E13 step 1 (Block 4a Part 1) - locating the run a confirmed outcome links to. Mirrors
# fusion/router.py::_matching_runs's selection rule (the latest stored run containing component_id,
# optionally restricted to one lot) without importing fusion's own private helper - capa/ and fusion/
# are separately-owned P5 directories for this session (AGENTS.md rule 2: call an exposed function,
# never reach into another module's private internals).
# ---------------------------------------------------------------------------


def find_latest_run_for_component(
    component_id: str, lot_id: str | None = None
) -> tuple[Project, ProjectData, AnalysisResults] | None:
    """The (project, ProjectData row, parsed AnalysisResults) for the most recent stored analysis run
    whose assessments contain component_id, across every matching lot when lot_id is None or within
    the one named lot when given. None if no such run exists. A row that fails AnalysisResults
    validation is skipped (logged), not a 500 - same discipline as fusion/router.py::_matching_runs."""
    matches: list[tuple[Project, ProjectData, AnalysisResults]] = []
    for project in query_projects():
        if lot_id is not None and project.lot_id != lot_id:
            continue
        for row in query_project_data(project.project_id):
            try:
                results = AnalysisResults.model_validate_json(row.results_json)
            except ValidationError as exc:
                logger.warning(
                    "skipping stored analysis run %s (project %s) - failed AnalysisResults validation: %s",
                    row.analysis_run_id, project.project_id, exc,
                )
                continue
            if any(a.component_id == component_id for a in results.assessments):
                matches.append((project, row, results))
    if not matches:
        return None
    return max(matches, key=lambda m: m[1].created_at)


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


# ---------------------------------------------------------------------------
# E13 steps 6-8 (Block 4a Part 3b) - GET /settings/corrective-status: live-computed on every call,
# nothing stored. Ties compute_match_rates (Part 2) to storage - the one I/O step Part 2's own
# pure function deliberately does not do.
# ---------------------------------------------------------------------------


def _verdict_for_outcome(outcome: ConfirmedOutcome) -> str | None:
    """The model's verdict tier (RiskAssessment.verdict) at the exact analysis_run_id a confirmed
    outcome is linked to - not the latest run for that project, the run that was actually judged
    (E13 step 1). None if the row or the component within it can no longer be found (a data-integrity
    edge that should not occur under normal operation, logged rather than raised - one bad row must
    not 500 the whole live-computed status)."""
    for row in query_project_data(outcome.project_id):
        if row.analysis_run_id != outcome.analysis_run_id:
            continue
        try:
            results = AnalysisResults.model_validate_json(row.results_json)
        except ValidationError as exc:
            logger.warning(
                "corrective-status: skipping confirmed outcome %s - stored run %s failed "
                "AnalysisResults validation: %s", outcome.confirmed_outcome_id, row.analysis_run_id, exc,
            )
            return None
        for assessment in results.assessments:
            if assessment.component_id == outcome.component_id:
                return assessment.verdict
        return None
    return None


def compute_corrective_status(
    ceiling: float, min_confirmed_outcomes: int, outcomes: list[ConfirmedOutcome] | None = None,
) -> CorrectiveStatusResponse:
    """E13 steps 6-8. outcomes defaults to every confirmed outcome across every project (the ceiling
    is a global Settings value, not per-project). status is INSUFFICIENT_DATA strictly below
    min_confirmed_outcomes (Good+Defective, Unknown excluded) regardless of the FN rate; otherwise
    CEILING_EXCEEDED iff the FN rate is known and exceeds ceiling, else OK. fp_rate is informational
    only, never a trigger (E13 step 7).

    CorrectiveStatusResponse.fn_rate/fp_rate are contract-frozen required floats (not Optional) -
    contracts.py is read-only here (AGENTS.md rule 3), so a None rate (zero denominator, e.g. zero
    Confirmed Defective outcomes so far) is rendered as 0.0 at this API boundary, a disclosed
    rendering choice logged in CONTRACT_CHANGES.md, not a silent guess: compute_match_rates itself
    still returns the honest None to any caller that wants it."""
    if outcomes is None:
        outcomes = query_confirmed_outcomes()

    pairs: list[tuple[str, str]] = []
    for outcome in outcomes:
        verdict = _verdict_for_outcome(outcome)
        if verdict is None:
            continue
        pairs.append((outcome.confirmed_outcome, verdict))

    rates = compute_match_rates(pairs)
    confirmed_outcome_count = rates.confirmed_defective_count + rates.confirmed_good_count

    if confirmed_outcome_count < min_confirmed_outcomes:
        status: Literal["OK", "CEILING_EXCEEDED", "INSUFFICIENT_DATA"] = "INSUFFICIENT_DATA"
    elif rates.fn_rate is not None and rates.fn_rate > ceiling:
        status = "CEILING_EXCEEDED"
    else:
        status = "OK"

    return CorrectiveStatusResponse(
        fn_rate=rates.fn_rate if rates.fn_rate is not None else 0.0,
        fp_rate=rates.fp_rate if rates.fp_rate is not None else 0.0,
        confirmed_outcome_count=confirmed_outcome_count,
        status=status,
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
