"""Rows sharing one timestamp (coarse Windows clock) must still come back in insertion order."""
import importlib
from datetime import UTC, datetime

import pytest

from contracts import AnalysisResults, LotDisposition, RiskAssessment

_FROZEN = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _FROZEN


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'tie.db'}")
    from storage import database

    importlib.reload(database)
    from storage import repository

    importlib.reload(repository)
    repository.init_db()
    repository.save_account(account_id="a", display_name="A", role="QE", pin_hash="h")
    monkeypatch.setattr(repository, "datetime", _FrozenDatetime)
    return repository


def _results(verdict="PASS"):
    return AnalysisResults(
        assessments=[RiskAssessment(
            component_id="C1", lot_id="L1", verdict=verdict, module_a_rank=0.25, module_b_rank=0.75,
            worst_parameter="iddq", module_a_ran=True, module_b_ran=True,
            predicted_168h=None, actual_168h=None, explanation_sentence=None,
        )],
        disposition=LotDisposition(lot_id="L1", status="IN_PROGRESS", pda_result=0.0,
                                   verdict="LOT_ON_TRACK", is_forecast=True),
    )


def test_same_timestamp_runs_keep_insertion_order(repo):
    repo.save_project("p1", "L1", "PN", _FROZEN, "a")
    ids = [repo.save_analysis_run("p1", {}, _results()).analysis_run_id for _ in range(150)]
    assert [r.analysis_run_id for r in repo.query_project_data("p1")] == ids
    assert repo.query_latest_project_data("p1").analysis_run_id == ids[-1]


def test_same_timestamp_prior_run_is_the_previous_insert(repo):
    repo.save_project("p1", "L1", "PN", _FROZEN, "a")
    repo.save_analysis_run("p1", {}, _results("PASS"))
    repo.save_analysis_run("p1", {}, _results("PASS"))
    third = repo.save_analysis_run("p1", {}, _results("REJECT"))
    # diff is against the second (PASS) run, so a verdict change must be recorded
    assert third.diff_vs_prior is not None
    assert third.diff_vs_prior["verdict_changes"]


def test_same_timestamp_events_signoffs_outcomes_keep_insertion_order(repo):
    repo.save_project("p1", "L1", "PN", _FROZEN, "a")
    run = repo.save_analysis_run("p1", {}, _results())
    for i in range(150):
        repo.log_event("p1", "a", "ingest", {"i": i})
        repo.save_disposition_signoff("p1", "C1", run.analysis_run_id, "a", "REJECT", f"r{i}")
        repo.save_confirmed_outcome("p1", "C1", run.analysis_run_id, "a", "Confirmed Defective", f"n{i}")
    assert [e.payload["i"] for e in repo.query_events("p1")] == list(range(150))
    assert [s.rationale for s in repo.query_disposition_signoffs("p1")] == [f"r{i}" for i in range(150)]
    assert [o.note for o in repo.query_confirmed_outcomes("p1")] == [f"n{i}" for i in range(150)]


def test_same_timestamp_projects_list_newest_insert_first(repo):
    for pid in ("p9", "p1", "p5", "p3"):
        repo.save_project(pid, "L1", "PN", _FROZEN, "a")
    assert [p.project_id for p in repo.query_projects()] == ["p3", "p5", "p1", "p9"]
