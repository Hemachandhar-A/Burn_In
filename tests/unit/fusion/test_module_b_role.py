"""Session I3 Part 3: Module B's role in a FINISHED lot's part verdict (docs/MODULE_B_ROLE_EXPERIMENT.md).

The truth table is the pre-registered one (variants a-d). `compute_part_verdict(a, b)` with no role keeps today's behaviour
(the in-progress path); the role only applies when the pipeline passes it for a COMPLETE lot."""
import itertools

import pytest

from contracts import ModuleAResult, ModuleBResult
from fusion.gate import compute_part_verdict
from fusion.settings import DEFAULT_MODULE_B_ROLE, MODULE_B_ROLES, module_b_finished_lot_role
from scripts.module_b_role_experiment import add_variants, b_tier, fuse
import pandas as pd


def _a(tier="PASS", explainable=True):
    return ModuleAResult(
        component_id="C1", lot_id="L1", parameter="iddq", robust_z=2.0, mcd_distance=None, isolation_forest_score=None,
        ecod_score=0.0, explainable_tags={"robust_z": True, "mcd": True, "isolation_forest": False, "ecod": False},
        direction="above_median", severity_tier=tier, severity_cap_reason=None, combined_severity=0.5,
        explainable_corroboration=explainable)


def _b(exceeds, lower):
    return ModuleBResult(
        component_id="C1", lot_id="L1", parameter="iddq", predicted_168h=1.0, interval_lower=0.5, interval_upper=2.0,
        physics_baseline_prediction=1.0, physics_disagreement_gap=0.1, drift_rate=1.0, exceeds_safety_slope=exceeds,
        lower_bound_exceeds_safety_slope=lower, safety_slope=0.5, forecast_unavailable=False)


B_STATES = [(False, False), (True, False), (True, True)]  # (exceeds, lower bound exceeds): the lower bound cannot exceed alone


def test_roles_and_default():
    assert MODULE_B_ROLES == ("current", "tiered", "advisory", "off")
    assert DEFAULT_MODULE_B_ROLE == "advisory"


def test_setting_reads_the_environment_on_every_call(monkeypatch):
    monkeypatch.delenv("MODULE_B_FINISHED_LOT_ROLE", raising=False)
    assert module_b_finished_lot_role() == "advisory"
    for role in MODULE_B_ROLES:
        monkeypatch.setenv("MODULE_B_FINISHED_LOT_ROLE", role)
        assert module_b_finished_lot_role() == role
    monkeypatch.setenv("MODULE_B_FINISHED_LOT_ROLE", "  ")
    assert module_b_finished_lot_role() == "advisory"
    monkeypatch.setenv("MODULE_B_FINISHED_LOT_ROLE", "bogus")
    with pytest.raises(ValueError):
        module_b_finished_lot_role()


def test_no_role_argument_is_todays_behaviour():
    for a_tier, (ex, lb) in itertools.product(("PASS", "REVIEW", "REJECT"), B_STATES):
        assert compute_part_verdict(_a(a_tier), _b(ex, lb))[0] == compute_part_verdict(_a(a_tier), _b(ex, lb), b_role="current")[0]
    assert compute_part_verdict(_a("PASS"), _b(True, False))[0] == "REJECT"


@pytest.mark.parametrize("role", MODULE_B_ROLES)
@pytest.mark.parametrize("a_tier", ["PASS", "REVIEW", "REJECT"])
@pytest.mark.parametrize("state", B_STATES)
def test_gate_equals_the_preregistered_offline_combination(role, a_tier, state):
    ex, lb = state
    verdict, _cap, _tier = compute_part_verdict(_a(a_tier), _b(ex, lb), b_role=role)
    assert verdict == fuse(a_tier, b_tier(role, ex, lb))


def test_current_b_alone_rejects():
    assert compute_part_verdict(_a("PASS"), _b(True, False), b_role="current")[0] == "REJECT"


def test_tiered_b_alone_is_watch_unless_the_lower_bound_also_exceeds():
    assert compute_part_verdict(_a("PASS"), _b(True, False), b_role="tiered")[0] == "WATCH"
    assert compute_part_verdict(_a("PASS"), _b(True, True), b_role="tiered")[0] == "REJECT"
    assert compute_part_verdict(_a("PASS"), _b(False, False), b_role="tiered")[0] == "PASS"
    # the existing table: A REVIEW with B REVIEW is REJECT
    assert compute_part_verdict(_a("REVIEW"), _b(True, False), b_role="tiered")[0] == "REJECT"


@pytest.mark.parametrize("role", ["advisory", "off"])
def test_advisory_and_off_leave_module_a_alone_in_charge(role):
    for a_tier, (ex, lb) in itertools.product(("PASS", "REVIEW", "REJECT"), B_STATES):
        expected, _c, _t = compute_part_verdict(_a(a_tier), None, b_role="current")
        assert compute_part_verdict(_a(a_tier), _b(ex, lb), b_role=role)[0] == expected


def test_explainability_gate_still_applies_under_every_role():
    for role in MODULE_B_ROLES:
        verdict, cap, tier = compute_part_verdict(_a("REJECT", explainable=False), _b(False, False), b_role=role)
        assert (verdict, cap, tier) == ("WATCH", "explainability_gate", "REVIEW")


def test_unavailable_forecast_is_pass_in_every_role():
    unavailable = ModuleBResult(
        component_id="C1", lot_id="L1", parameter="iddq", predicted_168h=None, interval_lower=None, interval_upper=None,
        physics_baseline_prediction=None, physics_disagreement_gap=None, drift_rate=None, exceeds_safety_slope=None,
        lower_bound_exceeds_safety_slope=None, safety_slope=None, forecast_unavailable=True)
    for role in MODULE_B_ROLES:
        assert compute_part_verdict(_a("PASS"), unavailable, b_role=role)[0] == "PASS"


def test_unknown_role_is_rejected():
    with pytest.raises(ValueError):
        compute_part_verdict(_a("PASS"), _b(True, True), b_role="bogus")


def test_offline_add_variants_uses_the_same_functions():
    parts = pd.DataFrame([{"a_tier": "REJECT", "a_explainable": False, "b_exceeds": True, "b_lb_exceeds": True}])
    out = add_variants(parts).iloc[0]
    assert (out.verdict_current, out.verdict_tiered, out.verdict_advisory, out.verdict_off) == ("REJECT", "REJECT", "WATCH", "WATCH")
