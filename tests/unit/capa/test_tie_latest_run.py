"""Tied created_at: find_latest_run_for_component returns the later-inserted run."""
from datetime import UTC, datetime
from types import SimpleNamespace

from capa import logic
from contracts import AnalysisResults, LotDisposition, RiskAssessment

_T = datetime(2026, 8, 1, tzinfo=UTC)


def _json(verdict):
    return AnalysisResults(
        assessments=[RiskAssessment(component_id="C1", lot_id="L1", verdict=verdict, module_a_rank=0.1,
                                    module_b_rank=0.1, worst_parameter="iddq", module_a_ran=True,
                                    module_b_ran=True, predicted_168h=None, actual_168h=None,
                                    explanation_sentence=None)],
        disposition=LotDisposition(lot_id="L1", status="IN_PROGRESS", pda_result=0.0,
                                   verdict="LOT_ON_TRACK", is_forecast=True),
    ).model_dump_json()


def test_tied_created_at_later_insert_wins(monkeypatch):
    project = SimpleNamespace(project_id="p1", lot_id="L1")
    rows = [SimpleNamespace(analysis_run_id="run-1", results_json=_json("PASS"), created_at=_T),
            SimpleNamespace(analysis_run_id="run-2", results_json=_json("REJECT"), created_at=_T)]
    monkeypatch.setattr(logic, "query_projects", lambda: [project])
    monkeypatch.setattr(logic, "query_project_data", lambda pid: rows)
    _, row, _ = logic.find_latest_run_for_component("C1")
    assert row.analysis_run_id == "run-2"
