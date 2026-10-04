"""G5 gate (Block 4b, Lead as verifier): one test per IMPLEMENTATION_PLAN.md Part 7.3 row for Fusion,
Explainability and Identity/CAPA, written against the real code (real pipeline, real routes, isolated
DB), independent of the earlier unit tests that cover the same rows. Part 7.4: this file is new,
nothing existing is edited.

Rows (numbering follows the Block 4b work packet, Part B):
  Fusion:         (1) gate cap only on unexplainable-only signals   (2) capped A + B REJECT still REJECT
                  (3) early reject counts toward PDA                (4) forecast vs final wording
  Explainability: (5) every mechanism that applies is present       (6) cap note fires for BOTH reasons
  Identity/CAPA:  (7) dual sign-off needs two DISTINCT accounts     (8) FN and FP computed separately
                  (9) INSUFFICIENT_DATA below 10 outcomes           (10) JWT valid / expired / tampered

Part C (D82 puzzle 2) is also pinned here: the explanation sentence quotes the same robust_z as
ModuleAResult.robust_z and names the checkpoint that produced it.
"""
from datetime import UTC, datetime, timedelta

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient

import fusion.pipeline as pipeline_module
from contracts import (
    AnalysisResults, LotDataset, LotDisposition, ModuleAResult, ModuleBResult, RiskAssessment, ScreeningConfig,
)
from fusion.gate import compute_part_verdict
from fusion.pipeline import run_full_pipeline
from harness.golden import GOLDEN_COMPONENT_ID, golden_lot
from storage import repository
from storage.repository import save_account, save_analysis_run, save_confirmed_outcome, save_project

hasher = PasswordHasher()

