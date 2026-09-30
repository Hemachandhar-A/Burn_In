"""P2's repository API (contracts.py Part 5.5) - the only place that writes SQL against
these tables; every other stage calls these functions instead (AGENTS.md rule 2).

Session P2.1: `save_account` and `save_project`.
Session P2.6: `save_analysis_run`, `log_event`, `save_disposition_signoff`,
`save_confirmed_outcome`, and every function's `query_*` counterpart.
Session P2.7 (E9): pins the real `results_json` shape below, additively over P2.6's
TEMP_ANALYSIS_RESULTS_DICT - no caller depended on a shape this doesn't still satisfy.

`save_analysis_run`'s `results` argument is a real `contracts.AnalysisResults`, stored as
`results.model_dump_json()` - exactly what `contracts.ProjectData.results_json` documents, so
`GET /lots/{lot_id}` and `report/data.py` read every `RiskAssessment` field (including
`module_a_rank`/`module_b_rank`/`worst_parameter`) with nothing reshaped or defaulted. The diff
(`_diff_analysis_results`) reads `assessments` and diffs three things per context.md 5.15: a module
activating for the first time, a forecast resolving into an actual, and a verdict moving.
A prior row stored in the retired `per_component` shape can't be compared; it yields a null diff.

`project_data.raw_data`'s shape is pinned here too, also new this session:
`LotDataset.model_dump(mode="json")` - nothing had pinned it before (see CONTRACT_CHANGES.md).
"""
import json
import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import literal_column

from contracts import (
    Account,
    AnalysisResults,
    ConfirmedOutcome,
    DispositionSignoff,
    Event,
    LotDataset,
    Project,
    ProjectData,
    Reading,
)
from storage.database import SessionLocal, init_db  # noqa: F401 - re-exported for scripts/seed.py

_EVENT_TYPES = {"ingest", "checkpoint_add", "analysis_run", "config_change", "timing_flag"}
_DISPOSITION_VERDICTS = {"ACCEPT", "HOLD", "REJECT"}
_CONFIRMED_OUTCOMES = {"Confirmed Good", "Confirmed Defective", "Unknown"}


def save_account(account_id: str, display_name: str, role: str, pin_hash: str) -> Account:
    with SessionLocal() as session:
        account = Account(account_id=account_id, display_name=display_name, role=role, pin_hash=pin_hash)
        session.add(account)
        session.commit()
        return account


def query_account(account_id: str) -> Account | None:
    with SessionLocal() as session:
        return session.get(Account, account_id)


def save_project(
    project_id: str, lot_id: str, part_number: str, test_date: datetime, created_by: str,
    manufacturer: str | None = None, date_code: str | None = None,
) -> Project:
    with SessionLocal() as session:
        project = Project(
            project_id=project_id,
            lot_id=lot_id,
            part_number=part_number,
            test_date=test_date,
            created_at=datetime.now(UTC),
            created_by=created_by,
            manufacturer=manufacturer,
            date_code=date_code,
        )
        session.add(project)
        session.commit()
        return project


def query_project(project_id: str) -> Project | None:
    with SessionLocal() as session:
        return session.get(Project, project_id)


def query_projects() -> list[Project]:
    with SessionLocal() as session:
        return list(
            session.query(Project)
            .order_by(Project.created_at.desc(), literal_column("projects.rowid").desc())
            .all()
        )


def query_readings_by_part_number(part_number: str, *, exclude_lot_id: str | None = None) -> list[Reading]:
    """P2.6 follow-up (CONTRACT_CHANGES.md 2026-09-25 "No storage query function exists yet
    for the pooled cross-lot reference E8 step 3 needs"; scope confirmed P2.6 by the Lead's
    "Resolving P2's four open entries" note, item 4). Pools every `Reading` from other lots
    sharing `part_number` - there is no dedicated readings table (`project_data.raw_data` is
    the pinned `LotDataset.model_dump(mode="json")` shape, P2.7), so this reads the latest
    `ProjectData` row per matching `Project` and re-parses its `readings`. `exclude_lot_id`
    keeps a lot from pooling against itself. `features.build_pooled_reference` turns the
    result into `compute()`'s `pooled_reference` shape."""
    with SessionLocal() as session:
        projects = session.query(Project).filter(Project.part_number == part_number).all()
        readings: list[Reading] = []
        for project in projects:
            if exclude_lot_id is not None and project.lot_id == exclude_lot_id:
                continue
            latest = (
                session.query(ProjectData)
                .filter(ProjectData.project_id == project.project_id)
                .order_by(ProjectData.created_at.desc(), literal_column("project_data.rowid").desc())
                .first()
            )
            if latest is None:
                continue
            raw_data = json.loads(latest.raw_data)
            if not raw_data.get("readings"):
                continue
            readings.extend(LotDataset.model_validate(raw_data).readings)
        return readings


def _diff_analysis_results(prior: AnalysisResults, current: AnalysisResults) -> dict:
    prior_by_id = {a.component_id: a for a in prior.assessments}

    newly_activated_modules: dict[str, list[str]] = {}
    resolved_forecasts: dict[str, dict] = {}
    verdict_changes: dict[str, dict] = {}

    for curr in current.assessments:
        cid = curr.component_id
        prev = prior_by_id.get(cid)

        activated = [
            module
            for module, ran in (("module_a", "module_a_ran"), ("module_b", "module_b_ran"))
            if getattr(curr, ran) and not (prev and getattr(prev, ran))
        ]
        if activated:
            newly_activated_modules[cid] = activated

        if curr.actual_168h is not None and (prev is None or prev.actual_168h is None):
            resolved_forecasts[cid] = {"predicted": curr.predicted_168h, "actual": curr.actual_168h}

        if prev is not None and curr.verdict != prev.verdict:
            verdict_changes[cid] = {"from": prev.verdict, "to": curr.verdict}

    return {
        "newly_activated_modules": newly_activated_modules,
        "resolved_forecasts": resolved_forecasts,
        "verdict_changes": verdict_changes,
    }


