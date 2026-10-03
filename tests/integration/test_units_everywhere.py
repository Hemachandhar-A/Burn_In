"""F24 Part 3: units on every number a person reads - T14 (golden sentence), T16 (PDF text), T17 (old stored JSON)."""
import csv
import io
import re
import zlib

import pytest
from argon2 import PasswordHasher
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db(tmp_path, monkeypatch):
    from ingestion import store
    from storage import database, repository

    engine = create_engine(f"sqlite:///{tmp_path / 'units.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    monkeypatch.setattr(repository, "SessionLocal", session_local)
    repository.init_db()
    store.clear()
    repository.save_account("a.sharma", "A. Sharma", "Quality Engineer", PasswordHasher().hash("1234"))
    yield
    store.clear()


def _pdf_text(pdf: bytes) -> str:
    """Text of an fpdf2 document without a renderer: inflate each content stream and join the strings drawn by the
    Tj/TJ operators (fpdf2 writes core-font text as `(..) Tj`)."""
    out = []
    for raw in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, flags=re.S):
        try:
            data = zlib.decompress(raw)
        except zlib.error:
            data = raw
        for chunk in re.findall(rb"\((.*?)(?<!\\)\)\s*Tj", data, flags=re.S):
            out.append(chunk.decode("latin-1").replace("\\(", "(").replace("\\)", ")"))
    return "\n".join(out)


def _upload_golden(client, headers):
    from harness.golden import golden_lot

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["component_id", "parameter", "checkpoint_hour", "value", "unit"])
    for r in golden_lot().readings:
        w.writerow([r.component_id, r.parameter, r.checkpoint_hour, r.value, r.unit])
    up = client.post("/lots", headers=headers, files={"file": ("g.csv", buf.getvalue().encode(), "text/csv")},
                     data={"lot_id": "GOLDEN-U", "part_number": "PN-GOLDEN", "manufacturer": "GOLDEN-MFR",
                           "date_code": "2601", "account_id": "a.sharma"})
    assert up.status_code == 200, up.text


