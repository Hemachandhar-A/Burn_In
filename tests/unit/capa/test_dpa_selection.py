"""E13 step 5 / context.md 5.19 (Block 4a Part 5, Lead ruling D70.5): select_dpa_work_order - the
DPA-sample selection rule, as a pure function over an already-computed AnalysisResults (no I/O, no
re-running any module). Up to 3 recommendations, each with a real computed-sentence reason, no part
twice, deterministic, ties broken by component_id ascending:
    (i)   highest combined severity (Module A) among flagged (WATCH/REJECT) parts
    (ii)  highest Module B interval width among WATCH-tier parts (the boundary tier per context.md
          6.2 - "crossed REVIEW only" sits exactly between PASS and REJECT), falling back to
          REJECT-tier parts only if no WATCH-tier part has a usable interval
    (iii) one control part: lowest component_id among PASS-tier parts not already chosen
"""
from contracts import AnalysisResults, LotDisposition, ModuleAResult, ModuleBResult, RiskAssessment
from capa.logic import select_dpa_work_order


def _assessment(component_id, verdict, lot_id="lot_001"):
    return RiskAssessment(
        component_id=component_id, lot_id=lot_id, verdict=verdict,
        module_a_rank=1.0, module_b_rank=1.0, worst_parameter="leakage",
        module_a_ran=True, module_b_ran=True, predicted_168h=None, actual_168h=None,
        explanation_sentence=None,
    )


def _module_a(component_id, combined_severity, lot_id="lot_001"):
    return ModuleAResult(
        component_id=component_id, lot_id=lot_id, parameter="leakage", robust_z=1.0, mcd_distance=None,
        isolation_forest_score=None, ecod_score=0.1, explainable_tags={"robust_z": True, "mcd": False,
        "isolation_forest": False, "ecod": False}, direction="above_median", severity_tier="REVIEW",
        severity_cap_reason=None, combined_severity=combined_severity, explainable_corroboration=True,
    )


def _module_b(component_id, interval_lower, interval_upper, lot_id="lot_001"):
    return ModuleBResult(
        component_id=component_id, lot_id=lot_id, parameter="leakage", predicted_168h=20.0,
        interval_lower=interval_lower, interval_upper=interval_upper, physics_baseline_prediction=None,
        physics_disagreement_gap=None, drift_rate=0.1, exceeds_safety_slope=False, safety_slope=0.5,
        lower_bound_exceeds_safety_slope=False, forecast_unavailable=False,
    )


def _results(assessments, module_a_results=None, module_b_results=None):
    return AnalysisResults(
        assessments=assessments,
        disposition=LotDisposition(lot_id="lot_001", status="COMPLETE", pda_result=0.0, verdict="REJECT",
                                    is_forecast=False),
        module_a_results=module_a_results or {},
        module_b_results=module_b_results or {},
    )


def test_picks_highest_severity_uncertainty_and_control_no_duplicates():
    results = _results(
        assessments=[
            _assessment("HIGH-SEV", "REJECT"),
            _assessment("MID-SEV", "WATCH"),
            _assessment("PASS-1", "PASS"),
            _assessment("PASS-2", "PASS"),
        ],
        module_a_results={
            "HIGH-SEV": _module_a("HIGH-SEV", 0.99),
            "MID-SEV": _module_a("MID-SEV", 0.60),
            "PASS-1": _module_a("PASS-1", 0.05),
            "PASS-2": _module_a("PASS-2", 0.02),
        },
        module_b_results={
            "HIGH-SEV": _module_b("HIGH-SEV", 10.0, 11.0),  # narrow interval, width 1.0
            "MID-SEV": _module_b("MID-SEV", 5.0, 12.0),     # wide interval, width 7.0
        },
    )
    recs = select_dpa_work_order(results)
    component_ids = [r.component_id for r in recs]
    assert component_ids == ["HIGH-SEV", "MID-SEV", "PASS-1"]
    assert len(set(component_ids)) == 3  # no part twice
    assert "0.99" in recs[0].reason
    assert "7.00" in recs[1].reason
    assert "PASS" in recs[2].reason


def test_all_pass_lot_returns_only_a_control_part():
    results = _results(
        assessments=[_assessment("P1", "PASS"), _assessment("P2", "PASS")],
        module_a_results={"P1": _module_a("P1", 0.1), "P2": _module_a("P2", 0.05)},
    )
    recs = select_dpa_work_order(results)
    assert len(recs) == 1
    assert recs[0].component_id == "P1"  # lowest component_id ascending