FORECAST_VERDICTS = {"LOT_ON_TRACK", "LOT_AT_RISK", "STOP_RUN_RECOMMENDED"}
FINAL_VERDICTS = {"ACCEPT", "HOLD", "REJECT"}


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from storage import database

    engine = create_engine(f"sqlite:///{tmp_path / 'g5.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    monkeypatch.setattr(repository, "SessionLocal", session_local)
    repository.init_db()
    save_account("a.sharma", "A. Sharma", "Quality Engineer", hasher.hash("1234"))
    save_account("r.mehta", "R. Mehta", "Reliability Engineer", hasher.hash("5678"))


@pytest.fixture
def client():
    from capa.router import planned_router
    from fusion.router import router as fusion_router
    from identity.router import router as identity_router
    from storage.router import router as storage_router

    app = FastAPI()
    for r in (identity_router, fusion_router, storage_router, planned_router):
        app.include_router(r)
    return TestClient(app)


def _token(client, account_id, pin):
    resp = client.post("/auth/login", json={"account_id": account_id, "pin": pin})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _hdr(client, account_id="a.sharma", pin="1234"):
    return {"Authorization": f"Bearer {_token(client, account_id, pin)}"}


# ---------------------------------------------------------------------------
# Module-result builders (contract-shaped, only the fields a row exercises vary)
# ---------------------------------------------------------------------------

def _a(tier="REJECT", corroborated=True, cap_reason=None, direction="above_median"):
    return ModuleAResult(
        component_id="C1", lot_id="L1", parameter="iddq", robust_z=2.0, mcd_distance=None,
        isolation_forest_score=None, ecod_score=0.0,
        explainable_tags={"robust_z": True, "mcd": False, "isolation_forest": False, "ecod": False},
        direction=direction, severity_tier=tier, severity_cap_reason=cap_reason, combined_severity=1.0,
        explainable_corroboration=corroborated,
    )


def _b(exceeds=False):
    return ModuleBResult(
        component_id="C1", lot_id="L1", parameter="iddq", predicted_168h=None, interval_lower=None,
        interval_upper=None, physics_baseline_prediction=None, physics_disagreement_gap=None,
        drift_rate=None, exceeds_safety_slope=exceeds, lower_bound_exceeds_safety_slope=False,
        safety_slope=None, forecast_unavailable=False,
    )


# ---------------------------------------------------------------------------
# Real-pipeline fixtures (computed once per module: ~8 s each)
# ---------------------------------------------------------------------------

def _in_progress_lot(steep_component: str | None = "G-005", steep_factor: float = 3.0) -> LotDataset:
    """The golden lot cut back to 0h/24h and marked IN_PROGRESS; `steep_component`'s 24h leakage is
    multiplied so Module B forecasts a real early reject for it."""
    base = golden_lot()
    readings = []
    for r in base.readings:
        if r.checkpoint_hour not in (0, 24):
            continue
        if (steep_component and r.component_id == steep_component and r.parameter == "leakage"
                and r.checkpoint_hour == 24):
            r = r.model_copy(update={"value": r.value * steep_factor})
        readings.append(r)
    return LotDataset(lot_id="IP-LOT-01", part_number=base.part_number, status="IN_PROGRESS",
                      readings=readings, account_id=base.account_id)


@pytest.fixture(scope="module")
def golden_results() -> AnalysisResults:
    return run_full_pipeline(golden_lot(), ScreeningConfig())


@pytest.fixture(scope="module")
def in_progress_results() -> AnalysisResults:
    return run_full_pipeline(_in_progress_lot(), ScreeningConfig())


# ===========================================================================
# FUSION
# ===========================================================================

def test_row1_gate_cap_fires_only_when_no_explainable_detector_corroborates():
    # REJECT driven by an unexplainable detector alone (IF/ECOD): capped to REVIEW, reason recorded.
    verdict, cap_reason, tier = compute_part_verdict(_a("REJECT", corroborated=False), _b(False))
    assert (tier, cap_reason, verdict) == ("REVIEW", "explainability_gate", "WATCH")

    # Same REJECT with an explainable detector (z-score/MCD) corroborating: no cap, REJECT stands.
    verdict, cap_reason, tier = compute_part_verdict(_a("REJECT", corroborated=True), _b(False))
    assert (tier, cap_reason, verdict) == ("REJECT", None, "REJECT")

    # The gate never touches a non-REJECT tier, corroborated or not.
    for tier_in in ("PASS", "REVIEW"):
        for corr in (True, False):
            _, cap_reason, tier = compute_part_verdict(_a(tier_in, corroborated=corr), _b(False))
            assert tier == tier_in and cap_reason is None


def test_row1_real_module_a_gate_is_consistent_with_corroboration_on_every_golden_result(golden_results):
    """Real Module A output over the golden lot: fusion's cap_reason is 'explainability_gate' exactly
    when the raw tier is REJECT with no explainable corroboration - never anywhere else."""
    from features.compute import compute
    from module_a.detect import detect

    results = detect(compute(golden_lot()))
    assert results
    for r in results:
        _, cap_reason, tier = compute_part_verdict(r, None)
        gated = r.severity_tier == "REJECT" and not r.explainable_corroboration
        assert (cap_reason == "explainability_gate") == gated
        if gated:
            assert tier == "REVIEW"
    golden = next(r for r in results if r.component_id == GOLDEN_COMPONENT_ID and r.parameter == "leakage")
    assert golden.severity_tier == "REJECT" and golden.explainable_corroboration  # the worked example is never gated


def test_row2_capped_module_a_plus_module_b_reject_is_still_reject():
    verdict, cap_reason, tier = compute_part_verdict(_a("REJECT", corroborated=False), _b(True))
    assert (tier, cap_reason, verdict) == ("REVIEW", "explainability_gate", "REJECT")
    # ...and the same for a direction-capped A: B's own REJECT is never suppressed by A's cap.
    verdict, cap_reason, tier = compute_part_verdict(
        _a("REVIEW", cap_reason="below_median_direction_cap", direction="below_median"), _b(True))
    assert (tier, cap_reason, verdict) == ("REVIEW", "below_median_direction_cap", "REJECT")


def test_row3_early_reject_counts_toward_pda(in_progress_results):
    r = in_progress_results
    assert r.disposition.status == "IN_PROGRESS" and r.disposition.is_forecast is True
    early = next(a for a in r.assessments if a.component_id == "G-005")
    assert early.verdict == "REJECT" and early.actual_168h is None  # rejected before any 168h reading exists
    assert early.module_b_ran and not early.module_a_ran
    # PDA = failures / parts submitted: the early reject IS the one failure of the 77.
    assert r.disposition.pda_result == pytest.approx(1 / len(r.assessments))
    assert len(r.assessments) == 77 and r.disposition.verdict == "LOT_AT_RISK"


def test_row3_early_reject_reaches_stop_run_when_pda_threshold_is_crossed():
    r = run_full_pipeline(_in_progress_lot(), ScreeningConfig(pda_threshold=0.01))
    assert r.disposition.pda_result == pytest.approx(1 / 77)
    assert r.disposition.verdict == "STOP_RUN_RECOMMENDED"


def test_row4_forecast_and_final_wording_are_never_conflated(in_progress_results, golden_results):
    ip, done = in_progress_results.disposition, golden_results.disposition
    assert ip.is_forecast is True and ip.status == "IN_PROGRESS"
    assert ip.verdict in FORECAST_VERDICTS and ip.verdict not in FINAL_VERDICTS
    assert done.is_forecast is False and done.status == "COMPLETE"
    assert done.verdict in FINAL_VERDICTS and done.verdict not in FORECAST_VERDICTS
    assert FORECAST_VERDICTS.isdisjoint(FINAL_VERDICTS)
    # Same PDA math, different wording: an in-progress run with zero flags is ON_TRACK, never ACCEPT.
    calm = run_full_pipeline(_in_progress_lot(steep_component=None), ScreeningConfig())
    assert calm.disposition.verdict == "LOT_ON_TRACK" and calm.disposition.is_forecast is True


def test_row4_pdf_pda_label_carries_the_forecast_wording():
    """report/pdf.py labels the PDA line by is_forecast (the only user-facing 'PDA' label the backend
    renders itself)."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "report" / "pdf.py").read_text(encoding="utf-8")
    assert '"PDA Result (forecast)" if report.is_forecast else "PDA Result"' in src


# ===========================================================================
# EXPLAINABILITY
# ===========================================================================

def test_row5_in_progress_flagged_parts_carry_shap_and_zscore(in_progress_results):
    r = in_progress_results
    flagged = [a for a in r.assessments if a.verdict != "PASS"]
    assert flagged
    for a in flagged:
        pe = r.part_explanations[a.component_id]
        assert pe.shap_contributions, f"{a.component_id}: SHAP empty on an in-progress flagged part"
        assert pe.zscore_table, f"{a.component_id}: z-score table empty"
        assert pe.explanation_sentence and pe.confidence_qualifier
    assert all(a.component_id not in r.part_explanations for a in r.assessments if a.verdict == "PASS")


def test_row5_complete_flagged_parts_carry_zscore_mcd_ecod_and_shap(golden_results):
    r = golden_results
    flagged = [a for a in r.assessments if a.verdict != "PASS"]
    assert {a.component_id for a in flagged} >= {GOLDEN_COMPONENT_ID}
    for a in flagged:
        pe = r.part_explanations[a.component_id]
        assert pe.zscore_table, f"{a.component_id}: z-score table empty"
        assert pe.mcd_contributions, f"{a.component_id}: MCD contributions empty"
        assert pe.ecod_dimensions, f"{a.component_id}: ECOD dimensions empty"
        assert pe.shap_contributions, f"{a.component_id}: SHAP empty (Module B ran on the complete lot)"
        assert pe.explanation_sentence


def _gated_pipeline(monkeypatch, cap_reason: str):
    """Run the real pipeline on the golden lot, with Module A's result for GOLDEN-045 forced into the
    given capping state (real detect() for everything else)."""
    real_detect = pipeline_module.module_a_detect

    def patched(frames, **kwargs):  # the pipeline passes scoring=... in the default (absolute) mode
        out = []
        for r in real_detect(frames, **kwargs):
            if r.component_id == GOLDEN_COMPONENT_ID and r.parameter == "leakage":
                if cap_reason == "explainability_gate":
                    r = r.model_copy(update={"severity_tier": "REJECT", "explainable_corroboration": False,
                                             "severity_cap_reason": None})
                else:
                    r = r.model_copy(update={"severity_tier": "REVIEW", "direction": "below_median",
                                             "severity_cap_reason": "below_median_direction_cap"})
            out.append(r)
        return out

    monkeypatch.setattr(pipeline_module, "module_a_detect", patched)
    return run_full_pipeline(golden_lot(), ScreeningConfig())


def test_row6_severity_cap_note_fires_for_both_reasons_with_distinct_wording(monkeypatch):
    gate = _gated_pipeline(monkeypatch, "explainability_gate")
    direction = _gated_pipeline(monkeypatch, "below_median_direction_cap")
    gate_note = gate.part_explanations[GOLDEN_COMPONENT_ID].severity_cap_note
    dir_note = direction.part_explanations[GOLDEN_COMPONENT_ID].severity_cap_note
    assert gate_note and dir_note and gate_note != dir_note
    assert "unexplainable detector" in gate_note and "Isolation Forest" in gate_note
    assert "below the lot median" in dir_note and "direction-awareness" in dir_note
    # Gate cap on a part whose final verdict still needs Module B: WATCH held down, note still shown.
    gate_verdict = next(a for a in gate.assessments if a.component_id == GOLDEN_COMPONENT_ID).verdict
    assert gate_verdict in {"WATCH", "REJECT"}
    if gate_verdict == "REJECT":
        assert "relies on Module B" in gate_note


def test_row6_uncapped_reject_has_no_cap_note(golden_results):
    assert golden_results.part_explanations[GOLDEN_COMPONENT_ID].severity_cap_note is None


# ===========================================================================
# IDENTITY / CAPA
# ===========================================================================

def _seed_reject_part(component_id="comp1", lot_id="lot_001", project_id="proj1", verdict="REJECT"):
    save_project(project_id, lot_id, "PN123", datetime.now(UTC), "a.sharma")
    results = AnalysisResults(
        assessments=[RiskAssessment(component_id=component_id, lot_id=lot_id, verdict=verdict,
                                    module_a_rank=1.0, module_b_rank=1.0, worst_parameter="leakage",
                                    module_a_ran=True, module_b_ran=True, predicted_168h=None,
                                    actual_168h=None, explanation_sentence=None)],
        disposition=LotDisposition(lot_id=lot_id, status="COMPLETE", pda_result=1.0, verdict="REJECT",
                                   is_forecast=False),
    )
    return save_analysis_run(project_id, {}, results)


def test_row7_dual_signoff_needs_two_distinct_account_ids(client):
    run = _seed_reject_part()
    url = f"/parts/comp1/disposition?project_id=proj1&analysis_run_id={run.analysis_run_id}"
    body = {"verdict": "REJECT", "rationale": "confirmed"}
    sharma = _hdr(client)
    assert client.post(url, json=body, headers=sharma).status_code == 200
    same = client.post(url, json=body, headers=sharma)  # same account twice
    assert same.status_code == 400 and "two distinct account IDs" in same.json()["detail"]
    other = client.post(url, json=body, headers=_hdr(client, "r.mehta", "5678"))
    assert other.status_code == 200
    accounts = [s.account_id for s in repository.query_disposition_signoffs(project_id="proj1", component_id="comp1")]
    assert accounts == ["a.sharma", "r.mehta"]  # the rejected retry wrote nothing


def test_row7_settings_change_also_needs_two_distinct_accounts(client):
    sharma = _hdr(client)
    body = {"field": "pda_threshold", "proposed_value": 0.08}
    assert client.post("/settings/propose", json=body, headers=sharma).status_code == 200
    same = client.post("/settings/signoff", json={"field": "pda_threshold"}, headers=sharma)
    assert same.status_code == 400
    ok = client.post("/settings/signoff", json={"field": "pda_threshold"}, headers=_hdr(client, "r.mehta", "5678"))
    assert ok.status_code == 200 and ok.json()["pda_threshold"] == 0.08


def _add_outcomes(pairs, start=0):
    """pairs: (verdict, confirmed_outcome) - one project + one stored run + one confirmed outcome each."""
    for i, (verdict, outcome) in enumerate(pairs, start=start):
        pid, cid, lid = f"proj{i}", f"part{i}", f"lot{i}"
        save_project(pid, lid, "PN1", datetime.now(UTC), "a.sharma")
        results = AnalysisResults(
            assessments=[RiskAssessment(component_id=cid, lot_id=lid, verdict=verdict,
                                        module_a_rank=1.0, module_b_rank=1.0, worst_parameter="leakage",
                                        module_a_ran=True, module_b_ran=True, predicted_168h=None,
                                        actual_168h=None, explanation_sentence=None)],
            disposition=LotDisposition(lot_id=lid, status="COMPLETE", pda_result=0.0, verdict="ACCEPT",
                                       is_forecast=False))
        run = save_analysis_run(pid, {}, results)
        save_confirmed_outcome(project_id=pid, component_id=cid, analysis_run_id=run.analysis_run_id,
                               account_id="a.sharma", confirmed_outcome=outcome)


def test_row8_fn_and_fp_are_computed_separately_in_both_directions(client):
    hdr = _hdr(client)
    # FP bad, FN good: all 10 Confirmed-Good parts were REJECTed (fp 100%), the 10 defectives all caught.
    _add_outcomes([("REJECT", "Confirmed Good")] * 10 + [("REJECT", "Confirmed Defective")] * 10)
    body = client.get("/settings/corrective-status", headers=hdr).json()
    assert body["fp_rate"] == 1.0 and body["fn_rate"] == 0.0
    assert body["status"] == "OK"  # an FP-heavy record is informational, never a trigger (E13 step 7)


def test_row8_fn_bad_fp_good(client):
    hdr = _hdr(client)
    _add_outcomes([("PASS", "Confirmed Defective")] * 10 + [("PASS", "Confirmed Good")] * 10)
    body = client.get("/settings/corrective-status", headers=hdr).json()
    assert body["fn_rate"] == 1.0 and body["fp_rate"] == 0.0
    assert body["status"] == "CEILING_EXCEEDED" and body["confirmed_outcome_count"] == 20


def test_row9_status_stays_insufficient_data_below_ten_even_at_100pct_fn(client):
    hdr = _hdr(client)
    _add_outcomes([("PASS", "Confirmed Defective")] * 9)
    body = client.get("/settings/corrective-status", headers=hdr).json()
    assert body["fn_rate"] == 1.0 and body["confirmed_outcome_count"] == 9
    assert body["status"] == "INSUFFICIENT_DATA"
    _add_outcomes([("PASS", "Confirmed Defective")], start=9)  # the 10th counted outcome flips it
    assert client.get("/settings/corrective-status", headers=hdr).json()["status"] == "CEILING_EXCEEDED"


def test_row10_jwt_valid_expired_and_tampered(client, monkeypatch):
    import identity.auth as auth

    valid = _token(client, "a.sharma", "1234")
    assert client.get("/settings", headers={"Authorization": f"Bearer {valid}"}).status_code == 200

    monkeypatch.setattr(auth, "JWT_EXPIRY_MINUTES", -5)  # signing helper now mints an already-expired token
    expired = auth.create_access_token("a.sharma", "Quality Engineer")
    resp = client.get("/settings", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401 and "expired" in resp.json()["detail"].lower()

    header, payload, sig = valid.split(".")
    flipped = ("A" if payload[0] != "A" else "B") + payload[1:]
    for bad in (f"{header}.{flipped}.{sig}", f"{header}.{payload}.{sig[:-2]}xx", "not.a.jwt"):
        r = client.get("/settings", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401, bad
    assert client.get("/settings").status_code == 401  # no token at all


# ===========================================================================
# PART C (D82 puzzle 2): the sentence quotes Module A's own number
# ===========================================================================

def test_partc_sentence_quotes_module_a_robust_z_and_its_checkpoint(golden_results):
    a = golden_results.module_a_results[GOLDEN_COMPONENT_ID]
    sentence = golden_results.part_explanations[GOLDEN_COMPONENT_ID].explanation_sentence
    from features.compute import compute
    frame = next(f for f in compute(golden_lot())
                 if f.component_id == GOLDEN_COMPONENT_ID and f.parameter == a.parameter)
    checkpoint = max(frame.robust_z, key=lambda k: abs(frame.robust_z[k]))
    assert abs(frame.robust_z[checkpoint]) == pytest.approx(a.robust_z)  # same worst-checkpoint rule as Module A
    assert f"{a.robust_z:.1f} robust-sigma" in sentence
    assert f"at {checkpoint}" in sentence
