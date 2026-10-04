"""Session P2.7 (E9 steps 1-2): report/data.py assembles everything the PDF/JSON/CSV
report needs from what P2 already owns - storage (persistent project/project_data/
disposition_signoffs), ingestion.store (the interim test_date bridge, CONTRACT_CHANGES.md
2026-09-25 "No field anywhere stores a lot's test date"), and features.compute (recomputed
from raw_data for the delta table, since results_json does not carry per-checkpoint values).

`raw_data` is documented here (and in CONTRACT_CHANGES.md, this session) as
`LotDataset.model_dump(mode="json")` - no other pinned shape exists for it yet.
"""
import importlib
from datetime import UTC, datetime

import pytest

from contracts import AnalysisResults, LotDisposition, RiskAssessment


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
    return repository


def _lot_dataset(lot_id="L1", part_number="PN-100", status="IN_PROGRESS", account_id="a.sharma"):
    from contracts import LotDataset, Reading

    readings = []
    for i in range(3):
        cid = f"C{i}"
        readings.append(Reading(
            component_id=cid, lot_id=lot_id, part_number=part_number, manufacturer="Acme",
            date_code="2450", parameter="iddq", checkpoint_hour=0.0, value=10.0 + i, unit="uA",
        ))
        readings.append(Reading(
            component_id=cid, lot_id=lot_id, part_number=part_number, manufacturer="Acme",
            date_code="2450", parameter="iddq", checkpoint_hour=24.0, value=12.0 + i, unit="uA",
        ))
    return LotDataset(lot_id=lot_id, part_number=part_number, status=status, readings=readings, account_id=account_id)


def _results(verdicts=None):
    verdicts = verdicts or {"C0": "PASS", "C1": "WATCH", "C2": "REJECT"}
    return AnalysisResults(
        assessments=[
            RiskAssessment(
                component_id=cid, lot_id="L1", verdict=v, module_a_rank=0.5, module_b_rank=0.5,
                worst_parameter="iddq", module_a_ran=True, module_b_ran=False,
                predicted_168h=None, actual_168h=None,
                explanation_sentence=f"{cid} flagged by robust z-score." if v != "PASS" else None,
            )
            for cid, v in verdicts.items()
        ],
        disposition=LotDisposition(
            lot_id="L1", status="IN_PROGRESS", pda_result=0.02, verdict="LOT_ON_TRACK", is_forecast=True,
        ),
    )


def _seed_project(repository, project_id="proj-1", lot_id="L1", part_number="PN-100"):
    repository.save_project(
        project_id=project_id, lot_id=lot_id, part_number=part_number,
        test_date=datetime(2026, 8, 1, tzinfo=UTC), created_by="a.sharma",
    )


# --- build_report_data: metadata ---------------------------------------------------


def test_missing_project_raises_lookup_error(repository):
    from report import data

    with pytest.raises(LookupError):
        data.build_report_data("does-not-exist")


def test_no_analysis_runs_yet_raises_lookup_error(repository):
    _seed_project(repository)
    from report import data

    with pytest.raises(LookupError):
        data.build_report_data("proj-1")


def test_metadata_pulled_from_raw_data_and_project(repository):
    _seed_project(repository)
    lot = _lot_dataset()
    repository.save_analysis_run(project_id="proj-1", raw_data=lot.model_dump(mode="json"), results=_results())

    from report import data

    report = data.build_report_data("proj-1")
    assert report.project_id == "proj-1"
    assert report.lot_id == "L1"
    assert report.part_number == "PN-100"
    assert report.manufacturer == "Acme"
    assert report.date_code == "2450"
    assert report.lot_status == "IN_PROGRESS"
    assert report.report_reference_id.startswith("RPT-")


def test_test_date_pulled_from_ingestion_store_bridge(repository):
    _seed_project(repository)
    lot = _lot_dataset()
    repository.save_analysis_run(project_id="proj-1", raw_data=lot.model_dump(mode="json"), results=_results())

    from ingestion import store

    store.clear()
    store.put("L1", lot, test_date="2026-08-01")

    from report import data

    report = data.build_report_data("proj-1")
    assert report.test_date == "2026-08-01"
    store.clear()


def test_test_date_none_when_not_bridged(repository):
    _seed_project(repository)
    lot = _lot_dataset()
    repository.save_analysis_run(project_id="proj-1", raw_data=lot.model_dump(mode="json"), results=_results())

    from ingestion import store

    store.clear()

    from report import data

    report = data.build_report_data("proj-1")
    assert report.test_date is None


# --- quantity screened/flagged + PDA -------------------------------------------------


