import json
import uuid as uuid_lib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch
from fusion.router import router as fusion_router
from identity.router import router as identity_router
from identity.auth import create_access_token
from storage import repository
from datetime import datetime, UTC

app = FastAPI()
app.include_router(fusion_router)
app.include_router(identity_router)
client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    """Each test points fusion/router.py's storage calls at its own temp SQLite file,
    same pattern as tests/integration/test_golden_module_a.py:25-37 - monkeypatching
    engine/SessionLocal in place works across every module that imports storage.repository's
    functions directly (fusion/router.py, capa/, identity/), unlike importlib.reload which only
    updates names bound at reload time.
    """
    from storage import database
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    test_engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(repository, "SessionLocal", TestSessionLocal)

    repository.init_db()


import uuid
def test_get_lot_summary_no_live_recompute():
    # Setup test data
    uid = str(uuid.uuid4())
    lot_id = f"test-lot-no-recompute-{uid}"
    tester_id = f"tester-{uid}"
    repository.save_account(tester_id, "Tester", "operator", "hash")
    repository.save_project(lot_id, lot_id, "PN-1", datetime.now(UTC), tester_id)
    
    raw_data = {"lot_id": lot_id, "part_number": "PN-1", "status": "COMPLETE", "readings": [], "account_id": tester_id}
    
    from contracts import AnalysisResults, RiskAssessment, LotDisposition
    results = AnalysisResults(
        assessments=[
            RiskAssessment(
                component_id="C1",
                lot_id=lot_id,
                verdict="PASS",
                module_a_rank=0.5,
                module_b_rank=0.8,
                worst_parameter="iddq_uA",
                module_a_ran=True,
                module_b_ran=True,
                predicted_168h=5.0,
                actual_168h=5.1,
                explanation_sentence="Explanation here."
            )
        ],
        disposition=LotDisposition(
            lot_id=lot_id,
            status="COMPLETE",
            pda_result=0.0,
            verdict="ACCEPT",
            is_forecast=False
        )
    )
    
    repository.save_analysis_run(lot_id, raw_data, results)
    
    # We patch fusion.pipeline.run_full_pipeline just in case someone imports it or calls it.
    with patch("fusion.pipeline.run_full_pipeline") as mock_run:
        mock_run.side_effect = Exception("Live recompute should not happen")
        
        # First call
        resp1 = client.get(f"/lots/{lot_id}")
        assert resp1.status_code == 200
        
        # Second call
        resp2 = client.get(f"/lots/{lot_id}")
        assert resp2.status_code == 200
        
        # Confirm no recomputation occurred
        assert mock_run.call_count == 0
        
        # Confirm they are identical
        assert resp1.json() == resp2.json()
        
        data = resp1.json()
        assert len(data["assessments"]) == 1
        assert data["assessments"][0]["component_id"] == "C1"
        assert data["assessments"][0]["verdict"] == "PASS"
        assert data["assessments"][0]["module_a_rank"] == 0.5
        assert data["assessments"][0]["module_b_rank"] == 0.8
        assert data["assessments"][0]["worst_parameter"] == "iddq_uA"
        assert data["disposition"]["verdict"] == "ACCEPT"


def test_get_lot_summary_returns_insufficient_data_components():
    """AnalysisResults.insufficient_data_components (additive, CONTRACT_CHANGES.md 2026-09-30) reaches
    GET /lots/{lot_id} on a stored row that set it."""
    uid = str(uuid.uuid4())
    lot_id = f"test-lot-idc-{uid}"
    tester_id = f"tester-{uid}"
    repository.save_account(tester_id, "Tester", "operator", "hash")
    repository.save_project(lot_id, lot_id, "PN-1", datetime.now(UTC), tester_id)

    from contracts import AnalysisResults, LotDisposition

    results = AnalysisResults(
        assessments=[],
        disposition=LotDisposition(
            lot_id=lot_id, status="IN_PROGRESS", pda_result=0.0, verdict="LOT_AT_RISK", is_forecast=True
        ),
        insufficient_data_components=["C9"],
    )
    raw_data = {"lot_id": lot_id, "part_number": "PN-1", "status": "IN_PROGRESS", "readings": [], "account_id": tester_id}
    repository.save_analysis_run(lot_id, raw_data, results)

    resp = client.get(f"/lots/{lot_id}")
    assert resp.status_code == 200
    assert resp.json()["insufficient_data_components"] == ["C9"]


