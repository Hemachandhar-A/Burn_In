"""E3 steps 6-7 (session P4.3): the real `module_b.predict` - what P5's `fusion.run_full_pipeline` calls
in-process (IMPLEMENTATION_PLAN.md Part 5.7). Assembles one `ModuleBResult` per input from P4.2's
calibrated forecast plus the physics-vs-model disagreement (step 6), recording every E3 step 7 field.

Out-of-scope parameters (context.md 5.9): a parameter outside TRAINED_PARAMETERS is declined by rule -
`forecast_unavailable=True`, every forecast field None - even if a model for it happened to exist. So is
any input whose (part_number, parameter, horizon) has no calibrated model: never an uncalibrated guess.

Physics baseline (step 6): the power-law baseline (module_b.baselines), with its exponent fit over the
whole batch per (lot, parameter) - callers pass a lot's frames together, as fusion does. The gap is
|predicted_168h - physics_baseline_prediction|; the sign is recoverable from the two stored values.

TEMP model source (CONTRACT_CHANGES.md 2026-09-26 P4, "Where do Module B's trained models come from",
OPEN): with `models=None`, each part number gets a synthetic prior - TEMP_SYNTHETIC_LOTS Complete lots
from P1's `generate_lot` (fixed seeds), run through `features.compute`, calibrated with P4.2's
`calibrate_drift_models`, cached in-process. Its intervals are calibrated on synthetic lots, not on the
uploaded part's own history.
"""

from functools import cache

from contracts import ModuleBInput, ModuleBResult, ScreeningConfig
from features.compute import compute
from generator.lot import generate_lot
from module_b.baselines import physics_baselines
from module_b.calibration import CalibratedDriftModel, calibrate_drift_models, forecast
from module_b.model import usable_input

# The three parameters the generator - and so every trained model - covers (context.md 1.3, 5.9).
TRAINED_PARAMETERS = frozenset({"iddq", "leakage", "prop_delay"})

TEMP_SYNTHETIC_LOTS = 14
_TEMP_SYNTHETIC_ACCOUNT = "module_b.synthetic_prior"  # generate_lot requires an attribution; never stored


@cache
def TEMP_synthetic_models(part_number: str) -> dict[tuple[str, str], CalibratedDriftModel]:
    frames = []
    for seed in range(TEMP_SYNTHETIC_LOTS):
        lot = generate_lot(f"SYNTHETIC-{part_number}-{seed:03d}", part_number, seed, account_id=_TEMP_SYNTHETIC_ACCOUNT)
        frames += compute(lot.dataset)
    return calibrate_drift_models(frames)


def _unavailable(frame: ModuleBInput) -> ModuleBResult:
    return ModuleBResult(
        component_id=frame.component_id,
        lot_id=frame.lot_id,
        parameter=frame.parameter,
        predicted_168h=None,
        interval_lower=None,
        interval_upper=None,
        physics_baseline_prediction=None,
        physics_disagreement_gap=None,
        drift_rate=None,
        exceeds_safety_slope=None,
        safety_slope=None,
        forecast_unavailable=True,
    )


def predict(
    frames: list[ModuleBInput],
    config: ScreeningConfig | None = None,
    *,
    models: dict[tuple[str, str], CalibratedDriftModel] | None = None,
) -> list[ModuleBResult]:
    """One ModuleBResult per input, in input order. Callers convert each FeatureFrame with
    contracts.to_module_b_input first - 168h never reaches here. `config` is accepted for the Part 5.7
    call shape; no ScreeningConfig field governs Module B yet.

    Every input passes `usable_input` first: a non-finite required input is forecast_unavailable, and a
    non-finite 96h read is treated as absent (forecast at the 24h horizon) - so no NaN/inf ever reaches the
    model, the physics fit, or a returned field."""
    # Parallel to `frames`: the cleaned input to forecast from, or None when the part is declined.
    usable = [usable_input(f) if f.parameter in TRAINED_PARAMETERS else None for f in frames]
    in_scope = [u for u in usable if u is not None]
    if models is None:
        models = {}
        for part_number in sorted({u.part_number for u in in_scope}):
            models.update(TEMP_synthetic_models(part_number))

    forecasts = iter(forecast(models, in_scope))
    baselines = physics_baselines(in_scope)

    results = []
    for f, u in zip(frames, usable):
        fc = next(forecasts) if u is not None else None
        if fc is None:
            results.append(_unavailable(f))
            continue
        physics = baselines[(u.lot_id, u.component_id, u.parameter)].power_law
        results.append(
            ModuleBResult(
                component_id=f.component_id,
                lot_id=f.lot_id,
                parameter=f.parameter,
                predicted_168h=fc.predicted_168h,
                interval_lower=fc.interval_lower,
                interval_upper=fc.interval_upper,
                physics_baseline_prediction=physics,
                physics_disagreement_gap=abs(fc.predicted_168h - physics),
                drift_rate=fc.drift_rate,
                exceeds_safety_slope=fc.exceeds_safety_slope,
                safety_slope=fc.safety_slope,
                forecast_unavailable=False,
            )
        )
    return results
