"""P4.0 stub - fixed, contract-shaped ModuleBResult values (IMPLEMENTATION_PLAN.md R6).

Every value here is fake. `module_b.predict` is real since P4.3 (module_b/predictor.py); these rows
stay as a fast, training-free fixture covering every branch P5 must handle.
"""

from contracts import ModuleBResult

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

