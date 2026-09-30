import pytest
from contracts import LotDataset, ScreeningConfig, Reading, AnalysisResults
from fusion.pipeline import run_full_pipeline

def test_run_full_pipeline_stub():
    """
    Verify that the stubbed pipeline returns valid, correctly shaped instances 
    of RiskAssessment, LotDisposition, and AnalysisResults matching contracts.py.
    """
    reading = Reading(
        component_id="COMP-001",
        lot_id="LOT-123",
        part_number="PN-ABC",
        manufacturer="MFG",
        date_code="2026",
        parameter="iddq",
        checkpoint_hour=0.0,
        value=1.5,
        unit="uA"
    )
    reading_24h = Reading(
        component_id="COMP-001",
        lot_id="LOT-123",
        part_number="PN-ABC",
        manufacturer="MFG",
        date_code="2026",
        parameter="iddq",
        checkpoint_hour=24.0,
        value=1.6,
        unit="uA"
    )
    reading_168h = Reading(
        component_id="COMP-001",
        lot_id="LOT-123",
        part_number="PN-ABC",
        manufacturer="MFG",
        date_code="2026",
        parameter="iddq",
        checkpoint_hour=168.0,
        value=2.0,
        unit="uA"
    )
    lot = LotDataset(
        lot_id="LOT-123",
        part_number="PN-ABC",
        status="COMPLETE",
        readings=[reading, reading_24h, reading_168h],
        account_id="ACC-001"
    )
    config = ScreeningConfig()
    
    result = run_full_pipeline(lot, config)
    
    # Verify shape
    assert isinstance(result, AnalysisResults)
    assert len(result.assessments) == 1
    
    assessment = result.assessments[0]
    assert assessment.component_id == "COMP-001"
    assert assessment.lot_id == "LOT-123"
    assert assessment.verdict == "PASS"
    
    disposition = result.disposition
    assert disposition.lot_id == "LOT-123"
    assert disposition.status == "COMPLETE"
    assert disposition.verdict == "ACCEPT"
    assert disposition.is_forecast is False

def test_run_full_pipeline_stub_in_progress():
    """
    Verify that an IN_PROGRESS input produces is_forecast=True and 
    forecast-vocabulary verdict.
    """
    reading = Reading(
        component_id="COMP-001",
        lot_id="LOT-456",
        part_number="PN-DEF",
        manufacturer="MFG",
        date_code="2026",
        parameter="iddq",
        checkpoint_hour=0.0,
        value=1.5,
        unit="uA"
    )
    reading_24h = Reading(
        component_id="COMP-001",
        lot_id="LOT-456",
        part_number="PN-DEF",
        manufacturer="MFG",
        date_code="2026",
        parameter="iddq",
        checkpoint_hour=24.0,
        value=1.6,
        unit="uA"
    )
    lot = LotDataset(
        lot_id="LOT-456",
        part_number="PN-DEF",
        status="IN_PROGRESS",
        readings=[reading, reading_24h],
        account_id="ACC-001"
    )
    config = ScreeningConfig()
    
    result = run_full_pipeline(lot, config)
    
    disposition = result.disposition
    assert disposition.status == "IN_PROGRESS"
    assert disposition.is_forecast is True
    assert disposition.verdict == "LOT_ON_TRACK"  # Forecast vocabulary


