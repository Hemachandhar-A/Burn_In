"""Session I2a: the delta table's Component column is wide enough for a long component ID (DISCLOSURES #34)."""
from fpdf import FPDF

from report import pdf as report_pdf
from report.data import DeltaRow
from tests.unit.report.test_pdf import _report


def test_component_column_fits_a_22_character_id_and_the_table_fits_the_page():
    doc = FPDF()
    doc.set_font("Helvetica", size=report_pdf._SMALL_SIZE)
    longest = "DEMO-COMPLETE-01-0004" + "x"
    assert doc.get_string_width(longest) + 2 * doc.c_margin <= report_pdf._DELTA_WIDTHS[0]
    assert sum(report_pdf._DELTA_WIDTHS) <= doc.w - 2 * doc.l_margin


def test_param_and_verdict_columns_fit_their_longest_text():
    doc = FPDF()
    doc.set_font("Helvetica", style="B", size=report_pdf._SMALL_SIZE)
    for text, col in (("prop_delay", 1), ("REJECT", 10),):
        assert doc.get_string_width(text) + 2 * doc.c_margin <= report_pdf._DELTA_WIDTHS[col], text


def test_pdf_with_long_ids_renders():
    row = DeltaRow(component_id="DEMO-COMPLETE-01-0004", parameter="prop_delay", value_0h=3.4, value_24h=3.5,
                   delta_24h=0.1, value_96h=3.7, delta_96h=0.3, value_168h=4.2, delta_168h=0.8, verdict="REJECT")
    out = report_pdf.render_pdf(_report(delta_table=[row]))
    assert bytes(out[:5]) == b"%PDF-"