@pytest.fixture
def golden(db):
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    token = client.post("/auth/login", json={"account_id": "a.sharma", "pin": "1234"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    _upload_golden(client, headers)
    return client, headers


def test_t14_golden_sentence_has_a_unit_and_a_readable_magnitude(golden):
    from harness.golden import GOLDEN_COMPONENT_ID

    client, headers = golden
    part = client.get(f"/parts/{GOLDEN_COMPONENT_ID}", headers=headers, params={"lot_id": "GOLDEN-U"}).json()
    sentence = part["explanation_sentence"]
    print("golden sentence:", sentence)
    # leakage is normalised to nA at upload (10000 nA / 45000 nA); a person reads 10 uA and 45 uA
    assert "median = 10 uA" in sentence and "value = 45 uA" in sentence
    assert "10000" not in sentence and "45000" not in sentence
    explanation = part["explanation"]
    assert all(row["unit"] for row in explanation["zscore_table"])
    assert {p["unit"] for p in explanation["trajectory"]} == {"nA"}
    assert part["module_b"]["unit"] == "nA"


def test_t16_pdf_text_contains_the_unit_tokens(golden):
    from report.data import build_report_data
    from report.pdf import render_pdf
    from storage import repository

    project = next(p for p in repository.query_projects() if p.lot_id == "GOLDEN-U")
    report = build_report_data(project.project_id)
    assert {row.unit for row in report.delta_table} == {"uA", "nA", "ns"}
    text = _pdf_text(bytes(render_pdf(report)))
    print("PDF unit tokens present:", [t for t in ("Unit", "uA", "nA", "ns") if t in text])
    assert "Unit" in text
    # leakage (10000 nA) is shown with the automatic prefix, as uA; iddq is uA, prop_delay ns
    for token in ("uA", "ns"):
        assert re.search(rf"(^|\n){token}($|\n)", text), f"unit token {token} missing from the PDF text"
    assert "10 uA" in text and "45 uA" in text  # the flagged part's sentence
    assert "None" not in text and "undefined" not in text


def test_t17_old_stored_results_without_the_new_fields_still_parse_and_render():
    from contracts import AnalysisResults, ModuleBResult, PartExplanation, TrajectoryPoint, ZScoreTableRow
    from explain.text import explanation_sentence
    from explain.models import ZScoreRow
    from report.data import DeltaRow
    from report.pdf import render_pdf

    assert TrajectoryPoint.model_validate({"checkpoint_hour": 24, "value": 1.0}).unit is None
    assert ZScoreTableRow.model_validate({"parameter": "iddq", "value": 1.0, "lot_median": 1.0, "z": 0.1}).unit is None
    old_b = {"component_id": "c", "lot_id": "l", "parameter": "iddq", "predicted_168h": None, "interval_lower": None,
             "interval_upper": None, "physics_baseline_prediction": None, "physics_disagreement_gap": None,
             "drift_rate": None, "exceeds_safety_slope": None, "safety_slope": None,
             "lower_bound_exceeds_safety_slope": None, "forecast_unavailable": True}
    b = ModuleBResult.model_validate(old_b)
    assert b.unit is None and b.unavailable_reason is None
    old_expl = '{"zscore_table": [{"parameter": "iddq", "value": 12.5, "lot_median": 10.0, "z": 2.0}], "trajectory": [{"checkpoint_hour": 0, "value": 9.0}]}'
    assert PartExplanation.model_validate_json(old_expl).zscore_table[0].unit is None
    # a sentence for a unitless row keeps the plain numbers (nothing guessed, nothing "None")
    s = explanation_sentence("c1", zscore_row=ZScoreRow(parameter="iddq", value=45.0, lot_median=10.0, z=4.0))
    assert "median = 10, value = 45" in s and "None" not in s
    # and the PDF renders a row with no unit
    from datetime import UTC, datetime

    from report.data import ReportData
    report = ReportData(
        report_reference_id="R", generated_at=datetime(2026, 10, 3, tzinfo=UTC), project_id="p", lot_id="L",
        part_number="PN", manufacturer=None, date_code=None, test_date=None, lot_status="COMPLETE",
        methodology_summary="m", quantity_screened=1, quantity_flagged=0, pda_available=False, pda_result=None,
        overall_disposition=None, is_forecast=None, latest_analysis_run_id="r",
        delta_table=[DeltaRow(component_id="C", parameter="iddq", value_0h=10.0, value_24h=11.0, delta_24h=1.0,
                              value_96h=None, delta_96h=None, value_168h=None, delta_168h=None, verdict="PASS")],
        flagged_parts=[], analysis_history=[], analysis_history_truncated=False, reviewer_entries=[],
    )
    text = _pdf_text(bytes(render_pdf(report)))
    assert "None" not in text and "10" in text


def test_t16_pdf_shows_nanoamps_for_a_nanoamp_scale_row():
    from datetime import UTC, datetime

    from report.data import DeltaRow, ReportData
    from report.pdf import render_pdf

    report = ReportData(
        report_reference_id="R", generated_at=datetime(2026, 10, 3, tzinfo=UTC), project_id="p", lot_id="L",
        part_number="PN", manufacturer=None, date_code=None, test_date=None, lot_status="COMPLETE",
        methodology_summary="m", quantity_screened=1, quantity_flagged=0, pda_available=False, pda_result=None,
        overall_disposition=None, is_forecast=None, latest_analysis_run_id="r",
        delta_table=[DeltaRow(component_id="C", parameter="leakage", value_0h=5.2, value_24h=5.6, delta_24h=0.4,
                              value_96h=None, delta_96h=None, value_168h=None, delta_168h=None, verdict="PASS", unit="nA")],
        flagged_parts=[], analysis_history=[], analysis_history_truncated=False, reviewer_entries=[],
    )
    text = _pdf_text(bytes(render_pdf(report)))
    assert re.search(r"(^|\n)nA($|\n)", text) and "5.2" in text
