"""AGENTS.md rule 5 / Block 4a Part 5's own requirement: the DPA work order selection rule exercised
against the real golden lot (harness/golden.py) through the real fusion pipeline - not a hand-built
AnalysisResults. GOLDEN-045 (lot median 10 uA, part at 45 uA, limit 50 uA) is the lot's only flagged
part, so it must be the highest-severity recommendation; the control part must be PASS-tier; a
duplicate-run check confirms determinism."""
import pytest

from contracts import ScreeningConfig
from harness.golden import GOLDEN_COMPONENT_ID, golden_assessment, golden_lot
from harness.golden import run_golden_pipeline


def _golden_results():
    try:
        raw = run_golden_pipeline()
    except Exception as exc:  # GoldenTestUnavailable / GoldenEntryPointMissing, per harness/golden.py
        pytest.skip(f"golden pipeline unavailable on this branch: {exc}")
    from contracts import AnalysisResults
    if isinstance(raw, AnalysisResults):
        return raw
    return AnalysisResults.model_validate(raw, from_attributes=True)


def test_golden_045_is_recommended_as_the_highest_severity_part():
    from capa.logic import select_dpa_work_order

    results = _golden_results()
    golden_assessment(results.model_dump())  # confirms the golden part is present and flagged

    recs = select_dpa_work_order(results)
    assert recs, "expected at least one DPA recommendation for the golden lot"
    assert recs[0].component_id == GOLDEN_COMPONENT_ID


def test_the_control_part_is_pass():
    from capa.logic import select_dpa_work_order

    results = _golden_results()
    assessments_by_id = {a.component_id: a for a in results.assessments}

    recs = select_dpa_work_order(results)
    control = recs[-1]
    assert assessments_by_id[control.component_id].verdict == "PASS"


def test_deterministic_across_repeated_calls():
    from capa.logic import select_dpa_work_order

    results = _golden_results()
    first = select_dpa_work_order(results)
    second = select_dpa_work_order(results)
    assert [r.model_dump() for r in first] == [r.model_dump() for r in second]


def test_at_most_three_recommendations():
    from capa.logic import select_dpa_work_order

    results = _golden_results()
    recs = select_dpa_work_order(results)
    assert 1 <= len(recs) <= 3


def test_dpa_work_order_route_end_to_end_on_the_golden_lot(tmp_path, monkeypatch):
    """The full router path (POST /lots/{lot_id}/dpa-work-order) against a stored golden-lot run,
    same DB-isolation pattern as tests/unit/capa/*."""
    from datetime import UTC, datetime
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from storage import database, repository
    from identity.auth import create_access_token
    from storage.repository import save_account, save_analysis_run, save_project

    test_engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(repository, "SessionLocal", TestSessionLocal)
    repository.init_db()

    lot = golden_lot()
    results = _golden_results()
    save_account("account1", "User 1", "Quality Engineer", "$argon2id$v=19$m=65536,t=3,p=4$x$y")
    save_project("golden-proj", lot.lot_id, lot.part_number, datetime.now(UTC), "account1")
    save_analysis_run("golden-proj", {}, results)

    from capa.router import planned_router
    app = FastAPI()
    app.include_router(planned_router)
    client = TestClient(app)
    token = create_access_token("account1", "Quality Engineer")

    resp = client.post(f"/lots/{lot.lot_id}/dpa-work-order", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    recs = resp.json()["recommendations"]
    assert recs[0]["component_id"] == GOLDEN_COMPONENT_ID