def test_run_full_pipeline_stub_edge_cases():
    """
    Test edge cases for the pipeline stub to ensure it handles 
    empty readings and special characters in lot_id safely.
    """
    # Edge case 1: Empty readings and special characters in lot_id
    lot_empty = LotDataset(
        lot_id="LOT!@#-$%^&*(",
        part_number="PN-EDGE",
        status="IN_PROGRESS",
        readings=[],
        account_id="ACC-002"
    )
    config = ScreeningConfig()
    
    result_empty = run_full_pipeline(lot_empty, config)
    assert len(result_empty.assessments) == 0
    assert result_empty.disposition.lot_id == "LOT!@#-$%^&*("
    # Zero assessments (D50): never reassure without data. An IN_PROGRESS lot with nothing to
    # assess is LOT_AT_RISK, not the default-case LOT_ON_TRACK a no-failures fallthrough would give.
    assert result_empty.disposition.verdict == "LOT_AT_RISK"
    assert result_empty.disposition.pda_result == 0.0

    # Edge case 2: Empty lot_id string
    lot_no_id = LotDataset(
        lot_id="",
        part_number="PN-EDGE",
        status="COMPLETE",
        readings=[],
        account_id="ACC-002"
    )
    result_no_id = run_full_pipeline(lot_no_id, config)
    assert len(result_no_id.assessments) == 0
    assert result_no_id.disposition.lot_id == ""
    # Zero assessments (D50): a Complete lot with nothing to assess is HOLD, not the default-case
    # ACCEPT a no-failures/no-WATCH fallthrough would give.
    assert result_no_id.disposition.verdict == "HOLD"
    assert result_no_id.disposition.pda_result == 0.0


def test_run_full_pipeline_with_assessments_is_unchanged_by_the_zero_assessment_rule():
    """The zero-assessment D50 rule (LOT_AT_RISK/HOLD) must only fire when there are genuinely no
    assessments - a lot that DOES have assessments keeps its normal verdict logic untouched."""
    reading = Reading(
        component_id="COMP-001", lot_id="LOT-NONEMPTY", part_number="PN-ABC", manufacturer="MFG",
        date_code="2026", parameter="iddq", checkpoint_hour=0.0, value=1.5, unit="uA",
    )
    reading_24h = Reading(
        component_id="COMP-001", lot_id="LOT-NONEMPTY", part_number="PN-ABC", manufacturer="MFG",
        date_code="2026", parameter="iddq", checkpoint_hour=24.0, value=1.6, unit="uA",
    )
    lot = LotDataset(
        lot_id="LOT-NONEMPTY", part_number="PN-ABC", status="IN_PROGRESS",
        readings=[reading, reading_24h], account_id="ACC-001",
    )
    result = run_full_pipeline(lot, ScreeningConfig())
    assert len(result.assessments) == 1
    # Same as test_run_full_pipeline_stub_in_progress: a healthy in-progress part is LOT_ON_TRACK,
    # not LOT_AT_RISK - the zero-assessment branch must not fire here.
    assert result.disposition.verdict == "LOT_ON_TRACK"

from unittest.mock import patch
from contracts import ModuleBResult

@patch('fusion.pipeline.module_b_predict')
def test_stop_run_recommended_lower_bound(mock_predict):
    from contracts import LotDataset, Reading, ScreeningConfig
    # We will test 3 conditions: (a) lower bound exceeds, (b) point exceeds but not lower bound, (c) all None
    lot = LotDataset(
        lot_id="LOT-FRC",
        part_number="PN-ABC",
        status="IN_PROGRESS",
        readings=[
            Reading(component_id="C1", lot_id="LOT-FRC", part_number="PN-ABC", manufacturer="M", date_code="D", parameter="p", checkpoint_hour=0.0, value=1.0, unit="uA"),
            Reading(component_id="C1", lot_id="LOT-FRC", part_number="PN-ABC", manufacturer="M", date_code="D", parameter="p", checkpoint_hour=24.0, value=1.5, unit="uA"),
        ],
        account_id="ACC-001"
    )
    config = ScreeningConfig(pda_threshold=0.5)

    # (a) lower bound exceeds
    mock_predict.return_value = [
        ModuleBResult(component_id="C1", lot_id="LOT-FRC", parameter="p", drift_rate=2.0, exceeds_safety_slope=True, safety_slope=1.0, lower_bound_exceeds_safety_slope=True, predicted_168h=5.0, interval_lower=4.0, interval_upper=6.0, physics_baseline_prediction=1.0, physics_disagreement_gap=0.0, forecast_unavailable=False)
    ]
    res_a = run_full_pipeline(lot, config)
    assert res_a.disposition.verdict == "STOP_RUN_RECOMMENDED"

    # (b) point exceeds but not lower bound -> LOT_AT_RISK
    mock_predict.return_value = [
        ModuleBResult(component_id="C1", lot_id="LOT-FRC", parameter="p", drift_rate=2.0, exceeds_safety_slope=True, safety_slope=1.0, lower_bound_exceeds_safety_slope=False, predicted_168h=5.0, interval_lower=4.0, interval_upper=6.0, physics_baseline_prediction=1.0, physics_disagreement_gap=0.0, forecast_unavailable=False)
    ]
    res_b = run_full_pipeline(lot, config)
    assert res_b.disposition.verdict == "LOT_AT_RISK"

    # (c) all None -> LOT_ON_TRACK
    mock_predict.return_value = [
        ModuleBResult(component_id="C1", lot_id="LOT-FRC", parameter="p", drift_rate=None, exceeds_safety_slope=None, safety_slope=None, lower_bound_exceeds_safety_slope=None, predicted_168h=None, interval_lower=None, interval_upper=None, physics_baseline_prediction=None, physics_disagreement_gap=None, forecast_unavailable=True)
    ]
    res_c = run_full_pipeline(lot, config)
    assert res_c.disposition.verdict == "LOT_ON_TRACK"

