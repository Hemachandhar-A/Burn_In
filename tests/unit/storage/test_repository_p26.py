"""Session P2.6: E11 steps 4-8 - project_data+diff, events, disposition_signoffs,
confirmed_outcomes, and the full repository query API (IMPLEMENTATION_PLAN.md Part 10).

`results` passed to save_analysis_run is a TEMP_ANALYSIS_RESULTS_DICT shape (see
repository.py module docstring / CONTRACT_CHANGES.md) since E9's JSON export (which
project_data.results_json is documented to mirror) doesn't exist yet - P2.7 builds it.
"""
import importlib

import pytest


@pytest.fixture()
def repository(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    from storage import database

    importlib.reload(database)
    from storage import repository

    importlib.reload(repository)
    repository.init_db()
    repository.save_account(account_id="a.sharma", display_name="A. Sharma", role="QE", pin_hash="h")
    repository.save_account(account_id="b.rao", display_name="B. Rao", role="QE", pin_hash="h2")
    repository.save_project(project_id="proj-1", lot_id="L1", part_number="PN-100", created_by="a.sharma")
    return repository


def _results(component_id="C1", verdict="PASS", module_a_ran=True, module_b_ran=True,
             predicted_168h=None, actual_168h=None):
    return {
        "per_component": {
            component_id: {
                "verdict": verdict,
                "module_a_ran": module_a_ran,
                "module_b_ran": module_b_ran,
                "predicted_168h": predicted_168h,
                "actual_168h": actual_168h,
            }
        }
    }


# --- save_analysis_run / query_project_data / query_latest_project_data -----------


def test_first_analysis_run_has_null_diff(repository):
    run = repository.save_analysis_run(
        project_id="proj-1", raw_data={"lot_id": "L1"}, results=_results()
    )
    assert run.project_id == "proj-1"
    assert run.analysis_run_id
    assert run.diff_vs_prior is None


def test_project_data_is_append_only_new_row_per_run(repository):
    repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results())
    repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results())
    rows = repository.query_project_data("proj-1")
    assert len(rows) == 2
    assert rows[0].analysis_run_id != rows[1].analysis_run_id


def test_latest_project_data_is_most_recent_row_not_a_stored_flag(repository):
    first = repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results())
    second = repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results())
    latest = repository.query_latest_project_data("proj-1")
    assert latest.analysis_run_id == second.analysis_run_id
    assert latest.analysis_run_id != first.analysis_run_id


def test_diff_flags_module_activated_for_first_time(repository):
    repository.save_analysis_run(
        project_id="proj-1", raw_data={}, results=_results(module_a_ran=False, module_b_ran=True)
    )
    second = repository.save_analysis_run(
        project_id="proj-1", raw_data={}, results=_results(module_a_ran=True, module_b_ran=True)
    )
    assert second.diff_vs_prior is not None
    assert "C1" in second.diff_vs_prior["newly_activated_modules"]
    assert second.diff_vs_prior["newly_activated_modules"]["C1"] == ["module_a"]


def test_diff_flags_forecast_resolved_into_actual(repository):
    repository.save_analysis_run(
        project_id="proj-1",
        raw_data={},
        results=_results(predicted_168h=42.0, actual_168h=None),
    )
    second = repository.save_analysis_run(
        project_id="proj-1",
        raw_data={},
        results=_results(predicted_168h=42.0, actual_168h=45.5),
    )
    resolved = second.diff_vs_prior["resolved_forecasts"]["C1"]
    assert resolved == {"predicted": 42.0, "actual": 45.5}


def test_diff_flags_verdict_moved(repository):
    repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results(verdict="WATCH"))
    second = repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results(verdict="REJECT"))
    change = second.diff_vs_prior["verdict_changes"]["C1"]
    assert change == {"from": "WATCH", "to": "REJECT"}


def test_diff_is_empty_dict_shape_when_nothing_changed(repository):
    repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results())
    second = repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results())
    assert second.diff_vs_prior == {
        "newly_activated_modules": {},
        "resolved_forecasts": {},
        "verdict_changes": {},
    }


def test_diff_is_scoped_per_project_not_global(repository):
    repository.save_project(project_id="proj-2", lot_id="L2", part_number="PN-200", created_by="a.sharma")
    repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results(verdict="REJECT"))
    # proj-2's first-ever run must not diff against proj-1's run.
    run = repository.save_analysis_run(project_id="proj-2", raw_data={}, results=_results(verdict="PASS"))
    assert run.diff_vs_prior is None


# --- log_event / query_events ------------------------------------------------------


def test_log_event_persists_and_is_append_only(repository):
    e1 = repository.log_event(
        project_id="proj-1", account_id="a.sharma", event_type="ingest", payload={"reading_count": 12}
    )
    e2 = repository.log_event(
        project_id="proj-1", account_id="a.sharma", event_type="checkpoint_add", payload={"hour": 24}
    )
    events = repository.query_events("proj-1")
    assert [e.event_id for e in events] == [e1.event_id, e2.event_id]
    assert events[0].payload == {"reading_count": 12}