def test_get_lot_summary_parses_an_old_stored_row_without_insufficient_data_components():
    """A row stored before this field existed has no key at all in its results_json - must still parse,
    defaulting to [] (additive field, CONTRACT_CHANGES.md 2026-09-30), not a validation error on reload."""
    uid = str(uuid.uuid4())
    lot_id = f"test-lot-old-shape-{uid}"
    tester_id = f"tester-{uid}"
    repository.save_account(tester_id, "Tester", "operator", "hash")
    repository.save_project(lot_id, lot_id, "PN-1", datetime.now(UTC), tester_id)

    old_shape_results_json = json.dumps({
        "assessments": [],
        "disposition": {
            "lot_id": lot_id, "status": "IN_PROGRESS", "pda_result": 0.0,
            "verdict": "LOT_ON_TRACK", "is_forecast": True,
        },
        # deliberately no "insufficient_data_components" key - the pre-this-field stored shape.
    })

    from contracts import ProjectData
    from storage.repository import SessionLocal

    with SessionLocal() as session:
        session.add(ProjectData(
            analysis_run_id=f"run-{uuid_lib.uuid4().hex[:12]}",
            project_id=lot_id,
            raw_data=json.dumps({}),
            results_json=old_shape_results_json,
            diff_vs_prior=None,
            created_at=datetime.now(UTC),
        ))
        session.commit()

    resp = client.get(f"/lots/{lot_id}")
    assert resp.status_code == 200
    assert resp.json()["insufficient_data_components"] == []


# --- Block 3B Part 4: GET /parts/{component_id} ----------------------------------------------------

def _seed_account(uid):
    account_id = f"tester-{uid}"
    repository.save_account(account_id, "Tester", "Quality Engineer", "hash")
    return account_id


def _auth_headers(account_id):
    token = create_access_token(account_id, "Quality Engineer")
    return {"Authorization": f"Bearer {token}"}


def _module_a_result(component_id, lot_id, parameter="leakage", tier="REJECT"):
    from contracts import ModuleAResult
    return ModuleAResult(
        component_id=component_id, lot_id=lot_id, parameter=parameter, robust_z=4.2,
        mcd_distance=None, isolation_forest_score=None, ecod_score=0.9,
        explainable_tags={"robust_z": True, "mcd": False, "isolation_forest": False, "ecod": False},
        direction="above_median", severity_tier=tier, severity_cap_reason=None,
        combined_severity=0.95, explainable_corroboration=True,
    )


def _module_b_result(component_id, lot_id, parameter="leakage", forecast_unavailable=False):
    from contracts import ModuleBResult
    if forecast_unavailable:
        return ModuleBResult(
            component_id=component_id, lot_id=lot_id, parameter=parameter, predicted_168h=None,
            interval_lower=None, interval_upper=None, physics_baseline_prediction=None,
            physics_disagreement_gap=None, drift_rate=None, exceeds_safety_slope=None,
            safety_slope=None, lower_bound_exceeds_safety_slope=None, forecast_unavailable=True,
        )
    return ModuleBResult(
        component_id=component_id, lot_id=lot_id, parameter=parameter, predicted_168h=69.0,
        interval_lower=60.0, interval_upper=78.0, physics_baseline_prediction=65.0,
        physics_disagreement_gap=4.0, drift_rate=1.38, exceeds_safety_slope=True, safety_slope=1.0,
        lower_bound_exceeds_safety_slope=True, forecast_unavailable=False,
    )


def _seed_lot_with_results(project_id, lot_id, part_number, account_id, results, created_at=None):
    repository.save_project(project_id, lot_id, part_number, created_at or datetime.now(UTC), account_id)
    raw_data = {"lot_id": lot_id, "part_number": part_number, "status": "COMPLETE", "readings": [], "account_id": account_id}
    return repository.save_analysis_run(project_id, raw_data, results)