@patch('fusion.pipeline.module_b_predict')
@patch('fusion.pipeline.module_a_detect')
def test_rankings(mock_a, mock_b):
    from contracts import LotDataset, Reading, ScreeningConfig, ModuleAResult, ModuleBResult
    from fusion.pipeline import run_full_pipeline
    
    # 3 components, 3 parameters = 9 readings (0h and 24h)
    readings = []
    for c in ['C1', 'C2', 'C3']:
        for p in ['iddq', 'leakage', 'prop_delay']:
            readings.append(Reading(component_id=c, lot_id='LOT1', part_number='PN1', manufacturer='M', date_code='D', parameter=p, checkpoint_hour=0.0, value=1.0, unit='u'))
            readings.append(Reading(component_id=c, lot_id='LOT1', part_number='PN1', manufacturer='M', date_code='D', parameter=p, checkpoint_hour=24.0, value=2.0, unit='u'))
            
    lot = LotDataset(lot_id='LOT1', part_number='PN1', status='COMPLETE', readings=readings, account_id='ACC')
    config = ScreeningConfig()
    
    # Module A: C2 is worst (0.9), C1 is 0.8, C3 is 0.8. Ties broken by ID: C1 > C3?
    # Wait, 'Rank 1 = most severe. Ties are broken by component_id ascending.'
    # So C2=1, C1=2, C3=3.
    mock_a.return_value = [
        ModuleAResult(component_id='C1', lot_id='LOT1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='PASS', severity_cap_reason=None, combined_severity=0.8, explainable_corroboration=False),
        ModuleAResult(component_id='C2', lot_id='LOT1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='PASS', severity_cap_reason=None, combined_severity=0.9, explainable_corroboration=False),
        ModuleAResult(component_id='C3', lot_id='LOT1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='PASS', severity_cap_reason=None, combined_severity=0.8, explainable_corroboration=False),
    ]
    
    # Module B: C3 is worst (drift_rate/safety_slope = 3.0), C1 is 2.0, C2 has None.
    # C2 should rank 3.
    mock_b.return_value = [
        ModuleBResult(component_id='C1', lot_id='LOT1', parameter='iddq', drift_rate=2.0, safety_slope=1.0, exceeds_safety_slope=True, lower_bound_exceeds_safety_slope=False, predicted_168h=0, interval_lower=0, interval_upper=0, physics_baseline_prediction=0, physics_disagreement_gap=0, forecast_unavailable=False),
        ModuleBResult(component_id='C2', lot_id='LOT1', parameter='iddq', drift_rate=None, safety_slope=None, exceeds_safety_slope=None, lower_bound_exceeds_safety_slope=None, predicted_168h=0, interval_lower=0, interval_upper=0, physics_baseline_prediction=0, physics_disagreement_gap=0, forecast_unavailable=True),
        ModuleBResult(component_id='C3', lot_id='LOT1', parameter='iddq', drift_rate=6.0, safety_slope=2.0, exceeds_safety_slope=True, lower_bound_exceeds_safety_slope=False, predicted_168h=0, interval_lower=0, interval_upper=0, physics_baseline_prediction=0, physics_disagreement_gap=0, forecast_unavailable=False),
    ]
    
    res = run_full_pipeline(lot, config)
    
    # Check Module A
    a_ranks = {a.component_id: a.module_a_rank for a in res.assessments}
    assert a_ranks['C2'] == 1.0
    assert a_ranks['C1'] == 2.0
    assert a_ranks['C3'] == 3.0
    
    # Check Module B
    b_ranks = {a.component_id: a.module_b_rank for a in res.assessments}
    assert b_ranks['C3'] == 1.0
    assert b_ranks['C1'] == 2.0
    assert b_ranks['C2'] == 3.0

@patch('fusion.pipeline.module_b_predict')
@patch('fusion.pipeline.module_a_detect')
def test_lot_level_verdict_mapping(mock_a, mock_b):
    from contracts import LotDataset, Reading, ScreeningConfig, ModuleAResult, ModuleBResult
    from fusion.pipeline import run_full_pipeline
    
    # helper to create a 2-component lot
    def build_lot():
        readings = []
        for c in ['C1', 'C2']:
            readings.append(Reading(component_id=c, lot_id='L1', part_number='PN1', manufacturer='M', date_code='D', parameter='iddq', checkpoint_hour=0.0, value=1.0, unit='u'))
            readings.append(Reading(component_id=c, lot_id='L1', part_number='PN1', manufacturer='M', date_code='D', parameter='iddq', checkpoint_hour=24.0, value=2.0, unit='u'))
        return LotDataset(lot_id='L1', part_number='PN1', status='COMPLETE', readings=readings, account_id='ACC')
    
    config = ScreeningConfig(pda_threshold=0.5) # 1 part failure = 0.5 (REJECT)

    # Case 1: PDA at or over threshold (both parts REJECT) -> REJECT
    lot1 = build_lot()
    mock_a.return_value = [
        ModuleAResult(component_id='C1', lot_id='L1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='REJECT', severity_cap_reason=None, combined_severity=0.9, explainable_corroboration=True),
        ModuleAResult(component_id='C2', lot_id='L1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='REJECT', severity_cap_reason=None, combined_severity=0.9, explainable_corroboration=True)
    ]
    mock_b.return_value = []
    r1 = run_full_pipeline(lot1, config)
    assert r1.disposition.verdict == 'REJECT'
    assert r1.disposition.pda_result == 1.0
    
    # Case 2: PDA below threshold, at least one WATCH part -> HOLD
    config_low = ScreeningConfig(pda_threshold=1.0) # > 0.5 so PDA not exceeded
    lot2 = build_lot()
    mock_a.return_value = [
        ModuleAResult(component_id='C1', lot_id='L1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='PASS', severity_cap_reason=None, combined_severity=0.1, explainable_corroboration=False),
        ModuleAResult(component_id='C2', lot_id='L1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='REVIEW', severity_cap_reason=None, combined_severity=0.5, explainable_corroboration=True)
    ]
    mock_b.return_value = []
    r2 = run_full_pipeline(lot2, config_low)
    assert r2.disposition.verdict == 'HOLD'
    assert r2.disposition.pda_result == 0.0 # WATCH does not count as failure
    
    # Case 3: PDA below threshold, none -> ACCEPT
    lot3 = build_lot()
    mock_a.return_value = [
        ModuleAResult(component_id='C1', lot_id='L1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='PASS', severity_cap_reason=None, combined_severity=0.1, explainable_corroboration=False),
        ModuleAResult(component_id='C2', lot_id='L1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='PASS', severity_cap_reason=None, combined_severity=0.1, explainable_corroboration=False)
    ]
    mock_b.return_value = []
    r3 = run_full_pipeline(lot3, config_low)
    assert r3.disposition.verdict == 'ACCEPT'
    assert r3.disposition.pda_result == 0.0
    
    # Case 4: PDA below threshold, ONLY REJECT parts -> ACCEPT
    lot4 = build_lot()
    mock_a.return_value = [
        ModuleAResult(component_id='C1', lot_id='L1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='PASS', severity_cap_reason=None, combined_severity=0.1, explainable_corroboration=False),
        ModuleAResult(component_id='C2', lot_id='L1', parameter='iddq', robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod':False}, direction='above_median', severity_tier='REJECT', severity_cap_reason=None, combined_severity=0.9, explainable_corroboration=True)
    ]
    mock_b.return_value = []
    r4 = run_full_pipeline(lot4, config_low) # PDA is 0.5, threshold is 1.0 => not exceeded
    assert r4.disposition.verdict == 'ACCEPT'
    assert r4.disposition.pda_result == 0.5

@patch('fusion.pipeline.module_b_predict')
@patch('fusion.pipeline.module_a_detect')
def test_multi_parameter_rank_with_real_per_component_dedup(mock_a, mock_b):
    """Item B: test_rankings only ever gives each component a single (fake) parameter result,
    so it never exercises the per-component dedup across multiple real parameters - the exact
    gap that let the old dict-collision ranking bug (ranking by frame/parameter count, not by
    component) through undetected. This test gives every one of 4 components a result for all
    3 parameters, for both modules, and picks the worst per component deliberately so the worst
    parameter is not always the one that happens to sort last alphabetically.
    """
    from contracts import LotDataset, Reading, ScreeningConfig, ModuleAResult, ModuleBResult
    from fusion.pipeline import run_full_pipeline

    components = ['C1', 'C2', 'C3', 'C4']
    parameters = ['iddq', 'leakage', 'prop_delay']

    readings = []
    for c in components:
        for p in parameters:
            readings.append(Reading(component_id=c, lot_id='LOT-MP', part_number='PN1', manufacturer='M', date_code='D', parameter=p, checkpoint_hour=0.0, value=1.0, unit='u'))
            readings.append(Reading(component_id=c, lot_id='LOT-MP', part_number='PN1', manufacturer='M', date_code='D', parameter=p, checkpoint_hour=24.0, value=2.0, unit='u'))
    lot = LotDataset(lot_id='LOT-MP', part_number='PN1', status='COMPLETE', readings=readings, account_id='ACC')
    config = ScreeningConfig()

    def a_result(cid, param, severity, tier):
        return ModuleAResult(
            component_id=cid, lot_id='LOT-MP', parameter=param,
            robust_z=0, mcd_distance=0, isolation_forest_score=0, ecod_score=0,
            explainable_tags={'ecod': False}, direction='above_median',
            severity_tier=tier, severity_cap_reason=None,
            combined_severity=severity, explainable_corroboration=True,
        )

    # Module A combined_severity per (component, parameter). Worst (max) per component marked WORST;
    # its severity_tier is REVIEW (not PASS) so fusion/pipeline.py's worst_parameter override fires.
    # C1's worst is "leakage" and C3's worst is "iddq" - neither is "prop_delay", the alphabetically
    # last parameter - so the worst parameter is not always the one that sorts last.
    # combined_severity table:
    #   C1: iddq=0.3, leakage=0.85 (WORST), prop_delay=0.5
    #   C2: iddq=0.2, leakage=0.3,          prop_delay=0.85 (WORST)  <- ties C1 at 0.85
    #   C3: iddq=0.95 (WORST), leakage=0.1, prop_delay=0.4
    #   C4: iddq=0.05, leakage=0.1,         prop_delay=0.15 (WORST)
    mock_a.return_value = [
        a_result('C1', 'iddq', 0.3, 'PASS'),
        a_result('C1', 'leakage', 0.85, 'REVIEW'),
        a_result('C1', 'prop_delay', 0.5, 'PASS'),
        a_result('C2', 'iddq', 0.2, 'PASS'),
        a_result('C2', 'leakage', 0.3, 'PASS'),
        a_result('C2', 'prop_delay', 0.85, 'REVIEW'),
        a_result('C3', 'iddq', 0.95, 'REVIEW'),
        a_result('C3', 'leakage', 0.1, 'PASS'),
        a_result('C3', 'prop_delay', 0.4, 'PASS'),
        a_result('C4', 'iddq', 0.05, 'PASS'),
        a_result('C4', 'leakage', 0.1, 'PASS'),
        a_result('C4', 'prop_delay', 0.15, 'REVIEW'),
    ]

    def b_result(cid, param, drift_rate, safety_slope):
        return ModuleBResult(
            component_id=cid, lot_id='LOT-MP', parameter=param,
            drift_rate=drift_rate, safety_slope=safety_slope,
            exceeds_safety_slope=False, lower_bound_exceeds_safety_slope=False,
            predicted_168h=0, interval_lower=0, interval_upper=0,
            physics_baseline_prediction=0, physics_disagreement_gap=0,
            forecast_unavailable=False,
        )

    # Module B drift_rate/safety_slope per (component, parameter). Worst (max drift_rate/safety_slope
    # ratio) per component marked WORST below. Chosen so ranking by ratio gives the OPPOSITE order to
    # ranking by raw drift_rate alone - this is exactly the distinction fusion/pipeline.py:39-43 makes
    # (severity = drift_rate / safety_slope, not drift_rate on its own):
    #   ratio order (desc):       C4(10.0) > C2(8.0) > C3(6.0) > C1(1.0)
    #   raw drift_rate order (desc, using each component's own worst-by-ratio row): C1(20.0) > C2(16.0) > C3(12.0) > C4(2.0)
    mock_b.return_value = [
        b_result('C1', 'iddq', 20.0, 20.0),        # ratio 1.0  (WORST for C1)
        b_result('C1', 'leakage', 2.0, 4.0),       # ratio 0.5
        b_result('C1', 'prop_delay', 1.0, 4.0),    # ratio 0.25
        b_result('C2', 'iddq', 1.0, 2.0),          # ratio 0.5
        b_result('C2', 'leakage', 16.0, 2.0),      # ratio 8.0  (WORST for C2)
        b_result('C2', 'prop_delay', 1.0, 5.0),    # ratio 0.2
        b_result('C3', 'iddq', 1.0, 2.0),          # ratio 0.5
        b_result('C3', 'leakage', 1.0, 2.0),       # ratio 0.5
        b_result('C3', 'prop_delay', 12.0, 2.0),   # ratio 6.0  (WORST for C3)
        b_result('C4', 'iddq', 2.0, 0.2),          # ratio 10.0 (WORST for C4)
        b_result('C4', 'leakage', 1.0, 2.0),       # ratio 0.5
        b_result('C4', 'prop_delay', 1.0, 2.0),    # ratio 0.5
    ]

    res = run_full_pipeline(lot, config)
    by_id = {a.component_id: a for a in res.assessments}

    # Exactly one assessment per component.
    assert set(by_id.keys()) == set(components)

    a_ranks = {cid: a.module_a_rank for cid, a in by_id.items()}
    b_ranks = {cid: a.module_b_rank for cid, a in by_id.items()}

    # Ranks unique, all in 1..N, max rank == N, for both modules.
    for ranks in (a_ranks, b_ranks):
        values = list(ranks.values())
        assert len(set(values)) == len(components), f"ranks not unique: {ranks}"
        assert all(1.0 <= r <= len(components) for r in values), f"rank out of 1..{len(components)}: {ranks}"
        assert max(values) == float(len(components))

    # Explicit expected Module A order (combined_severity desc, ties broken by component_id asc).
    # C3=0.95 highest; C1 and C2 tie at 0.85 -> C1 (< C2) ranks first; C4=0.15 lowest.
    expected_module_a_order = ['C3', 'C1', 'C2', 'C4']
    actual_module_a_order = sorted(components, key=lambda cid: a_ranks[cid])
    assert actual_module_a_order == expected_module_a_order

    # Explicit expected Module B order (drift_rate/safety_slope ratio desc). No tie here.
    expected_module_b_order = ['C4', 'C2', 'C3', 'C1']
    actual_module_b_order = sorted(components, key=lambda cid: b_ranks[cid])
    assert actual_module_b_order == expected_module_b_order

    # The displayed worst_parameter is the parameter that produced the Module A rank (its
    # severity_tier is REVIEW, not PASS, so fusion/pipeline.py's override always fires here).
    expected_worst_parameter = {'C1': 'leakage', 'C2': 'prop_delay', 'C3': 'iddq', 'C4': 'prop_delay'}
    for cid, expected_param in expected_worst_parameter.items():
        assert by_id[cid].worst_parameter == expected_param, (
            f"{cid}: expected worst_parameter {expected_param!r}, got {by_id[cid].worst_parameter!r}"
        )


# --- Block 3B Part 1: a COMPLETE lot with missing components must never be ACCEPT --------------------

def _reading(cid, lot_id, part_number, param, hour, value, unit='uA'):
    return Reading(component_id=cid, lot_id=lot_id, part_number=part_number, manufacturer='M',
                    date_code='D', parameter=param, checkpoint_hour=hour, value=value, unit=unit)


def test_complete_lot_with_missing_components_is_hold_not_accept():
    """C1 has a full 0h/24h pair (iddq); C2 is missing its 24h reading entirely, so
    ingestion.quality.check_missing_checkpoints flags it INSUFFICIENT_DATA and features.compute
    produces no frame for it at all (rule 7 - never guessed). C1 alone would otherwise verdict
    ACCEPT (no WATCH/REJECT, PDA 0) - the new rule must override that to HOLD because the lot is
    COMPLETE, has >=1 analysed part, and insufficient_data_components is non-empty."""
    readings = [
        _reading('C1', 'LOT-MISSING', 'PN1', 'iddq', 0.0, 1.0),
        _reading('C1', 'LOT-MISSING', 'PN1', 'iddq', 24.0, 1.0),
        _reading('C2', 'LOT-MISSING', 'PN1', 'iddq', 0.0, 1.0),
        # C2's 24h reading is absent entirely.
    ]
    lot = LotDataset(lot_id='LOT-MISSING', part_number='PN1', status='COMPLETE',
                      readings=readings, account_id='ACC')
    result = run_full_pipeline(lot, ScreeningConfig())

    assert result.insufficient_data_components == ['C2']
    assert {a.component_id for a in result.assessments} == {'C1'}
    assert result.disposition.verdict == 'HOLD'


def test_complete_lot_no_missing_none_flagged_stays_accept():
    """Control for the rule above: the same shape, but C2 also has its 24h reading, so nothing is
    missing - insufficient_data_components is empty and the verdict is the ordinary ACCEPT."""
    readings = [
        _reading('C1', 'LOT-FULL', 'PN1', 'iddq', 0.0, 1.0),
        _reading('C1', 'LOT-FULL', 'PN1', 'iddq', 24.0, 1.0),
        _reading('C2', 'LOT-FULL', 'PN1', 'iddq', 0.0, 1.0),
        _reading('C2', 'LOT-FULL', 'PN1', 'iddq', 24.0, 1.0),
    ]
    lot = LotDataset(lot_id='LOT-FULL', part_number='PN1', status='COMPLETE',
                      readings=readings, account_id='ACC')
    result = run_full_pipeline(lot, ScreeningConfig())

    assert result.insufficient_data_components == []
    assert result.disposition.verdict == 'ACCEPT'


@patch('fusion.pipeline.module_a_detect')
def test_complete_lot_only_reject_parts_below_pda_stays_accept_even_with_missing_components(mock_a):
    """1b's second case: 'complete + none missing + PDA below threshold + only REJECT parts ->
    ACCEPT (unchanged)' - the missing-components override must key off insufficient_data_components
    specifically, never off the presence of a REJECT part, so this pre-existing (D15) behaviour is
    untouched."""
    from contracts import ModuleAResult
    readings = [
        _reading('C1', 'L1', 'PN1', 'iddq', 0.0, 1.0),
        _reading('C1', 'L1', 'PN1', 'iddq', 24.0, 2.0),
        _reading('C2', 'L1', 'PN1', 'iddq', 0.0, 1.0),
        _reading('C2', 'L1', 'PN1', 'iddq', 24.0, 2.0),
    ]
    lot = LotDataset(lot_id='L1', part_number='PN1', status='COMPLETE', readings=readings, account_id='ACC')
    config = ScreeningConfig(pda_threshold=1.0)  # 0.5 PDA from one REJECT part does not exceed 1.0
    mock_a.return_value = [
        ModuleAResult(component_id='C1', lot_id='L1', parameter='iddq', robust_z=0, mcd_distance=0,
                      isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod': False},
                      direction='above_median', severity_tier='PASS', severity_cap_reason=None,
                      combined_severity=0.1, explainable_corroboration=False),
        ModuleAResult(component_id='C2', lot_id='L1', parameter='iddq', robust_z=0, mcd_distance=0,
                      isolation_forest_score=0, ecod_score=0, explainable_tags={'ecod': False},
                      direction='above_median', severity_tier='REJECT', severity_cap_reason=None,
                      combined_severity=0.9, explainable_corroboration=True),
    ]
    result = run_full_pipeline(lot, config)
    assert result.insufficient_data_components == []
    assert result.disposition.verdict == 'ACCEPT'


def test_in_progress_lot_with_missing_components_verdict_unchanged():
    """The override is scoped to COMPLETE lots only - an IN_PROGRESS lot still carries the list, but
    its forecast verdict logic (LOT_ON_TRACK/AT_RISK/STOP_RUN_RECOMMENDED) is untouched."""
    readings = [
        _reading('C1', 'LOT-INPROG', 'PN1', 'iddq', 0.0, 1.0),
        _reading('C1', 'LOT-INPROG', 'PN1', 'iddq', 24.0, 1.0),
        _reading('C2', 'LOT-INPROG', 'PN1', 'iddq', 0.0, 1.0),
        # C2 missing 24h.
    ]
    lot = LotDataset(lot_id='LOT-INPROG', part_number='PN1', status='IN_PROGRESS',
                      readings=readings, account_id='ACC')
    result = run_full_pipeline(lot, ScreeningConfig())

    assert result.insufficient_data_components == ['C2']
    assert result.disposition.is_forecast is True
    assert result.disposition.verdict == 'LOT_ON_TRACK'


def test_zero_analysed_with_missing_components_keeps_d50_rule():
    """D50's zero-assessment rule (HOLD for a COMPLETE lot, LOT_AT_RISK for IN_PROGRESS) must still
    govern when total_parts == 0, even though insufficient_data_components is non-empty here too -
    the override in Part 1 requires >=1 analysed part, so it must not double-fire or change wording."""
    readings = [_reading('C1', 'LOT-ZERO', 'PN1', 'iddq', 0.0, 1.0)]  # 24h missing -> zero frames
    lot = LotDataset(lot_id='LOT-ZERO', part_number='PN1', status='COMPLETE',
                      readings=readings, account_id='ACC')
    result = run_full_pipeline(lot, ScreeningConfig())

    assert result.insufficient_data_components == ['C1']
    assert result.assessments == []
    assert result.disposition.verdict == 'HOLD'


def test_pipeline_insufficient_data_components_matches_ingestion_routers_helper():
    """The ingestion router computes the same list independently (CONTRACT_CHANGES.md 2026-09-30) by
    calling the same ingestion.quality.check_missing_checkpoints - verify the two stay equal rather
    than assuming it, per Part 1a's instruction."""
    from ingestion.router import _insufficient_data_components

    readings = [
        _reading('C1', 'LOT-EQ', 'PN1', 'iddq', 0.0, 1.0),
        _reading('C1', 'LOT-EQ', 'PN1', 'iddq', 24.0, 1.0),
        _reading('C2', 'LOT-EQ', 'PN1', 'iddq', 0.0, 1.0),
        _reading('C3', 'LOT-EQ', 'PN1', 'leakage', 0.0, 1.0),
        _reading('C3', 'LOT-EQ', 'PN1', 'leakage', 24.0, 1.0),
        _reading('C3', 'LOT-EQ', 'PN1', 'leakage', 96.0, 1.0),
    ]
    lot = LotDataset(lot_id='LOT-EQ', part_number='PN1', status='COMPLETE', readings=readings, account_id='ACC')
    result = run_full_pipeline(lot, ScreeningConfig())

    assert result.insufficient_data_components == _insufficient_data_components(readings)
    assert result.insufficient_data_components == ['C2']