def save_analysis_run(project_id: str, raw_data: dict, results: AnalysisResults) -> ProjectData:
    with SessionLocal() as session:
        prior = (
            session.query(ProjectData)
            .filter(ProjectData.project_id == project_id)
            .order_by(ProjectData.created_at.desc(), literal_column("project_data.rowid").desc())
            .first()
        )
        diff = None
        if prior is not None:
            try:
                diff = _diff_analysis_results(AnalysisResults.model_validate_json(prior.results_json), results)
            except ValidationError:
                diff = None  # prior row predates the AnalysisResults shape; nothing comparable

        run = ProjectData(
            analysis_run_id=f"run-{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            raw_data=json.dumps(raw_data),
            results_json=results.model_dump_json(),
            diff_vs_prior=json.dumps(diff) if diff is not None else None,
            created_at=datetime.now(UTC),
        )
        session.add(run)
        session.commit()

        # Expose the decoded dict, not the raw JSON string, to callers in-process.
        run.diff_vs_prior = diff
        return run


def query_project_data(project_id: str) -> list[ProjectData]:
    import json

    with SessionLocal() as session:
        rows = (
            session.query(ProjectData)
            .filter(ProjectData.project_id == project_id)
            .order_by(ProjectData.created_at.asc(), literal_column("project_data.rowid").asc())
            .all()
        )
        for row in rows:
            row.diff_vs_prior = json.loads(row.diff_vs_prior) if row.diff_vs_prior else None
        return list(rows)


def query_latest_project_data(project_id: str) -> ProjectData | None:
    rows = query_project_data(project_id)
    return rows[-1] if rows else None


def log_event(project_id: str, account_id: str, event_type: str, payload: dict) -> Event:
    import json

    if event_type not in _EVENT_TYPES:
        raise ValueError(f"Unrecognized event_type {event_type!r}; must be one of {sorted(_EVENT_TYPES)}")

    with SessionLocal() as session:
        event = Event(
            event_id=f"event-{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            account_id=account_id,
            event_type=event_type,
            timestamp=datetime.now(UTC),
            payload=json.dumps(payload),
        )
        session.add(event)
        session.commit()
        event.payload = payload
        return event


def query_events(project_id: str | None = None) -> list[Event]:
    import json

    with SessionLocal() as session:
        query = session.query(Event)
        if project_id is not None:
            query = query.filter(Event.project_id == project_id)
        rows = list(query.order_by(Event.timestamp.asc(), literal_column("events.rowid").asc()).all())
        for row in rows:
            row.payload = json.loads(row.payload)
        return rows


def save_disposition_signoff(
    project_id: str,
    component_id: str,
    analysis_run_id: str,
    account_id: str,
    verdict: str,
    rationale: str,
) -> DispositionSignoff:
    if verdict not in _DISPOSITION_VERDICTS:
        raise ValueError(f"Unrecognized verdict {verdict!r}; must be one of {sorted(_DISPOSITION_VERDICTS)}")

    with SessionLocal() as session:
        signoff = DispositionSignoff(
            project_id=project_id,
            component_id=component_id,
            analysis_run_id=analysis_run_id,
            account_id=account_id,
            verdict=verdict,
            rationale=rationale,
            timestamp=datetime.now(UTC),
        )
        session.add(signoff)
        session.commit()
        return signoff


def query_disposition_signoffs(
    project_id: str | None = None, component_id: str | None = None
) -> list[DispositionSignoff]:
    with SessionLocal() as session:
        query = session.query(DispositionSignoff)
        if project_id is not None:
            query = query.filter(DispositionSignoff.project_id == project_id)
        if component_id is not None:
            query = query.filter(DispositionSignoff.component_id == component_id)
        return list(query.order_by(DispositionSignoff.timestamp.asc(), literal_column("disposition_signoffs.rowid").asc()).all())


def save_confirmed_outcome(
    project_id: str,
    component_id: str,
    analysis_run_id: str,
    account_id: str,
    confirmed_outcome: str,
    note: str | None = None,
) -> ConfirmedOutcome:
    if confirmed_outcome not in _CONFIRMED_OUTCOMES:
        raise ValueError(
            f"Unrecognized confirmed_outcome {confirmed_outcome!r}; must be one of {sorted(_CONFIRMED_OUTCOMES)}"
        )

    with SessionLocal() as session:
        outcome = ConfirmedOutcome(
            confirmed_outcome_id=f"outcome-{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            component_id=component_id,
            analysis_run_id=analysis_run_id,
            account_id=account_id,
            confirmed_outcome=confirmed_outcome,
            note=note,
            recorded_at=datetime.now(UTC),
        )
        session.add(outcome)
        session.commit()
        return outcome


def query_confirmed_outcomes(project_id: str | None = None) -> list[ConfirmedOutcome]:
    with SessionLocal() as session:
        query = session.query(ConfirmedOutcome)
        if project_id is not None:
            query = query.filter(ConfirmedOutcome.project_id == project_id)
        return list(query.order_by(ConfirmedOutcome.recorded_at.asc(), literal_column("confirmed_outcomes.rowid").asc()).all())
