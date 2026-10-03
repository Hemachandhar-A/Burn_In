"""E9 step 3: render the report template to PDF with `fpdf2` - resolved over `weasyprint`
per IMPLEMENTATION_PLAN.md Part 3, to avoid a system-dependency (Pango/Cairo) install risk.
Covers E9 step 1's field list plus step 2's Analysis History section.
"""
from fpdf import FPDF

from explain.units import scale_for_display
from report.data import ReportData

_TITLE_SIZE = 16
_HEADING_SIZE = 12
_BODY_SIZE = 10
_SMALL_SIZE = 8
# Delta table column widths (mm). The Component column fits a 22-character ID at the small font (a 22-character ID such
# as DEMO-COMPLETE-01-0004 overprinted the Parameter column at the previous width of 22); the sum stays within the
# 190 mm printable width of an A4 page.
_DELTA_WIDTHS = [42, 20, 12, 14, 14, 14, 14, 14, 14, 14, 18]


def _heading(doc: FPDF, text: str) -> None:
    doc.ln(3)
    doc.set_font("Helvetica", style="B", size=_HEADING_SIZE)
    doc.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
    doc.set_font("Helvetica", size=_BODY_SIZE)


def _field(doc: FPDF, label: str, value: str) -> None:
    doc.set_font("Helvetica", style="B", size=_BODY_SIZE)
    doc.cell(45, 6, f"{label}:", new_x="RIGHT", new_y="TOP")
    doc.set_font("Helvetica", size=_BODY_SIZE)
    doc.multi_cell(0, 6, value, new_x="LMARGIN", new_y="NEXT")


def render_pdf(report: ReportData) -> bytearray:
    doc = FPDF()
    doc.set_auto_page_break(auto=True, margin=15)
    doc.add_page()

    doc.set_font("Helvetica", style="B", size=_TITLE_SIZE)
    doc.cell(0, 10, "Lot Screening Report", new_x="LMARGIN", new_y="NEXT")
    doc.set_font("Helvetica", size=_BODY_SIZE)

    _field(doc, "Report Reference ID", report.report_reference_id)
    _field(doc, "Generated", report.generated_at.isoformat())
    _field(doc, "Part Number", report.part_number)
    _field(doc, "Lot ID", report.lot_id)
    _field(doc, "Date Code", report.date_code or "unavailable")
    _field(doc, "Manufacturer", report.manufacturer or "unavailable")
    _field(doc, "Test Date", report.test_date or "not recorded at ingestion")
    _field(doc, "Lot Status", report.lot_status)

    _heading(doc, "Methodology")
    doc.multi_cell(0, 5, report.methodology_summary, new_x="LMARGIN", new_y="NEXT")

    _heading(doc, "Summary")
    _field(doc, "Quantity Screened", str(report.quantity_screened))
    _field(doc, "Quantity Flagged", str(report.quantity_flagged))
    if report.pda_available:
        pda_label = "PDA Result (forecast)" if report.is_forecast else "PDA Result"
        _field(doc, pda_label, f"{report.pda_result:.4f}")
        _field(doc, "Overall Lot Disposition", report.overall_disposition or "unavailable")
    else:
        _field(
            doc, "PDA Result / Lot Disposition",
            "Not yet available - the fusion/disposition stage has not run for this analysis "
            "record. This is a disclosed gap, not a computed zero.",
        )

    _heading(doc, "Delta-Data Table")
    if not report.delta_table:
        doc.multi_cell(0, 5, "No delta data available for this run.", new_x="LMARGIN", new_y="NEXT")
    else:
        doc.set_font("Helvetica", style="B", size=_SMALL_SIZE)
        headers = ["Component", "Param", "Unit", "0h", "24h", "d24h", "96h", "d96h", "168h", "d168h", "Verdict"]
        widths = _DELTA_WIDTHS
        for h, w in zip(headers, widths):
            doc.cell(w, 6, h, border=1)
        doc.ln()
        doc.set_font("Helvetica", size=_SMALL_SIZE)
        for row in report.delta_table:

            # One display unit per row (the prefix that suits its largest value, explain/units.py), shown in the
            # Unit column, so every cell of the row reads in the unit its column says.
            magnitudes = [abs(v) for v in (row.value_0h, row.value_24h, row.value_96h, row.value_168h) if v is not None]
            _, unit_label, factor = scale_for_display(max(magnitudes, default=0.0), row.unit)

            def fmt(v, factor=factor):
                return "" if v is None else f"{v / factor:.4g}"

            cells = [
                row.component_id, row.parameter, unit_label or "-", fmt(row.value_0h), fmt(row.value_24h),
                fmt(row.delta_24h), fmt(row.value_96h), fmt(row.delta_96h),
                fmt(row.value_168h), fmt(row.delta_168h), row.verdict or "-",
            ]
            for c, w in zip(cells, widths):
                doc.cell(w, 6, str(c), border=1)
            doc.ln()

    _heading(doc, "Flagged Parts - Explanation and Disposition")
    if not report.flagged_parts:
        doc.multi_cell(0, 5, "No parts flagged in this analysis run.", new_x="LMARGIN", new_y="NEXT")
    else:
        for part in report.flagged_parts:
            doc.set_font("Helvetica", style="B", size=_BODY_SIZE)
            doc.cell(0, 6, f"{part.component_id} ({part.parameter}) - {part.verdict}", new_x="LMARGIN", new_y="NEXT")
            doc.set_font("Helvetica", size=_BODY_SIZE)
            doc.multi_cell(
                0, 5,
                f"Explanation: {part.explanation or 'not yet available for this analysis record.'}",
                new_x="LMARGIN", new_y="NEXT",
            )
            if part.disposition_history:
                for d in part.disposition_history:
                    doc.multi_cell(
                        0, 5,
                        f"  Disposition: {d['verdict']} by {d['account_id']} - {d['rationale']}",
                        new_x="LMARGIN", new_y="NEXT",
                    )
            else:
                doc.multi_cell(0, 5, "  Disposition: pending reviewer sign-off.", new_x="LMARGIN", new_y="NEXT")
            doc.ln(1)

    _heading(doc, "Analysis History")
    for entry in report.analysis_history:
        doc.multi_cell(
            0, 5,
            f"{entry.timestamp.isoformat()} [{entry.analysis_run_id}] triggered by {entry.trigger}: "
            f"{entry.what_changed}",
            new_x="LMARGIN", new_y="NEXT",
        )
    if report.analysis_history_truncated:
        doc.set_font("Helvetica", style="I", size=_SMALL_SIZE)
        doc.multi_cell(
            0, 5,
            "Showing the most recent 10 runs. See the JSON export or the History screen for the full record.",
            new_x="LMARGIN", new_y="NEXT",
        )
        doc.set_font("Helvetica", size=_BODY_SIZE)

    _heading(doc, "Reviewer / Sign-off")
    if not report.reviewer_entries:
        doc.multi_cell(0, 5, "No disposition sign-offs recorded yet for this project.", new_x="LMARGIN", new_y="NEXT")
    else:
        for entry in report.reviewer_entries:
            doc.multi_cell(
                0, 5,
                f"{entry['account_id']} - {entry['verdict']} on {entry['component_id']} "
                f"({entry['timestamp'].isoformat()}): {entry['rationale']}",
                new_x="LMARGIN", new_y="NEXT",
            )

    return doc.output()
