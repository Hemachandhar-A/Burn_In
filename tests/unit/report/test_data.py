"""Session P2.7 (E9 steps 1-2): report/data.py assembles everything the PDF/JSON/CSV
report needs from what P2 already owns - storage (persistent project/project_data/
disposition_signoffs), ingestion.store (the interim test_date bridge, CONTRACT_CHANGES.md
2026-09-25 "No field anywhere stores a lot's test date"), and features.compute (recomputed
from raw_data for the delta table, since results_json does not carry per-checkpoint values).

`raw_data` is documented here (and in CONTRACT_CHANGES.md, this session) as
`LotDataset.model_dump(mode="json")` - no other pinned shape exists for it yet.
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
    return {
        "per_component": {
            cid: {
                "verdict": v, "module_a_ran": True, "module_b_ran": False,
                "predicted_168h": None, "actual_168h": None,
                "explanation_sentence": f"{cid} flagged by robust z-score." if v != "PASS" else None,
            }
            for cid, v in verdicts.items()
        },
        "lot_disposition": {
            "pda_result": 0.02, "verdict": "LOT_ON_TRACK", "is_forecast": True, "status": "IN_PROGRESS",
        },
    }


def _seed_project(repository, project_id="proj-1", lot_id="L1", part_number="PN-100"):
    repository.save_project(project_id=project_id, lot_id=lot_id, part_number=part_number, created_by="a.sharma")


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


def test_pda_not_available_when_lot_disposition_absent(repository):
    _seed_project(repository)
    lot = _lot_dataset()
    results = _results()
    del results["lot_disposition"]
    repository.save_analysis_run(project_id="proj-1", raw_data=lot.model_dump(mode="json"), results=results)

    from report import data

    report = data.build_report_data("proj-1")
    assert report.pda_available is False
    assert report.pda_result is None
    assert report.overall_disposition is None


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
