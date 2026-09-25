"""E9 step 3: render the report template to PDF with fpdf2 (resolved over weasyprint,
IMPLEMENTATION_PLAN.md Part 3 - no system-dependency install risk).
"""
from datetime import UTC, datetime

from report import pdf as report_pdf
from report.data import AnalysisHistoryEntry, DeltaRow, FlaggedPart, ReportData


def _report(**overrides):
    defaults = {
        "report_reference_id": "RPT-ABC123", "generated_at": datetime(2026, 9, 25, tzinfo=UTC),
        "project_id": "proj-1", "lot_id": "L1", "part_number": "PN-100", "manufacturer": "Acme",
        "date_code": "2450", "test_date": "2026-08-01", "lot_status": "IN_PROGRESS",
        "methodology_summary": "Two modules were used to screen this lot.",
        "quantity_screened": 3, "quantity_flagged": 1,
        "pda_available": True, "pda_result": 0.02, "overall_disposition": "LOT_ON_TRACK", "is_forecast": True,
        "latest_analysis_run_id": "run-1",
        "delta_table": [DeltaRow(
            component_id="C0", parameter="iddq", value_0h=10.0, value_24h=12.0, delta_24h=2.0,
            value_96h=None, delta_96h=None, value_168h=None, delta_168h=None, verdict="WATCH",
        )],
        "flagged_parts": [FlaggedPart(component_id="C0", parameter="iddq", verdict="WATCH", explanation="z-score high")],
        "analysis_history": [AnalysisHistoryEntry(
            analysis_run_id="run-1", timestamp=datetime(2026, 9, 25, tzinfo=UTC),
            trigger="ingest", what_changed="Initial analysis run - no prior revision to compare.",
        )],
        "analysis_history_truncated": False,
        "reviewer_entries": [{
            "component_id": "C0", "account_id": "a.sharma", "verdict": "ACCEPT",
            "rationale": "within limits", "timestamp": datetime(2026, 9, 25, tzinfo=UTC),
        }],
    }
    defaults.update(overrides)
    return ReportData(**defaults)


def test_render_pdf_returns_valid_pdf_bytes():
    out = report_pdf.render_pdf(_report())
    assert bytes(out[:5]) == b"%PDF-"
    assert len(out) > 500


def test_render_pdf_handles_empty_delta_table_and_no_flags():
    report = _report(delta_table=[], flagged_parts=[], quantity_flagged=0, reviewer_entries=[])
    out = report_pdf.render_pdf(report)
    assert bytes(out[:5]) == b"%PDF-"


def test_render_pdf_handles_unavailable_pda():
    report = _report(pda_available=False, pda_result=None, overall_disposition=None, is_forecast=None)
    out = report_pdf.render_pdf(report)
    assert bytes(out[:5]) == b"%PDF-"


def test_render_pdf_handles_truncated_history_note():
    history = [
        AnalysisHistoryEntry(
            analysis_run_id=f"run-{i}", timestamp=datetime(2026, 9, i + 1, tzinfo=UTC),
            trigger="analysis_run", what_changed="No revision from the prior run.",
        )
        for i in range(10)
    ]
    report = _report(analysis_history=history, analysis_history_truncated=True)
    out = report_pdf.render_pdf(report)
    assert bytes(out[:5]) == b"%PDF-"
