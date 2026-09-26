"""P4.0 stub fixture tests: canned, contract-valid ModuleBResult rows covering every branch P5 must handle.
module_b.predict is real since P4.3 (test_module_b_predictor.py); the fixture stays for fast P5 tests."""

from contracts import ModuleBResult
from module_b import STUB_RESULTS

FORECAST_FIELDS = (
    "predicted_168h",
    "interval_lower",
    "interval_upper",
    "physics_baseline_prediction",
    "physics_disagreement_gap",
    "drift_rate",
    "exceeds_safety_slope",
    "safety_slope",
)


def test_stub_results_validate_against_frozen_contract():
    for result in STUB_RESULTS:
        assert ModuleBResult.model_validate(result.model_dump()) == result


def test_stub_covers_every_branch_p5_must_handle():
    available = [r for r in STUB_RESULTS if not r.forecast_unavailable]
    assert any(r.exceeds_safety_slope is True for r in available)
    assert any(r.exceeds_safety_slope is False for r in available)
    assert any(r.forecast_unavailable for r in STUB_RESULTS)


def test_unavailable_forecast_never_carries_a_guessed_value():
    # 7.3 row 1 / AGENTS.md rule 7: unavailable means every forecast field is None, never zero.
    for result in STUB_RESULTS:
        if result.forecast_unavailable:
            assert all(getattr(result, f) is None for f in FORECAST_FIELDS)
            assert result.parameter not in {"iddq", "leakage", "prop_delay"}


def test_stub_intervals_are_ordered():
    # 7.3 row 3: lower <= point <= upper, held even by the stub so P5 never sees a malformed interval.
    for result in STUB_RESULTS:
        if not result.forecast_unavailable:
            assert result.interval_lower <= result.predicted_168h <= result.interval_upper


def test_stub_records_the_threshold_used_and_its_flag_agrees_with_it():
    # E3 step 7 / CONTRACT_CHANGES 2026-09-26: safety_slope is the threshold drift_rate was compared against.
    for result in STUB_RESULTS:
        if result.forecast_unavailable:
            continue
        assert result.safety_slope is not None
        assert result.exceeds_safety_slope == (result.drift_rate > result.safety_slope)