def test_ties_broken_by_component_id_ascending():
    results = _results(
        assessments=[_assessment("Z-COMP", "REJECT"), _assessment("A-COMP", "REJECT")],
        module_a_results={"Z-COMP": _module_a("Z-COMP", 0.5), "A-COMP": _module_a("A-COMP", 0.5)},
    )
    recs = select_dpa_work_order(results)
    assert recs[0].component_id == "A-COMP"  # tie on severity -> ascending component_id


def test_deterministic_across_repeated_calls():
    results = _results(
        assessments=[_assessment("A", "REJECT"), _assessment("B", "WATCH"), _assessment("C", "PASS")],
        module_a_results={"A": _module_a("A", 0.9), "B": _module_a("B", 0.4), "C": _module_a("C", 0.1)},
        module_b_results={"B": _module_b("B", 1.0, 3.0)},
    )
    first = select_dpa_work_order(results)
    second = select_dpa_work_order(results)
    assert [r.model_dump() for r in first] == [r.model_dump() for r in second]


def test_watch_tier_preferred_over_reject_for_boundary_uncertainty_pick():
    # REJECT part has a wider interval than the WATCH part, but WATCH is the boundary tier -
    # the WATCH part should still win slot (ii), per context.md 6.2's own definition of WATCH as
    # sitting exactly on the boundary; REJECT is only a fallback when no WATCH part has a usable interval.
    results = _results(
        assessments=[
            _assessment("REJ", "REJECT"),
            _assessment("WATCH-PART", "WATCH"),
            _assessment("CONTROL", "PASS"),
        ],
        module_a_results={
            "REJ": _module_a("REJ", 0.95),  # already takes slot (i), so excluded from slot (ii)
            "WATCH-PART": _module_a("WATCH-PART", 0.4),
        },
        module_b_results={
            "REJ": _module_b("REJ", 0.0, 20.0),        # width 20.0 - wider, but not the boundary tier
            "WATCH-PART": _module_b("WATCH-PART", 5.0, 10.0),  # width 5.0
        },
    )
    recs = select_dpa_work_order(results)
    ids = [r.component_id for r in recs]
    assert ids[0] == "REJ"           # highest severity
    assert ids[1] == "WATCH-PART"    # boundary tier wins slot (ii) even though REJ's interval is wider
    assert ids[2] == "CONTROL"


def test_boundary_pick_falls_back_to_reject_tier_when_no_watch_part_has_a_usable_interval():
    results = _results(
        assessments=[_assessment("REJ-HIGH", "REJECT"), _assessment("REJ-LOW", "REJECT"),
                     _assessment("CONTROL", "PASS")],
        module_a_results={"REJ-HIGH": _module_a("REJ-HIGH", 0.95), "REJ-LOW": _module_a("REJ-LOW", 0.2)},
        module_b_results={"REJ-LOW": _module_b("REJ-LOW", 2.0, 9.0)},  # only non-severity-picked part with an interval
    )
    recs = select_dpa_work_order(results)
    ids = [r.component_id for r in recs]
    assert ids[0] == "REJ-HIGH"
    assert ids[1] == "REJ-LOW"  # fallback: no WATCH-tier candidate exists at all
    assert ids[2] == "CONTROL"


def test_fewer_than_three_when_lot_has_fewer_eligible_parts():
    results = _results(
        assessments=[_assessment("ONLY-REJECT", "REJECT")],
        module_a_results={"ONLY-REJECT": _module_a("ONLY-REJECT", 0.8)},
    )
    recs = select_dpa_work_order(results)
    assert len(recs) == 1
    assert recs[0].component_id == "ONLY-REJECT"


def test_missing_module_b_interval_excluded_from_uncertainty_pick():
    results = _results(
        assessments=[_assessment("REJ", "REJECT"), _assessment("WATCH-NO-INTERVAL", "WATCH"),
                     _assessment("CONTROL", "PASS")],
        module_a_results={"REJ": _module_a("REJ", 0.9), "WATCH-NO-INTERVAL": _module_a("WATCH-NO-INTERVAL", 0.3)},
        module_b_results={
            "WATCH-NO-INTERVAL": ModuleBResult(
                component_id="WATCH-NO-INTERVAL", lot_id="lot_001", parameter="leakage",
                predicted_168h=None, interval_lower=None, interval_upper=None,
                physics_baseline_prediction=None, physics_disagreement_gap=None, drift_rate=None,
                exceeds_safety_slope=None, safety_slope=None, lower_bound_exceeds_safety_slope=None,
                forecast_unavailable=True,
            ),
        },
    )
    recs = select_dpa_work_order(results)
    ids = [r.component_id for r in recs]
    assert "WATCH-NO-INTERVAL" not in ids[:2]  # no usable interval -> not picked for slot (ii)
    assert ids[0] == "REJ"
