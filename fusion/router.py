"""Session P5.3: fusion/router.py - Lot Dashboard live computation.

Block 3B Part 4 adds GET /parts/{component_id} (IMPLEMENTATION_PLAN.md Part 5.6's route table,
P5.7's session entry) - it aggregates explain/, identity/, capa/ (via storage's repository
functions, never their routers) and P5's own stored AnalysisResults, and never re-runs
fusion.run_full_pipeline (Part 4c pins this with a monkeypatch-raises test)."""
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from contracts import (
    Account, AnalysisResults, ConfirmedOutcomeRecord, DispositionRecord, LotSummaryResponse,
    LotDataset, PartDetailResponse, PartExplanation, ScreeningConfig, RiskAssessment, LotDisposition,
)
from explain.text import confidence_qualifier, unavailable_forecast_note
from identity.auth import get_current_account
from identity.status import disposition_status_for
from storage.repository import (
    query_confirmed_outcomes, query_disposition_signoffs, query_project_data, query_latest_project_data,
    query_projects,
)

router = APIRouter(tags=["fusion"])
logger = logging.getLogger(__name__)

@router.get("/lots/{lot_id}", response_model=LotSummaryResponse)
def get_lot_summary(lot_id: str) -> LotSummaryResponse:
    matches = [p for p in query_projects() if p.lot_id == lot_id]
    if not matches:
        raise HTTPException(status_code=404, detail=f"no project found for lot '{lot_id}'")
    project = matches[0]

    latest_data = query_latest_project_data(project.project_id)
    if not latest_data:
        raise HTTPException(status_code=404, detail=f"No analysis run found for lot {lot_id}")
    return LotSummaryResponse.model_validate_json(latest_data.results_json)


def _matching_runs(component_id: str, lot_id: str | None):
    """Every (project, ProjectData row, parsed AnalysisResults) whose assessments contain
    component_id, optionally restricted to one lot_id. A row that predates AnalysisResults'
    current shape (fails validation) is skipped, not a 500 - the same discipline
    storage.repository._diff_analysis_results already applies to an incomparable prior row."""
    matches = []
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
    return matches


@router.get("/parts/{component_id}", response_model=PartDetailResponse)
def get_part_detail(
    component_id: str,
    lot_id: str | None = None,
    account: Account = Depends(get_current_account),
) -> PartDetailResponse:
    matches = _matching_runs(component_id, lot_id)
    if not matches:
        detail = f"component '{component_id}' not found"
        if lot_id is not None:
            detail += f" in lot '{lot_id}'"
        raise HTTPException(status_code=404, detail=detail)

    # 4a: the most recent stored analysis run that contains component_id - across every matching
    # lot when lot_id is not given (an ambiguous component_id resolves to its newest run, never an
    # error), or within the one named lot when it is.
    _, (project, row, results) = max(enumerate(matches), key=lambda t: (t[1][1].created_at, t[0]))  # ties: later insert wins

    assessment = next(a for a in results.assessments if a.component_id == component_id)
    module_a = results.module_a_results.get(component_id)
    module_b = results.module_b_results.get(component_id)
    # Documented gap (CONTRACT_CHANGES.md 2026-09-30): Module A never runs on an IN_PROGRESS lot, so
    # a component whose only stored run is still in progress has no ModuleAResult - module_a/module_b
    # are Optional (Block 3C) precisely for this case, never fabricated (rule 7). 404 is reserved for
    # a genuinely unknown component_id, handled by the `not matches` check above.

    explanation = results.part_explanations.get(component_id)
    if explanation is not None:
        # 4b: the stored explanation fields - never recomputed.
        explanation_sentence = explanation.explanation_sentence or "within normal range"
        confidence_qualifier_text = explanation.confidence_qualifier or ""
        severity_cap_note_text = explanation.severity_cap_note
        unavailable_forecast_note_text = explanation.unavailable_forecast_note
    else:
        # A PASS part (or a pre-explanation stored row): a plain sentence and empty chart lists
        # (4b), but unavailable_forecast_note is still a true read of the stored ModuleBResult -
        # reading a pure function over already-stored data is not "re-running the pipeline".
        explanation = PartExplanation()
        explanation_sentence = "within normal range"
        confidence_qualifier_text = confidence_qualifier(module_b) or ""
        severity_cap_note_text = None
        unavailable_forecast_note_text = unavailable_forecast_note(module_b)

    staleness_note_text = _staleness_note_for(project.project_id, component_id, row)

    disposition_history = [
        DispositionRecord(
            project_id=s.project_id, component_id=s.component_id, account_id=s.account_id,
            verdict=s.verdict, rationale=s.rationale, timestamp=s.timestamp,
            analysis_run_id=s.analysis_run_id,
        )
        for s in query_disposition_signoffs(project_id=project.project_id, component_id=component_id)
    ]
    confirmed_outcomes = [
        ConfirmedOutcomeRecord(
            project_id=o.project_id, component_id=o.component_id, account_id=o.account_id,
            confirmed_outcome=o.confirmed_outcome, note=o.note, recorded_at=o.recorded_at,
            analysis_run_id=o.analysis_run_id,
        )
        for o in query_confirmed_outcomes(project_id=project.project_id)
        if o.component_id == component_id
    ]

    return PartDetailResponse(
        module_a=module_a,
        module_b=module_b,
        explanation_sentence=explanation_sentence,
        confidence_qualifier=confidence_qualifier_text,
        severity_cap_note=severity_cap_note_text,
        unavailable_forecast_note=unavailable_forecast_note_text,
        module_b_advisory_note=results.module_b_advisory_notes.get(component_id),
        staleness_note=staleness_note_text,
        disposition_history=disposition_history,
        confirmed_outcomes=confirmed_outcomes,
        explanation=explanation,
        # Block 4c Part 3a (Lead ruling D79): all five filled for every found part - never None here,
        # the field-level Optional/None-default exists only so an old stored/cached response parses.
        component_id=assessment.component_id,
        lot_id=assessment.lot_id,
        project_id=project.project_id,
        analysis_run_id=row.analysis_run_id,
        verdict=assessment.verdict,
        disposition_status=disposition_status_for(project.project_id, component_id, row.analysis_run_id),
    )


def _staleness_note_for(project_id: str, component_id: str, latest_row) -> str | None:
    """E4 step 10 / explain.text.staleness_note, fed from this part's most recent disposition
    sign-off and the project's own run history - see explain/text.py's own docstring for why this
    is None beyond a one-run gap (CONTRACT_CHANGES.md 2026-09-30)."""
    signoffs = query_disposition_signoffs(project_id=project_id, component_id=component_id)
    if not signoffs:
        return None
    latest_signoff = max(enumerate(signoffs), key=lambda t: (t[1].timestamp, t[0]))[1]  # ties: later insert wins

    rows = query_project_data(project_id)  # ascending by created_at
    second_latest_run_id = rows[-2].analysis_run_id if len(rows) >= 2 else None

    from explain.text import staleness_note

    return staleness_note(
        disposition_analysis_run_id=latest_signoff.analysis_run_id,
        latest_analysis_run_id=latest_row.analysis_run_id,
        second_latest_analysis_run_id=second_latest_run_id,
        diff_vs_prior=latest_row.diff_vs_prior,
    )
