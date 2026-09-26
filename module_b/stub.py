"""P4.0 stub - fixed, contract-shaped ModuleBResult values (IMPLEMENTATION_PLAN.md R6).

Lets P5 build fusion/explainability against Module B's real output shape before the model
exists. Every value here is fake. Replaced by the real predictor in P4.1-P4.3; the public
`predict` signature is what stays.
"""

from contracts import ModuleBInput, ModuleBResult, ScreeningConfig

# One row per branch P5 has to handle: an ordinary forecast, an early-reject forecast,
# and a parameter outside the trained three (context.md 5.9) - every forecast field None.
STUB_RESULTS: tuple[ModuleBResult, ...] = (
    ModuleBResult(
        component_id="STUB-C001",
        parameter="iddq",
        predicted_168h=12.4,
        interval_lower=11.1,
        interval_upper=13.9,
        physics_baseline_prediction=12.1,
        physics_disagreement_gap=0.3,
        drift_rate=0.0143,
        exceeds_safety_slope=False,
        safety_slope=0.0183,
        forecast_unavailable=False,
    ),
    ModuleBResult(
        component_id="STUB-C002",
        parameter="leakage",
        predicted_168h=48.0,
        interval_lower=41.5,
        interval_upper=55.2,
        physics_baseline_prediction=44.0,
        physics_disagreement_gap=4.0,
        drift_rate=0.2262,
        exceeds_safety_slope=True,
        safety_slope=0.0520,
        forecast_unavailable=False,
    ),
    ModuleBResult(
        component_id="STUB-C003",
        parameter="vdd_ripple",
        predicted_168h=None,
        interval_lower=None,
        interval_upper=None,
        physics_baseline_prediction=None,
        physics_disagreement_gap=None,
        drift_rate=None,
        exceeds_safety_slope=None,
        safety_slope=None,
        forecast_unavailable=True,
    ),
)


def predict(frames: list[ModuleBInput], config: ScreeningConfig | None = None) -> list[ModuleBResult]:
    """Stub: one result per frame, cycling through STUB_RESULTS, keyed to the frame's component_id.

    Callers convert each FeatureFrame with contracts.to_module_b_input first - 168h never reaches here.
    """
    return [
        STUB_RESULTS[i % len(STUB_RESULTS)].model_copy(update={"component_id": frame.component_id})
        for i, frame in enumerate(frames)
    ]
