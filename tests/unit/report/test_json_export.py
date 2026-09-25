"""E9 step 5: export the same structured content as JSON alongside the PDF/CSV - built
directly from `report.data.ReportData`, not a separately maintained copy.
"""
from datetime import UTC, datetime

from report import json_export
from report.data import AnalysisHistoryEntry, DeltaRow, FlaggedPart, ReportData


def _report():
    return ReportData(
        report_reference_id="RPT-ABC123", generated_at=datetime(2026, 9, 25, tzinfo=UTC),
        project_id="proj-1", lot_id="L1", part_number="PN-100", manufacturer="Acme",
        date_code="2450", test_date="2026-08-01", lot_status="IN_PROGRESS",
        methodology_summary="...", quantity_screened=3, quantity_flagged=1,
        pda_available=True, pda_result=0.02, overall_disposition="LOT_ON_TRACK", is_forecast=True,
        latest_analysis_run_id="run-1",
        delta_table=[DeltaRow(
            component_id="C0", parameter="iddq", value_0h=10.0, value_24h=12.0, delta_24h=2.0,
            value_96h=None, delta_96h=None, value_168h=None, delta_168h=None, verdict="WATCH",
        )],
        flagged_parts=[FlaggedPart(component_id="C0", parameter="iddq", verdict="WATCH", explanation="z-score high")],
        analysis_history=[AnalysisHistoryEntry(
            analysis_run_id="run-1", timestamp=datetime(2026, 9, 25, tzinfo=UTC),
            trigger="ingest", what_changed="Initial analysis run - no prior revision to compare.",
        )],
        analysis_history_truncated=False,
        reviewer_entries=[],
    )


def test_to_json_dict_is_json_serializable_and_round_trips_key_fields():
    import json

    payload = json_export.to_json_dict(_report())
    text = json.dumps(payload)
    parsed = json.loads(text)
    assert parsed["report_reference_id"] == "RPT-ABC123"
    assert parsed["lot_id"] == "L1"
    assert parsed["delta_table"][0]["component_id"] == "C0"
    assert parsed["flagged_parts"][0]["verdict"] == "WATCH"
    assert parsed["analysis_history"][0]["trigger"] == "ingest"
