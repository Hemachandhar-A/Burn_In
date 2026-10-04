"""E9 steps 1-2 (session P2.7): assembles everything the report template (PDF/JSON/CSV)
needs, from data P2 already owns - nothing here re-implements another owner's logic
(AGENTS.md rule 2): the per-component verdict/PDA/disposition numbers are read verbatim
from `storage`'s persisted `results_json` (the real shape pinned this session, see
`storage/repository.py`'s module docstring and CONTRACT_CHANGES.md), never recomputed;
only the delta-data table (E9 step 1) is recomputed locally, via `features.compute`, which
is P2's own module, not a cross-directory reimplementation.

`raw_data` is documented as `LotDataset.model_dump(mode="json")` - the only pinned shape
for `project_data.raw_data`, logged to CONTRACT_CHANGES.md this session since nothing had
pinned it before.

`results_json` is a serialized `contracts.AnalysisResults`, read as-is. This module never fabricates
a value: `explanation=None` stays None until the explainability engine populates it (AGENTS.md rule 12).
"""
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from contracts import AnalysisResults, LotDataset
from features import compute as features_compute
from ingestion import store as ingestion_store
from storage import repository

_HISTORY_CAP = 10  # ScreeningConfig.report_history_cap_runs (contracts.py 5.1) - E9 step 2
_TRIGGER_EVENT_TYPES = {"ingest", "checkpoint_add"}

# Legacy text: the previous scoring (MODULE_A_SCORING=rank) - robust z, MCD and ECOD combined by maximum, no pooled reference.
_METHODOLOGY_SUMMARY = (
    "Parts were screened using two complementary modules. Module A flags components that are "
    "statistically anomalous relative to their own lot, even when every reading is inside the "
    "part's datasheet limit, combining a robust per-parameter z-score, Minimum Covariance "
    "Determinant (MCD) distance and an ECOD outlier score. The detector also supports an Isolation Forest score from a pooled "
    "cross-lot reference, but the live pipeline supplies no such reference, so that score does not "
    "contribute in this build; a REJECT verdict requires corroboration from an explainable "
    "detector (z-score or MCD). Module B forecasts each part's 168-hour reading from its 0h/24h readings "
    "and flags early rejection against a calibrated safety slope, where trained for the part's "
    "parameter; it declines to forecast, rather than guess, for any parameter outside the three it "
    "was trained on. The FN:FP cost ratio and PDA threshold used below are disclosed, adjustable "
    "defaults, not values derived from field failure data - see the system's Settings screen for "
    "their current values."
)


# Default text (demo-v2, MODULE_A_SCORING unset or "absolute"): only the legs that score are named.
_METHODOLOGY_SUMMARY_ABSOLUTE = (
    "Parts were screened using two complementary modules. Module A flags components that are "
    "statistically anomalous relative to their own lot, even when every reading is inside the "
    "part's datasheet limit. It converts a robust per-parameter z-score and, for lots of 77 or more parts, a Minimum "
    "Covariance Determinant (MCD) distance into tail probabilities and reports the most extreme one as a severity index "
    "(an index, not a probability); a part is flagged when the index passes the REVIEW or REJECT cut-off. ECOD and an "
    "Isolation Forest are not used to score parts in this build: ECOD has no reference to score against, and the Isolation "
    "Forest needs a pooled cross-lot reference that the live pipeline does not supply, so it does not contribute. "
    "Module B forecasts each part's 168-hour reading from its 0h/24h readings "
    "and flags early rejection against a calibrated safety slope, where trained for the part's "
    "parameter; it declines to forecast, rather than guess, for any parameter outside the three it "
    "was trained on. The FN:FP cost ratio (which selects Module A's REVIEW and REJECT cut-offs) and the PDA threshold are disclosed, adjustable "
    "defaults, not values derived from field failure data - see the system's Settings screen for "
    "their current values."
)


def methodology_summary(mode: str | None = None) -> str:
    """The PDF's methodology paragraph for a Module A scoring mode (default: the configured one)."""
    from module_a.settings import module_a_scoring

    return _METHODOLOGY_SUMMARY if (mode or module_a_scoring()) == "rank" else _METHODOLOGY_SUMMARY_ABSOLUTE


