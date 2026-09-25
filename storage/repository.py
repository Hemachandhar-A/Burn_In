"""P2's repository API (contracts.py Part 5.5) - the only place that writes SQL against
these tables; every other stage calls these functions instead (AGENTS.md rule 2).

Session P2.1: `save_account` and `save_project`.
Session P2.6: `save_analysis_run`, `log_event`, `save_disposition_signoff`,
`save_confirmed_outcome`, and every function's `query_*` counterpart.
Session P2.7 (E9): pins the real `results_json` shape below, additively over P2.6's
TEMP_ANALYSIS_RESULTS_DICT - no caller depended on a shape this doesn't still satisfy.

`save_analysis_run`'s `results` argument is a plain dict, not `contracts.AnalysisResults`
- `RiskAssessment`/`LotDisposition` don't carry the per-component module-activation/
forecast-resolution fields the diff needs, a gap already logged
(CONTRACT_CHANGES.md 2026-09-25 P2.6). `project_data.results_json` is documented
(essential-features.md E11 step 4, context.md 5.15) to mirror E9's report JSON export -
`report/data.py` (P2.7) reads this same shape verbatim, so this IS that pinned shape now,
not a placeholder waiting on a later session:
    {
      "per_component": {component_id: {
          "verdict": "PASS" | "WATCH" | "REJECT",
          "module_a_ran": bool, "module_b_ran": bool,
          "predicted_168h": float | None, "actual_168h": float | None,
          "explanation_sentence": str | None,  # NEW in P2.7 - optional, None until P5's
                                                # explainability engine populates it
      }},
      "lot_disposition": {                     # NEW in P2.7 - optional; absent/None until
          "pda_result": float,                 # fusion (P5) is wired (P2.5, currently
          "verdict": str,                      # blocked - see BLOCKERS.md), mirrors
          "is_forecast": bool,                 # contracts.LotDisposition's fields
          "status": "IN_PROGRESS" | "COMPLETE",
      } | None,
    }
The diff (`_diff_analysis_results`) only ever reads `per_component`'s five original keys,
so this extension is backward-compatible with every existing caller/fixture; it still
diffs the same three things per context.md 5.15: a module activating for the first time,
a forecast resolving into an actual, and a verdict moving. `lot_disposition`/
`explanation_sentence` are not diffed (no named case in context.md 5.15 covers them) -
`report/data.py` reads them directly off the latest run instead.

`project_data.raw_data`'s shape is pinned here too, also new this session:
`LotDataset.model_dump(mode="json")` - nothing had pinned it before (see CONTRACT_CHANGES.md).
"""
import uuid
from datetime import UTC, datetime

from contracts import (
    Account,
    ConfirmedOutcome,
    DispositionSignoff,
    Event,
    Project,
    ProjectData,
)
from storage.database import SessionLocal, init_db  # noqa: F401 - re-exported for scripts/seed.py

_EVENT_TYPES = {"ingest", "checkpoint_add", "analysis_run", "config_change"}
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


def save_project(project_id: str, lot_id: str, part_number: str, created_by: str) -> Project:
    with SessionLocal() as session:
        project = Project(
            project_id=project_id,
            lot_id=lot_id,
            part_number=part_number,
            created_at=datetime.now(UTC),
            created_by=created_by,
        )
        session.add(project)
        session.commit()
        return project


def query_project(project_id: str) -> Project | None:
    with SessionLocal() as session:
        return session.get(Project, project_id)


def query_projects() -> list[Project]:
    with SessionLocal() as session:
        return list(session.query(Project).order_by(Project.created_at.desc()).all())


def _diff_analysis_results(prior: dict, current: dict) -> dict:
    prior_components = prior.get("per_component", {})
    current_components = current.get("per_component", {})

    newly_activated_modules: dict[str, list[str]] = {}
    resolved_forecasts: dict[str, dict] = {}
    verdict_changes: dict[str, dict] = {}

    for component_id, curr in current_components.items():
        prev = prior_components.get(component_id, {})

        activated = [
            module
            for module, key in (("module_a", "module_a_ran"), ("module_b", "module_b_ran"))
            if curr.get(key) and not prev.get(key)
        ]
        if activated:
            newly_activated_modules[component_id] = activated

        if curr.get("actual_168h") is not None and prev.get("actual_168h") is None:
            resolved_forecasts[component_id] = {
                "predicted": curr.get("predicted_168h"),
                "actual": curr.get("actual_168h"),
            }

        prev_verdict = prev.get("verdict")
        curr_verdict = curr.get("verdict")
        if prev_verdict is not None and curr_verdict != prev_verdict:
            verdict_changes[component_id] = {"from": prev_verdict, "to": curr_verdict}

    return {
        "newly_activated_modules": newly_activated_modules,
        "resolved_forecasts": resolved_forecasts,
        "verdict_changes": verdict_changes,
    }


def save_analysis_run(project_id: str, raw_data: dict, results: dict) -> ProjectData:
    import json

    with SessionLocal() as session:
        prior = (
            session.query(ProjectData)
            .filter(ProjectData.project_id == project_id)
            .order_by(ProjectData.created_at.desc())
            .first()
        )
        diff = None
        if prior is not None:
            diff = _diff_analysis_results(json.loads(prior.results_json), results)

        run = ProjectData(
            analysis_run_id=f"run-{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            raw_data=json.dumps(raw_data),
            results_json=json.dumps(results),
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
            .order_by(ProjectData.created_at.asc())
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


def query_events(project_id: str) -> list[Event]:
    import json

    with SessionLocal() as session:
        rows = (
            session.query(Event)
            .filter(Event.project_id == project_id)
            .order_by(Event.timestamp.asc())
            .all()
        )
        for row in rows:
            row.payload = json.loads(row.payload)
        return list(rows)


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


def query_disposition_signoffs(project_id: str, component_id: str | None = None) -> list[DispositionSignoff]:
    with SessionLocal() as session:
        query = session.query(DispositionSignoff).filter(DispositionSignoff.project_id == project_id)
        if component_id is not None:
            query = query.filter(DispositionSignoff.component_id == component_id)
        return list(query.order_by(DispositionSignoff.timestamp.asc()).all())


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
        return list(query.order_by(ConfirmedOutcome.recorded_at.asc()).all())