def test_log_event_rejects_unrecognized_event_type(repository):
    with pytest.raises(ValueError):
        repository.log_event(
            project_id="proj-1", account_id="a.sharma", event_type="edit", payload={}
        )


# --- save_disposition_signoff / query_disposition_signoffs -------------------------


def test_disposition_signoff_persists_and_is_append_only(repository):
    run = repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results())
    repository.save_disposition_signoff(
        project_id="proj-1",
        component_id="C1",
        analysis_run_id=run.analysis_run_id,
        account_id="a.sharma",
        verdict="REJECT",
        rationale="Isolation Forest outlier, corroborated by MCD",
    )
    signoffs = repository.query_disposition_signoffs("proj-1", component_id="C1")
    assert len(signoffs) == 1
    assert signoffs[0].verdict == "REJECT"
    assert signoffs[0].analysis_run_id == run.analysis_run_id


def test_disposition_signoff_rejects_bad_verdict(repository):
    run = repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results())
    with pytest.raises(ValueError):
        repository.save_disposition_signoff(
            project_id="proj-1",
            component_id="C1",
            analysis_run_id=run.analysis_run_id,
            account_id="a.sharma",
            verdict="MAYBE",
            rationale="",
        )


def test_two_distinct_accounts_query_supports_reject_dual_signoff_rule(repository):
    run = repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results())
    repository.save_disposition_signoff(
        project_id="proj-1", component_id="C1", analysis_run_id=run.analysis_run_id,
        account_id="a.sharma", verdict="REJECT", rationale="r1",
    )
    repository.save_disposition_signoff(
        project_id="proj-1", component_id="C1", analysis_run_id=run.analysis_run_id,
        account_id="a.sharma", verdict="REJECT", rationale="r1 again",
    )
    same_account = repository.query_disposition_signoffs("proj-1", component_id="C1")
    assert len({s.account_id for s in same_account}) == 1  # not yet dual sign-off

    repository.save_disposition_signoff(
        project_id="proj-1", component_id="C1", analysis_run_id=run.analysis_run_id,
        account_id="b.rao", verdict="REJECT", rationale="r2",
    )
    all_signoffs = repository.query_disposition_signoffs("proj-1", component_id="C1")
    assert len({s.account_id for s in all_signoffs}) == 2  # dual sign-off now satisfiable


# --- save_confirmed_outcome / query_confirmed_outcomes -----------------------------


def test_confirmed_outcome_persists_without_dual_signoff(repository):
    run = repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results())
    outcome = repository.save_confirmed_outcome(
        project_id="proj-1",
        component_id="C1",
        analysis_run_id=run.analysis_run_id,
        account_id="a.sharma",
        confirmed_outcome="Confirmed Defective",
        note="DPA report #4471",
    )
    assert outcome.confirmed_outcome_id
    assert outcome.confirmed_outcome == "Confirmed Defective"


def test_confirmed_outcome_rejects_bad_value(repository):
    run = repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results())
    with pytest.raises(ValueError):
        repository.save_confirmed_outcome(
            project_id="proj-1",
            component_id="C1",
            analysis_run_id=run.analysis_run_id,
            account_id="a.sharma",
            confirmed_outcome="Maybe Defective",
        )


def test_query_confirmed_outcomes_scoped_by_project_or_global(repository):
    repository.save_project(project_id="proj-2", lot_id="L2", part_number="PN-200", created_by="a.sharma")
    run1 = repository.save_analysis_run(project_id="proj-1", raw_data={}, results=_results())
    run2 = repository.save_analysis_run(project_id="proj-2", raw_data={}, results=_results())
    repository.save_confirmed_outcome(
        project_id="proj-1", component_id="C1", analysis_run_id=run1.analysis_run_id,
        account_id="a.sharma", confirmed_outcome="Confirmed Good",
    )
    repository.save_confirmed_outcome(
        project_id="proj-2", component_id="C1", analysis_run_id=run2.analysis_run_id,
        account_id="a.sharma", confirmed_outcome="Confirmed Defective",
    )
    assert len(repository.query_confirmed_outcomes(project_id="proj-1")) == 1
    assert len(repository.query_confirmed_outcomes()) == 2  # global, for FN/FP rate (E10/5.17)


# --- query_account / query_project / query_projects ---------------------------------


def test_query_account_returns_existing_account(repository):
    account = repository.query_account("a.sharma")
    assert account is not None
    assert account.display_name == "A. Sharma"


def test_query_account_returns_none_for_unknown_id(repository):
    assert repository.query_account("nobody") is None


def test_query_project_returns_existing_project(repository):
    project = repository.query_project("proj-1")
    assert project is not None
    assert project.lot_id == "L1"


def test_query_projects_lists_all_projects_newest_first(repository):
    repository.save_project(project_id="proj-2", lot_id="L2", part_number="PN-200", created_by="a.sharma")
    projects = repository.query_projects()
    assert [p.project_id for p in projects] == ["proj-2", "proj-1"]