def test_quantity_screened_and_flagged(repository):
    _seed_project(repository)
    lot = _lot_dataset()
    repository.save_analysis_run(project_id="proj-1", raw_data=lot.model_dump(mode="json"), results=_results())

    from report import data

    report = data.build_report_data("proj-1")
    assert report.quantity_screened == 3
    assert report.quantity_flagged == 2  # C1 WATCH, C2 REJECT


def test_pda_result_available_when_lot_disposition_present(repository):
    _seed_project(repository)
    lot = _lot_dataset()
    repository.save_analysis_run(project_id="proj-1", raw_data=lot.model_dump(mode="json"), results=_results())

    from report import data

    report = data.build_report_data("proj-1")
    assert report.pda_available is True
    assert report.pda_result == 0.02
    assert report.overall_disposition == "LOT_ON_TRACK"
    assert report.is_forecast is True


# --- delta table (recomputed via features.compute) -----------------------------------


def test_delta_table_has_one_row_per_component_parameter_pair(repository):
    _seed_project(repository)
    lot = _lot_dataset()
    repository.save_analysis_run(project_id="proj-1", raw_data=lot.model_dump(mode="json"), results=_results())

    from report import data

    report = data.build_report_data("proj-1")
    assert len(report.delta_table) == 3
    by_component = {row.component_id: row for row in report.delta_table}
    assert by_component["C1"].delta_24h == pytest.approx(2.0)
    assert by_component["C1"].verdict == "WATCH"


# --- flagged parts ---------------------------------------------------------------------


def test_flagged_parts_excludes_pass_verdicts(repository):
    _seed_project(repository)
    lot = _lot_dataset()
    repository.save_analysis_run(project_id="proj-1", raw_data=lot.model_dump(mode="json"), results=_results())

    from report import data

    report = data.build_report_data("proj-1")
    flagged_ids = {p.component_id for p in report.flagged_parts}
    assert flagged_ids == {"C1", "C2"}


def test_flagged_part_includes_disposition_history(repository):
    _seed_project(repository)
    lot = _lot_dataset()
    run = repository.save_analysis_run(project_id="proj-1", raw_data=lot.model_dump(mode="json"), results=_results())
    repository.save_disposition_signoff(
        project_id="proj-1", component_id="C2", analysis_run_id=run.analysis_run_id,
        account_id="a.sharma", verdict="REJECT", rationale="confirmed defect",
    )

    from report import data

    report = data.build_report_data("proj-1")
    c2 = next(p for p in report.flagged_parts if p.component_id == "C2")
    assert len(c2.disposition_history) == 1
    assert c2.disposition_history[0]["verdict"] == "REJECT"


# --- analysis history ------------------------------------------------------------------


def test_analysis_history_single_run_says_no_revisions(repository):
    _seed_project(repository)
    lot = _lot_dataset()
    repository.save_analysis_run(project_id="proj-1", raw_data=lot.model_dump(mode="json"), results=_results())

    from report import data

    report = data.build_report_data("proj-1")
    assert len(report.analysis_history) == 1
    assert "no revision" in report.analysis_history[0].what_changed.lower() \
        or "initial" in report.analysis_history[0].what_changed.lower()
    assert report.analysis_history_truncated is False


def test_analysis_history_second_run_describes_verdict_change(repository):
    _seed_project(repository)
    lot = _lot_dataset()
    repository.save_analysis_run(
        project_id="proj-1", raw_data=lot.model_dump(mode="json"),
        results=_results(verdicts={"C0": "PASS"}),
    )
    repository.save_analysis_run(
        project_id="proj-1", raw_data=lot.model_dump(mode="json"),
        results=_results(verdicts={"C0": "REJECT"}),
    )

    from report import data

    report = data.build_report_data("proj-1")
    assert len(report.analysis_history) == 2
    assert "C0" in report.analysis_history[1].what_changed


def test_analysis_history_capped_at_ten_with_truncation_note(repository):
    _seed_project(repository)
    lot = _lot_dataset()
    for _ in range(12):
        repository.save_analysis_run(project_id="proj-1", raw_data=lot.model_dump(mode="json"), results=_results())

    from report import data

    report = data.build_report_data("proj-1")
    assert len(report.analysis_history) == 10
    assert report.analysis_history_truncated is True


def test_analysis_history_trigger_derived_from_preceding_event(repository):
    _seed_project(repository)
    lot = _lot_dataset()
    repository.log_event("proj-1", "a.sharma", "ingest", {"lot_id": "L1"})
    repository.save_analysis_run(project_id="proj-1", raw_data=lot.model_dump(mode="json"), results=_results())

    from report import data

    report = data.build_report_data("proj-1")
    assert report.analysis_history[0].trigger == "ingest"