def analysis_settings_note(results: AnalysisResults) -> str:
    """Session I3: the Module A cut-offs this analysis used (selected by the Settings FN:FP ratio at the time) and, for a finished lot,
    what Module B's forecast did to the part verdicts under the configured role (fusion/settings.py). "" when neither applies."""
    from fusion.settings import module_b_finished_lot_role

    sentences: list[str] = []
    cutoffs = results.module_a_cutoffs
    if cutoffs.get("review") is not None and cutoffs.get("reject") is not None:
        sentences.append(
            f"Module A severity cut-offs used for this analysis: REVIEW at s >= {cutoffs['review']:.2f}, REJECT at s >= "
            f"{cutoffs['reject']:.2f}, selected by the FN:FP cost ratio setting at the time of the analysis."
        )
    if results.disposition.status == "COMPLETE":
        role = module_b_finished_lot_role()
        if role == "advisory":
            n = len(results.module_b_advisory_notes)
            sentences.append(
                "On this finished lot Module B's forecast did not change any part's verdict, which Module A sets from the measured "
                f"readings; {n} {'part carries' if n == 1 else 'parts carry'} an information note that the forecast exceeded the safety slope."
            )
        elif role == "current":
            sentences.append("On this finished lot Module B's forecast counts toward a part's verdict (role: current).")
        elif role == "tiered":
            sentences.append(
                "On this finished lot Module B's forecast counts toward a part's verdict only as REVIEW unless its interval's lower bound "
                "also exceeds the safety slope (role: tiered)."
            )
        else:
            sentences.append("On this finished lot Module B's forecast is not used for a part's verdict (role: off).")
    return " ".join(sentences)


@dataclass
class DeltaRow:
    component_id: str
    parameter: str
    value_0h: float
    value_24h: float
    delta_24h: float
    value_96h: float | None
    delta_96h: float | None
    value_168h: float | None
    delta_168h: float | None
    verdict: str | None
    unit: str | None = None  # F24 Part 3: the parameter's canonical unit (the PDF shows it and scales by it)


@dataclass
class FlaggedPart:
    component_id: str
    parameter: str
    verdict: str
    explanation: str | None
    disposition_history: list[dict] = field(default_factory=list)


@dataclass
class AnalysisHistoryEntry:
    analysis_run_id: str
    timestamp: datetime
    trigger: str
    what_changed: str


@dataclass
class ReportData:
    report_reference_id: str
    generated_at: datetime
    project_id: str
    lot_id: str
    part_number: str
    manufacturer: str | None
    date_code: str | None
    test_date: str | None
    lot_status: str
    methodology_summary: str
    quantity_screened: int
    quantity_flagged: int
    pda_available: bool
    pda_result: float | None
    overall_disposition: str | None
    is_forecast: bool | None
    latest_analysis_run_id: str
    delta_table: list[DeltaRow]
    flagged_parts: list[FlaggedPart]
    analysis_history: list[AnalysisHistoryEntry]
    analysis_history_truncated: bool
    reviewer_entries: list[dict]
    # Session I3: what this analysis used (Module A cut-offs from the FN:FP setting) and what Module B did on a finished lot. "" when neither applies.
    analysis_settings_note: str = ""


def _describe_diff(diff: dict | None) -> str:
    if diff is None:
        return "Initial analysis run - no prior revision to compare."

    parts: list[str] = []
    activated = diff.get("newly_activated_modules") or {}
    if activated:
        pieces = [f"{cid} ({', '.join(mods)})" for cid, mods in sorted(activated.items())]
        parts.append(f"Module(s) newly activated for: {'; '.join(pieces)}.")

    resolved = diff.get("resolved_forecasts") or {}
    if resolved:
        pieces = [
            f"{cid} (predicted {v.get('predicted')}, actual {v.get('actual')})"
            for cid, v in sorted(resolved.items())
        ]
        parts.append(f"Forecast(s) resolved into an actual reading: {'; '.join(pieces)}.")

    changed = diff.get("verdict_changes") or {}
    if changed:
        pieces = [f"{cid} ({v.get('from')} -> {v.get('to')})" for cid, v in sorted(changed.items())]
        parts.append(f"Verdict change(s): {'; '.join(pieces)}.")

    if not parts:
        return "No revision from the prior run - re-run produced identical results."
    return " ".join(parts)


def _trigger_for_run(events: list, run_created_at: datetime) -> str:
    candidates = [e for e in events if e.event_type in _TRIGGER_EVENT_TYPES and e.timestamp <= run_created_at]
    if not candidates:
        return "analysis_run"
    return max(enumerate(candidates), key=lambda t: (t[1].timestamp, t[0]))[1].event_type  # ties: later insert wins


