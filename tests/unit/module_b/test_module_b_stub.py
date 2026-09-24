"""P4.0 stub tests: the canned ModuleBResult output P5 builds against before Module B is real."""

from contracts import FeatureFrame, ModuleBResult, ScreeningConfig
from module_b import STUB_RESULTS, predict

FORECAST_FIELDS = (
    "predicted_168h",
    "interval_lower",
    "interval_upper",
    "physics_baseline_prediction",
    "physics_disagreement_gap",
    "drift_rate",
    "exceeds_safety_slope",
)


def _frame(component_id: str) -> FeatureFrame:
    return FeatureFrame(
        component_id=component_id,
        lot_id="LOT-STUB",
        value_0h=10.0,
        value_24h=11.0,
        value_96h=None,
        delta_24h=1.0,
        delta_96h=None,
        lot_median_0h=10.0,
        lot_median_24h=11.0,
        robust_z={"iddq_0h": 0.0, "iddq_24h": 0.0},
        lot_size=77,
        used_pooled_fallback=False,
        elapsed_hours=[0.0, 24.0],
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


def test_predict_returns_one_result_per_frame_with_its_component_id():
    frames = [_frame(f"C{i:03d}") for i in range(5)]
    results = predict(frames, ScreeningConfig())
    assert [r.component_id for r in results] == [f.component_id for f in frames]
    assert all(isinstance(r, ModuleBResult) for r in results)


def test_predict_is_deterministic_and_does_not_mutate_the_fixture():
    frames = [_frame("C900"), _frame("C901"), _frame("C902")]
    before = [r.model_copy() for r in STUB_RESULTS]
    assert predict(frames) == predict(frames)
    assert list(STUB_RESULTS) == before


def test_predict_on_empty_input_returns_empty():
    assert predict([]) == []