def test_methodology_sentence_states_only_what_the_live_pipeline_executes():
    """fusion/pipeline.py calls module_a_detect(frames) with no prior_frames, so no Isolation Forest is
    fitted and its score is 0.0 on the live path; the sentence must not say it contributes."""
    from report.data import _METHODOLOGY_SUMMARY as text

    assert "pooled cross-lot Isolation Forest score" not in text
    assert "combining a robust per-parameter z-score, Minimum Covariance Determinant (MCD) distance and an ECOD outlier score" in text
    assert "does not contribute in this build" in text
    assert "corroboration from an explainable detector (z-score or MCD)" in text


def test_methodology_sentence_in_absolute_mode_names_only_the_legs_that_score(monkeypatch):
    """demo-v2: the default is absolute scoring. The z-score leg (and the MCD leg for lots of 77+ parts) score; ECOD and the
    Isolation Forest do NOT contribute; severity is an index, not a probability."""
    from report.data import methodology_summary

    monkeypatch.delenv("MODULE_A_SCORING", raising=False)
    text = methodology_summary()
    assert text == methodology_summary("absolute")
    assert "combining a robust per-parameter z-score, Minimum Covariance Determinant (MCD) distance and an ECOD outlier score" not in text
    assert "ECOD" in text and "not used to score" in text
    assert "Isolation Forest" in text and "does not contribute" in text
    assert "tail probabilities" in text and "77 or more parts" in text
    assert "index, not a probability" in text
    assert "one in" not in text.lower()


def test_methodology_sentence_in_rank_mode_is_the_legacy_text(monkeypatch):
    from report.data import _METHODOLOGY_SUMMARY, methodology_summary

    monkeypatch.setenv("MODULE_A_SCORING", "rank")
    assert methodology_summary() == _METHODOLOGY_SUMMARY


def test_report_data_carries_the_mode_aware_methodology(repository, monkeypatch):
    from report import data

    for mode in ("rank", "absolute"):
        monkeypatch.setenv("MODULE_A_SCORING", mode)
        _seed_project(repository, project_id=f"proj-{mode}", lot_id=f"L-{mode}")
        repository.save_analysis_run(project_id=f"proj-{mode}", raw_data=_lot_dataset(lot_id=f"L-{mode}").model_dump(mode="json"),
                                     results=_results())
        assert data.build_report_data(f"proj-{mode}").methodology_summary == data.methodology_summary(mode)


# --- Session I3: what the PDF says about the FN:FP control and Module B's role on a finished lot ------------------------

def test_absolute_methodology_says_what_the_cost_ratio_does(monkeypatch):
    from report.data import methodology_summary

    monkeypatch.delenv("MODULE_A_SCORING", raising=False)
    text = methodology_summary()
    assert "FN:FP cost ratio (which selects Module A's REVIEW and REJECT cut-offs)" in text
    assert "used below" not in text


def _finished(cutoffs=None, notes=None):
    r = _results({"C0": "PASS", "C1": "WATCH", "C2": "REJECT"})
    return r.model_copy(update={
        "disposition": LotDisposition(lot_id="L1", status="COMPLETE", pda_result=0.02, verdict="HOLD", is_forecast=False),
        "module_a_cutoffs": cutoffs if cutoffs is not None else {"review": 2.956, "reject": 3.419},
        "module_b_advisory_notes": notes or {}})


def test_analysis_note_quotes_the_cutoffs_the_analysis_used_and_module_bs_role(monkeypatch):
    from report.data import analysis_settings_note

    monkeypatch.delenv("MODULE_B_FINISHED_LOT_ROLE", raising=False)
    note = analysis_settings_note(_finished({"review": 1.7234, "reject": 2.4522}, {"C0": "n"}))
    assert "REVIEW at s >= 1.72" in note and "REJECT at s >= 2.45" in note and "FN:FP cost ratio setting" in note
    assert "did not change any part's verdict" in note and "1 part carries an information note" in note
    assert "Module A" in note


@pytest.mark.parametrize("role,phrase", [("current", "counts toward"), ("tiered", "REVIEW"), ("off", "not used")])
def test_analysis_note_per_role(monkeypatch, role, phrase):
    from report.data import analysis_settings_note

    monkeypatch.setenv("MODULE_B_FINISHED_LOT_ROLE", role)
    assert phrase in analysis_settings_note(_finished())


def test_analysis_note_is_empty_for_an_in_progress_lot_without_cutoffs():
    from report.data import analysis_settings_note

    assert analysis_settings_note(_results()) == ""


def test_report_data_carries_the_analysis_note(repository):
    from report import data

    _seed_project(repository)
    repository.save_analysis_run(project_id="proj-1", raw_data=_lot_dataset().model_dump(mode="json"), results=_finished())
    assert data.build_report_data("proj-1").analysis_settings_note == data.analysis_settings_note(_finished())