def build_report_data(project_id: str) -> ReportData:
    """Raises `LookupError` if the project doesn't exist, or exists but has no analysis run
    yet - a report is a view over completed analysis (E9's own framing: "a templating
    exercise over data already computed by E2-E6"), not something to fabricate from raw
    readings alone."""
    project = repository.query_project(project_id)
    if project is None:
        raise LookupError(f"project '{project_id}' not found")

    runs = repository.query_project_data(project_id)
    if not runs:
        raise LookupError(f"project '{project_id}' has no analysis runs yet - nothing to report")

    latest = runs[-1]
    import json

    raw_data = json.loads(latest.raw_data) if isinstance(latest.raw_data, str) else latest.raw_data
    results = AnalysisResults.model_validate_json(latest.results_json)

    lot: LotDataset | None = None
    manufacturer = date_code = None
    lot_status = "IN_PROGRESS"
    delta_table: list[DeltaRow] = []
    quantity_screened = 0
    assessments = {a.component_id: a for a in results.assessments}

    if raw_data and raw_data.get("readings"):
        lot = LotDataset.model_validate(raw_data)
        manufacturer = lot.readings[0].manufacturer
        date_code = lot.readings[0].date_code
        lot_status = lot.status
        quantity_screened = len({r.component_id for r in lot.readings})

        pooled_readings = repository.query_readings_by_part_number(
            lot.part_number, exclude_lot_id=lot.lot_id
        )
        pooled_reference = features_compute.build_pooled_reference(lot.part_number, pooled_readings)
        frames = features_compute.compute(lot, pooled_reference=pooled_reference or None)
        unit_by_parameter: dict[str, str] = {}
        for reading in lot.readings:
            if reading.unit:
                unit_by_parameter.setdefault(reading.parameter, reading.unit)
        for frame in frames:
            assessment = assessments.get(frame.component_id)
            verdict = assessment.verdict if assessment else None
            delta_table.append(DeltaRow(
                component_id=frame.component_id, parameter=frame.parameter,
                value_0h=frame.value_0h, value_24h=frame.value_24h, delta_24h=frame.delta_24h,
                value_96h=frame.value_96h, delta_96h=frame.delta_96h,
                value_168h=frame.value_168h, delta_168h=frame.delta_168h,
                verdict=verdict, unit=unit_by_parameter.get(frame.parameter),
            ))

    quantity_flagged = sum(1 for a in assessments.values() if a.verdict in ("WATCH", "REJECT"))

    disposition = results.disposition
    pda_available = True
    pda_result = disposition.pda_result
    overall_disposition = disposition.verdict
    is_forecast = disposition.is_forecast

    disposition_signoffs = repository.query_disposition_signoffs(project_id)
    signoffs_by_component: dict[str, list[dict]] = {}
    reviewer_entries: list[dict] = []
    for s in disposition_signoffs:
        entry = {
            "component_id": s.component_id, "account_id": s.account_id, "verdict": s.verdict,
            "rationale": s.rationale, "timestamp": s.timestamp,
        }
        signoffs_by_component.setdefault(s.component_id, []).append(entry)
        reviewer_entries.append(entry)

    def stored_sentence(cid: str) -> str | None:
        # RiskAssessment.explanation_sentence is never filled by the pipeline; the sentence lives on the stored
        # PartExplanation (F24 Part 3: the report must show the sentence, units included, not "not yet available").
        explanation = results.part_explanations.get(cid)
        return explanation.explanation_sentence if explanation is not None else None

    flagged_parts: list[FlaggedPart] = []
    for cid, assessment in assessments.items():
        verdict = assessment.verdict
        if verdict not in ("WATCH", "REJECT"):
            continue
        parameter = next((row.parameter for row in delta_table if row.component_id == cid), "")
        flagged_parts.append(FlaggedPart(
            component_id=cid, parameter=parameter, verdict=verdict,
            explanation=assessment.explanation_sentence or stored_sentence(cid),
            disposition_history=signoffs_by_component.get(cid, []),
        ))

    events = repository.query_events(project_id)
    history_entries = [
        AnalysisHistoryEntry(
            analysis_run_id=run.analysis_run_id,
            timestamp=run.created_at,
            trigger=_trigger_for_run(events, run.created_at),
            what_changed=_describe_diff(run.diff_vs_prior),
        )
        for run in runs
    ]
    truncated = len(history_entries) > _HISTORY_CAP
    if truncated:
        history_entries = history_entries[-_HISTORY_CAP:]

    test_date = None
    record = ingestion_store.get(project.lot_id)
    if record is not None:
        test_date = record.test_date

    return ReportData(
        report_reference_id=f"RPT-{uuid.uuid4().hex[:10].upper()}",
        generated_at=datetime.now(UTC),
        project_id=project_id,
        lot_id=project.lot_id,
        part_number=project.part_number,
        manufacturer=manufacturer,
        date_code=date_code,
        test_date=test_date,
        lot_status=lot_status,
        methodology_summary=methodology_summary(),
        quantity_screened=quantity_screened,
        quantity_flagged=quantity_flagged,
        pda_available=pda_available,
        pda_result=pda_result,
        overall_disposition=overall_disposition,
        is_forecast=is_forecast,
        latest_analysis_run_id=latest.analysis_run_id,
        delta_table=delta_table,
        flagged_parts=flagged_parts,
        analysis_history=history_entries,
        analysis_history_truncated=truncated,
        reviewer_entries=reviewer_entries,
        analysis_settings_note=analysis_settings_note(results),
    )