def test_get_part_detail_flagged_part():
    from contracts import AnalysisResults, LotDisposition, PartExplanation, RiskAssessment

    uid = str(uuid.uuid4())
    lot_id = f"lot-flagged-{uid}"
    account_id = _seed_account(uid)
    results = AnalysisResults(
        assessments=[RiskAssessment(
            component_id="GOLDEN-045", lot_id=lot_id, verdict="REJECT", module_a_rank=1.0,
            module_b_rank=1.0, worst_parameter="leakage", module_a_ran=True, module_b_ran=True,
            predicted_168h=69.0, actual_168h=None, explanation_sentence=None,
        )],
        disposition=LotDisposition(lot_id=lot_id, status="COMPLETE", pda_result=0.1, verdict="HOLD", is_forecast=False),
        module_a_results={"GOLDEN-045": _module_a_result("GOLDEN-045", lot_id)},
        module_b_results={"GOLDEN-045": _module_b_result("GOLDEN-045", lot_id)},
        part_explanations={"GOLDEN-045": PartExplanation(
            explanation_sentence="Part GOLDEN-045: leakage at 24h is 4.2 robust-sigma above lot median.",
            confidence_qualifier="high confidence",
        )},
    )
    _seed_lot_with_results(lot_id, lot_id, "PN-GOLDEN", account_id, results)

    resp = client.get("/parts/GOLDEN-045", headers=_auth_headers(account_id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["module_a"]["component_id"] == "GOLDEN-045"
    assert data["module_b"]["predicted_168h"] == 69.0
    assert data["explanation_sentence"] == "Part GOLDEN-045: leakage at 24h is 4.2 robust-sigma above lot median."
    assert data["confidence_qualifier"] == "high confidence"


def test_get_part_detail_pass_part_within_normal_range():
    from contracts import AnalysisResults, LotDisposition, RiskAssessment

    uid = str(uuid.uuid4())
    lot_id = f"lot-pass-{uid}"
    account_id = _seed_account(uid)
    results = AnalysisResults(
        assessments=[RiskAssessment(
            component_id="C-PASS", lot_id=lot_id, verdict="PASS", module_a_rank=5.0,
            module_b_rank=5.0, worst_parameter="iddq", module_a_ran=True, module_b_ran=True,
            predicted_168h=12.0, actual_168h=12.1, explanation_sentence=None,
        )],
        disposition=LotDisposition(lot_id=lot_id, status="COMPLETE", pda_result=0.0, verdict="ACCEPT", is_forecast=False),
        module_a_results={"C-PASS": _module_a_result("C-PASS", lot_id, parameter="iddq", tier="PASS")},
        module_b_results={"C-PASS": _module_b_result("C-PASS", lot_id, parameter="iddq")},
        # no part_explanations entry for a PASS part.
    )
    _seed_lot_with_results(lot_id, lot_id, "PN-1", account_id, results)

    resp = client.get("/parts/C-PASS", headers=_auth_headers(account_id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["explanation_sentence"] == "within normal range"
    assert data["severity_cap_note"] is None
    assert data["explanation"]["shap_contributions"] == []
    assert data["explanation"]["mcd_contributions"] == []
    assert data["explanation"]["ecod_dimensions"] == []
    assert data["explanation"]["zscore_table"] == []


def test_get_part_detail_in_progress_part_returns_200_module_a_none():
    """B1: after B6, PartDetailResponse.module_a/.module_b are Optional - an in-progress part
    (Module A never ran) now returns 200 with module_a=None, module_b present, explanation
    present. 404 stays reserved for a genuinely unknown component_id."""
    from contracts import AnalysisResults, LotDisposition, PartExplanation, RiskAssessment

    uid = str(uuid.uuid4())
    lot_id = f"lot-inprog-detail-{uid}"
    account_id = _seed_account(uid)
    results = AnalysisResults(
        assessments=[RiskAssessment(
            component_id="C-INPROG", lot_id=lot_id, verdict="REJECT", module_a_rank=0.0,
            module_b_rank=1.0, worst_parameter="iddq", module_a_ran=False, module_b_ran=True,
            predicted_168h=500.0, actual_168h=None, explanation_sentence=None,
        )],
        disposition=LotDisposition(lot_id=lot_id, status="IN_PROGRESS", pda_result=1.0,
                                    verdict="STOP_RUN_RECOMMENDED", is_forecast=True),
        module_a_results={},
        module_b_results={"C-INPROG": _module_b_result("C-INPROG", lot_id, parameter="iddq")},
        part_explanations={"C-INPROG": PartExplanation(
            explanation_sentence="Part C-INPROG: predicted 168h drift exceeds the safety slope.",
            confidence_qualifier="forecast borderline: the prediction interval spans the safety slope - recommend retest",
        )},
    )
    _seed_lot_with_results(lot_id, lot_id, "PN-INPROG", account_id, results)

    resp = client.get("/parts/C-INPROG", headers=_auth_headers(account_id))
    assert resp.status_code == 200
    data = resp.json()
    assert data["module_a"] is None
    assert data["module_b"]["predicted_168h"] == 69.0
    assert data["explanation_sentence"] == "Part C-INPROG: predicted 168h drift exceeds the safety slope."


def test_get_part_detail_unknown_component_404():
    uid = str(uuid.uuid4())
    account_id = _seed_account(uid)
    resp = client.get("/parts/NO-SUCH-COMPONENT", headers=_auth_headers(account_id))
    assert resp.status_code == 404


def test_get_part_detail_requires_auth():
    resp = client.get("/parts/anything")
    assert resp.status_code in (401, 403)


def test_matching_runs_logs_a_warning_on_a_row_that_fails_validation(caplog):
    """B6c: a stored row that fails AnalysisResults validation is still skipped, not a 500 - but
    it must now be logged, not silently dropped (deliberately invalid row: no "disposition" key,
    a required field)."""
    import logging

    uid = str(uuid.uuid4())
    lot_id = f"lot-invalid-row-{uid}"
    account_id = _seed_account(uid)
    repository.save_project(lot_id, lot_id, "PN-1", datetime.now(UTC), account_id)

    invalid_results_json = json.dumps({"assessments": []})  # missing required "disposition"
    from contracts import ProjectData
    from storage.repository import SessionLocal

    with SessionLocal() as session:
        session.add(ProjectData(
            analysis_run_id=f"run-invalid-{uid}",
            project_id=lot_id,
            raw_data=json.dumps({}),
            results_json=invalid_results_json,
            diff_vs_prior=None,
            created_at=datetime.now(UTC),
        ))
        session.commit()

    with caplog.at_level(logging.WARNING, logger="fusion.router"):
        resp = client.get(f"/parts/anything-{uid}", headers=_auth_headers(account_id))
    assert resp.status_code == 404
    assert any(
        f"run-invalid-{uid}" in record.getMessage() and lot_id in record.getMessage()
        for record in caplog.records
    )


def test_get_part_detail_ambiguous_component_resolves_to_most_recent_or_named_lot():
    from contracts import AnalysisResults, LotDisposition, RiskAssessment

    uid = str(uuid.uuid4())
    account_id = _seed_account(uid)
    shared_component = f"SHARED-{uid}"
    lot_old = f"lot-old-{uid}"
    lot_new = f"lot-new-{uid}"

    def _results_for(lot_id, parameter):
        return AnalysisResults(
            assessments=[RiskAssessment(
                component_id=shared_component, lot_id=lot_id, verdict="WATCH", module_a_rank=1.0,
                module_b_rank=1.0, worst_parameter=parameter, module_a_ran=True, module_b_ran=True,
                predicted_168h=None, actual_168h=None, explanation_sentence=None,
            )],
            disposition=LotDisposition(lot_id=lot_id, status="COMPLETE", pda_result=0.0, verdict="HOLD", is_forecast=False),
            module_a_results={shared_component: _module_a_result(shared_component, lot_id, parameter=parameter, tier="REVIEW")},
            module_b_results={shared_component: _module_b_result(shared_component, lot_id, parameter=parameter)},
        )

    _seed_lot_with_results(lot_old, lot_old, "PN-OLD", account_id, _results_for(lot_old, "iddq"),
                            created_at=datetime(2020, 1, 1, tzinfo=UTC))
    _seed_lot_with_results(lot_new, lot_new, "PN-NEW", account_id, _results_for(lot_new, "prop_delay"),
                            created_at=datetime(2026, 1, 1, tzinfo=UTC))

    resp_default = client.get(f"/parts/{shared_component}", headers=_auth_headers(account_id))
    assert resp_default.status_code == 200
    assert resp_default.json()["module_a"]["lot_id"] == lot_new

    resp_scoped = client.get(f"/parts/{shared_component}", params={"lot_id": lot_old}, headers=_auth_headers(account_id))
    assert resp_scoped.status_code == 200
    assert resp_scoped.json()["module_a"]["lot_id"] == lot_old


def test_get_part_detail_disposition_history_after_post_disposition():
    from contracts import AnalysisResults, LotDisposition, RiskAssessment

    uid = str(uuid.uuid4())
    lot_id = f"lot-disp-{uid}"
    account_id = _seed_account(uid)
    account_id2 = _seed_account(uid + "-b")
    results = AnalysisResults(
        assessments=[RiskAssessment(
            component_id="C-DISP", lot_id=lot_id, verdict="WATCH", module_a_rank=1.0,
            module_b_rank=1.0, worst_parameter="iddq", module_a_ran=True, module_b_ran=True,
            predicted_168h=None, actual_168h=None, explanation_sentence=None,
        )],
        disposition=LotDisposition(lot_id=lot_id, status="COMPLETE", pda_result=0.0, verdict="HOLD", is_forecast=False),
        module_a_results={"C-DISP": _module_a_result("C-DISP", lot_id, parameter="iddq", tier="REVIEW")},
        module_b_results={"C-DISP": _module_b_result("C-DISP", lot_id, parameter="iddq")},
    )
    run = _seed_lot_with_results(lot_id, lot_id, "PN-1", account_id, results)

    post_resp = client.post(
        f"/parts/C-DISP/disposition",
        params={"project_id": lot_id, "analysis_run_id": run.analysis_run_id},
        json={"verdict": "HOLD", "rationale": "retest requested"},
        headers=_auth_headers(account_id),
    )
    assert post_resp.status_code == 200

    resp = client.get("/parts/C-DISP", headers=_auth_headers(account_id))
    assert resp.status_code == 200
    history = resp.json()["disposition_history"]
    assert len(history) == 1
    assert history[0]["verdict"] == "HOLD"
    assert history[0]["rationale"] == "retest requested"


def test_get_part_detail_never_calls_run_full_pipeline():
    from contracts import AnalysisResults, LotDisposition, RiskAssessment

    uid = str(uuid.uuid4())
    lot_id = f"lot-norecompute-{uid}"
    account_id = _seed_account(uid)
    results = AnalysisResults(
        assessments=[RiskAssessment(
            component_id="C-NR", lot_id=lot_id, verdict="PASS", module_a_rank=1.0, module_b_rank=1.0,
            worst_parameter="iddq", module_a_ran=True, module_b_ran=True, predicted_168h=None,
            actual_168h=None, explanation_sentence=None,
        )],
        disposition=LotDisposition(lot_id=lot_id, status="COMPLETE", pda_result=0.0, verdict="ACCEPT", is_forecast=False),
        module_a_results={"C-NR": _module_a_result("C-NR", lot_id, parameter="iddq", tier="PASS")},
        module_b_results={"C-NR": _module_b_result("C-NR", lot_id, parameter="iddq")},
    )
    _seed_lot_with_results(lot_id, lot_id, "PN-1", account_id, results)

    with patch("fusion.pipeline.run_full_pipeline") as mock_run:
        mock_run.side_effect = Exception("GET /parts/{id} must never re-run the pipeline")
        resp = client.get("/parts/C-NR", headers=_auth_headers(account_id))
        assert resp.status_code == 200
        assert mock_run.call_count == 0


def test_registered_routes_include_parts_detail_and_the_four_planned_capa_routes_and_exclude_the_unplanned_ones():
    """Part 4d, updated by Block 4a-resume R1: the real app (api/main.py), not the local test app -
    GET /parts/{component_id} is reachable, as are the four E13 routes Block 4a registered
    (capa.router.planned_router: confirmed-outcome, worklist, corrective-status, dpa-work-order).
    capa.router.router's three pre-existing, unplanned TEMP_ routes (/capa, /capa/{id}/resolve,
    /audit/export) are still absent - that router was never registered (CONTRACT_CHANGES.md,
    2026-09-30 Block 4a Part 6a)."""
    from api.main import app as real_app
    paths = real_app.openapi()["paths"]
    assert "/parts/{component_id}" in paths
    assert "get" in paths["/parts/{component_id}"]
    assert "post" in paths["/parts/{component_id}/confirmed-outcome"]
    assert "get" in paths["/settings/worklist"]
    assert "get" in paths["/settings/corrective-status"]
    assert "post" in paths["/lots/{lot_id}/dpa-work-order"]
    assert "/capa" not in paths
    assert "/capa/{id}/resolve" not in paths
    assert "/audit/export" not in paths
