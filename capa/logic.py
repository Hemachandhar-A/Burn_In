import logging
import uuid
from datetime import UTC, datetime
from typing import Literal, NamedTuple

from pydantic import ValidationError

from contracts import (
    AnalysisResults, ConfirmedOutcome, CorrectiveStatusResponse, DispositionSignoff, DPARecommendation,
    ModuleAResult, ModuleBResult, Project, ProjectData,
)
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


# ---------------------------------------------------------------------------
# E13 step 4 (Block 4a Part 4) - GET /settings/worklist: tracking only, changes nothing.
# ---------------------------------------------------------------------------


def find_dispositions_awaiting_confirmed_outcome() -> list[DispositionSignoff]:
    """Every signed-off disposition (disposition_signoffs row) with no confirmed_outcomes row for
    the same (project_id, component_id), across every project - "N dispositions awaiting a confirmed
    outcome" (E13 step 4). One entry per disposition_signoffs row, matching
    WorklistResponse.pending: list[DispositionRecord] as the contract literally defines it - a dual
    sign-off's two rows for the same REJECT both appear here if that part has no confirmed outcome
    yet, since the contract wraps the raw signoff record, not a part-deduplicated view."""
    signoffs = query_disposition_signoffs()
    confirmed_keys = {(o.project_id, o.component_id) for o in query_confirmed_outcomes()}
    return [s for s in signoffs if (s.project_id, s.component_id) not in confirmed_keys]


# ---------------------------------------------------------------------------
# E13 step 5 / context.md 5.19 (Block 4a Part 5, Lead ruling D70.5) - DPA-sample recommendation.
# Pure function over an already-computed AnalysisResults - no re-running module_a/module_b, no I/O.
# Selection rule (a simple, explainable proxy, not a trained metric - none exists at this layer):
#   (i)   highest combined severity (Module A's own max-combined percentile, E2 step 5) among
#         flagged parts - confirms a suspected mechanism.
#   (ii)  highest Module B calibrated-interval width (interval_upper - interval_lower, "most
#         information gained per part destroyed", context.md 5.19) among WATCH-tier parts - WATCH is
#         the actual boundary tier by definition (context.md 6.2: "crossed REVIEW only" sits exactly
#         between PASS and REJECT). No numeric "distance to REJECT" is computed anywhere upstream
#         (module_a_rank/module_b_rank are per-run percentile ranks, not a trained boundary-distance
#         metric), so WATCH-tier membership itself is the boundary proxy. Falls back to REJECT-tier
#         parts only if no WATCH-tier part has a usable interval (both bounds present) - documented
#         here rather than silently returning fewer than the rule intends.
#   (iii) one control part: the unflagged (PASS-tier) part with the lowest component_id, not already
#         chosen - deterministic, no randomness (real DPA practice samples at random; this
#         recommendation is deliberately not random, so repeated calls agree).
# No part is recommended twice; ties at every step break on component_id ascending.
# ---------------------------------------------------------------------------

DPA_MAX_RECOMMENDATIONS = 3
DPA_FLAGGED_TIERS = ("WATCH", "REJECT")  # non-PASS: parts a DPA teardown would actually investigate
DPA_BOUNDARY_TIERS_PRIMARY = ("WATCH",)  # the boundary tier itself (context.md 6.2)
DPA_BOUNDARY_TIERS_FALLBACK = ("WATCH", "REJECT")  # used only if no WATCH-tier candidate qualifies


def _module_b_interval_width(module_b_results: dict[str, ModuleBResult], component_id: str) -> float | None:
    result = module_b_results.get(component_id)
    if result is None or result.interval_lower is None or result.interval_upper is None:
        return None
    return result.interval_upper - result.interval_lower


def select_dpa_work_order(results: AnalysisResults) -> list[DPARecommendation]:
    assessments = {a.component_id: a for a in results.assessments}
    a_results: dict[str, ModuleAResult] = results.module_a_results
    b_results: dict[str, ModuleBResult] = results.module_b_results

    chosen: list[str] = []
    recommendations: list[DPARecommendation] = []

    # (i) highest combined severity among flagged (WATCH/REJECT) parts.
    severity_candidates = sorted(
        (
            (cid, a_results[cid].combined_severity)
            for cid, a in assessments.items()
            if a.verdict in DPA_FLAGGED_TIERS and cid in a_results
        ),
        key=lambda pair: (-pair[1], pair[0]),
    )
    if severity_candidates:
        cid, severity = severity_candidates[0]
        chosen.append(cid)
        recommendations.append(DPARecommendation(
            component_id=cid, reason=f"Highest combined severity in the lot ({severity:.2f}).",
        ))

    # (ii) highest-uncertainty part nearest the WATCH/REJECT boundary.
    for tiers in (DPA_BOUNDARY_TIERS_PRIMARY, DPA_BOUNDARY_TIERS_FALLBACK):
        candidates = sorted(
            (
                (cid, width)
                for cid, a in assessments.items()
                if a.verdict in tiers and cid not in chosen
                for width in [_module_b_interval_width(b_results, cid)]
                if width is not None
            ),
            key=lambda pair: (-pair[1], pair[0]),
        )
        if candidates:
            cid, width = candidates[0]
            chosen.append(cid)
            recommendations.append(DPARecommendation(
                component_id=cid,
                reason=f"Highest-uncertainty part near the WATCH/REJECT boundary "
                       f"(Module B interval width {width:.2f}).",
            ))
            break

    # (iii) one control part: lowest component_id among PASS-tier parts not already chosen.
    control_candidates = sorted(
        cid for cid, a in assessments.items() if a.verdict == "PASS" and cid not in chosen
    )
    if control_candidates:
        cid = control_candidates[0]
        chosen.append(cid)
        severity = a_results[cid].combined_severity if cid in a_results else None
        reason = (
            f"Unflagged control part (PASS verdict, combined severity {severity:.2f}) for comparison."
            if severity is not None else "Unflagged control part (PASS verdict) for comparison."
        )
        recommendations.append(DPARecommendation(component_id=cid, reason=reason))

    return recommendations[:DPA_MAX_RECOMMENDATIONS]


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
