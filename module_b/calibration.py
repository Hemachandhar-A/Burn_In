"""E3 steps 3-5 (session P4.2): conformalized quantile regression (MAPIE CQR) calibrated per
(part_number, parameter) across lots, the calibrated safety slope, and the early-reject flag.

Lot boundaries (AGENTS.md rule 8). Each (part_number, parameter)'s lots are split once, by a seeded
shuffle of lot ids, into training lots (fit the LightGBM quantile models) and calibration lots (conformal
scores and the safety slope). No lot is ever on both sides. A part number needs >= 2 lots with a
measured 168h reading before it can be calibrated at all; with fewer, it gets no model and so no forecast
- never an uncalibrated guess (context.md 4.4, 5.9). The per-lot calibration fallback context.md 4.4
mentions is not built here; pooled-across-lots is the default it names.

Horizons. The quantile models are fit once on both horizons' training rows (module_b.model's as-measured
and 24h-view rows), then conformalized separately per horizon: "96h" inputs (a 96h read exists) and
"24h" inputs (it doesn't). This keeps each part's two views out of the same calibration set, where they
would be correlated scores, and gives a 24h-only In-Progress lot the wider interval it should have.

Safety slope (E3 step 4, context.md 4.4). The calibrated upper quantile of healthy-part drift rate:
the conformal (finite-sample) q-quantile of the *measured* 0h->168h drift rate over the calibration
lots' healthy parts. "Healthy" is module_b.baselines.is_healthy (robust-z core at 0h/24h/96h - no
defect labels exist outside the harness). One slope per (part_number, parameter), in that parameter's
units per hour, shared by both horizons since it describes measured outcomes, not predictions.

Early reject (E3 step 5): a part's *predicted* drift rate, (predicted_168h - value_0h) / (168 - t0),
above its slope. Upward drift only - every trained parameter degrades upward (context.md 1.3-1.4);
downward anomalies are Module A's direction-aware check, not this flag.

CONFIDENCE_LEVEL and SLOPE_QUANTILE are disclosed defaults (0.90 is MAPIE's own default coverage; 0.95
is a conventional upper tail), not values derived from evidence.
"""

import copy
import math
from dataclasses import dataclass

import numpy as np
from mapie.regression import ConformalizedQuantileRegressor

from contracts import FeatureFrame, ModuleBInput, to_module_b_input
from module_b.baselines import TARGET_HOURS, is_healthy, persistence
from module_b.model import DEFAULT_SEED, build_training_set, feature_matrix, make_quantile_regressor

DEFAULT_CONFIDENCE_LEVEL = 0.90
DEFAULT_SLOPE_QUANTILE = 0.95
DEFAULT_CALIBRATION_FRACTION = 0.3
HORIZONS = ("96h", "24h")


@dataclass(frozen=True)
class CalibratedDriftModel:
    part_number: str
    parameter: str
    regressors: dict[str, ConformalizedQuantileRegressor]  # keyed by horizon; a horizon with no
    # calibration rows is absent, and inputs at that horizon get no forecast
    safety_slope: float
    confidence_level: float
    slope_quantile: float
    train_lots: tuple[str, ...]
    calibration_lots: tuple[str, ...]


@dataclass(frozen=True)
class DriftForecast:
    """Module B's per-part forecast before P4.3 assembles ModuleBResult. `safety_slope` is carried here
    because ModuleBResult has no field for it yet (CONTRACT_CHANGES.md 2026-09-26 P4)."""

    component_id: str
    parameter: str
    horizon: str
    predicted_168h: float
    interval_lower: float
    interval_upper: float
    drift_rate: float
    safety_slope: float
    exceeds_safety_slope: bool


def horizon_of(frame: ModuleBInput) -> str:
    return "96h" if frame.value_96h is not None else "24h"


def split_lots(lot_ids, calibration_fraction: float, seed: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(train_lots, calibration_lots): a seeded shuffle of the sorted unique lot ids, at least one lot
    on each side. Independent of input order."""
    lots = sorted(set(lot_ids))
    if len(lots) < 2:
        raise ValueError(f"need >= 2 lots to split by lot, got {len(lots)}")
    order = np.random.default_rng(seed).permutation(len(lots))
    n_cal = min(max(1, round(calibration_fraction * len(lots))), len(lots) - 1)
    cal = tuple(sorted(lots[i] for i in order[:n_cal]))
    train = tuple(sorted(lots[i] for i in order[n_cal:]))
    return train, cal


def drift_rate(frame: ModuleBInput, value_168h: float) -> float:
    """Change per hour from the part's 0h read to 168h."""
    return (value_168h - frame.value_0h) / (TARGET_HOURS - frame.elapsed_hours["0h"])


def conformal_upper_quantile(values, q: float) -> float:
    """The ceil((n+1)q)-th smallest value - the finite-sample-valid upper quantile. Raises when n is too
    small for that rank to exist, rather than quietly returning the max."""
    arr = np.sort(np.asarray(values, dtype=float))
    rank = math.ceil((len(arr) + 1) * q)
    if rank > len(arr):
        raise ValueError(f"{len(arr)} values is too few for a calibrated {q} quantile")
    return float(arr[rank - 1])


def _calibrate_one(
    frames: list[FeatureFrame], confidence_level: float, slope_quantile: float, calibration_fraction: float,
    seed: int,
) -> CalibratedDriftModel | None:
    complete = [f for f in frames if f.value_168h is not None]
    if len({f.lot_id for f in complete}) < 2:
        return None
    train_lots, cal_lots = split_lots([f.lot_id for f in complete], calibration_fraction, seed)
    cal_set = set(cal_lots)
    train_frames = [f for f in complete if f.lot_id not in cal_set]
    cal_frames = [f for f in complete if f.lot_id in cal_set]

    healthy_rates = []
    for f in cal_frames:
        seen = to_module_b_input(f)
        if is_healthy(seen):
            healthy_rates.append(drift_rate(seen, f.value_168h))
    try:
        slope = conformal_upper_quantile(healthy_rates, slope_quantile)
    except ValueError:
        return None

    train = build_training_set(train_frames)
    fitted = ConformalizedQuantileRegressor(make_quantile_regressor(seed=seed), confidence_level=confidence_level)
    fitted.fit(train.X, train.y)

    cal = build_training_set(cal_frames)
    is_24h = np.isnan(cal.X[:, 1])  # delta_96h column
    regressors = {}
    for horizon, mask in (("96h", ~is_24h), ("24h", is_24h)):
        if mask.any():
            regressors[horizon] = copy.deepcopy(fitted).conformalize(cal.X[mask], cal.y[mask])

    first = complete[0]
    return CalibratedDriftModel(
        part_number=first.part_number,
        parameter=first.parameter,
        regressors=regressors,
        safety_slope=slope,
        confidence_level=confidence_level,
        slope_quantile=slope_quantile,
        train_lots=train_lots,
        calibration_lots=cal_lots,
    )


def calibrate_drift_models(
    frames: list[FeatureFrame],
    *,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    slope_quantile: float = DEFAULT_SLOPE_QUANTILE,
    calibration_fraction: float = DEFAULT_CALIBRATION_FRACTION,
    seed: int = DEFAULT_SEED,
) -> dict[tuple[str, str], CalibratedDriftModel]:
    """One CalibratedDriftModel per (part_number, parameter) that has enough lots and healthy calibration
    parts; keys without them are absent."""
    by_key: dict[tuple[str, str], list[FeatureFrame]] = {}
    for f in frames:
        by_key.setdefault((f.part_number, f.parameter), []).append(f)
    models = {}
    for key in sorted(by_key):
        model = _calibrate_one(by_key[key], confidence_level, slope_quantile, calibration_fraction, seed)
        if model is not None:
            models[key] = model
    return models


def forecast(
    models: dict[tuple[str, str], CalibratedDriftModel], inputs: list[ModuleBInput]
) -> list[DriftForecast | None]:
    """Per input, in order: a calibrated forecast, or None when its (part_number, parameter) or horizon
    has no calibrated model."""
    out: list[DriftForecast | None] = [None] * len(inputs)
    groups: dict[tuple[tuple[str, str], str], list[int]] = {}
    for idx, f in enumerate(inputs):
        key = (f.part_number, f.parameter)
        if key in models and horizon_of(f) in models[key].regressors:
            groups.setdefault((key, horizon_of(f)), []).append(idx)

    for (key, horizon), idxs in groups.items():
        model = models[key]
        chosen = [inputs[i] for i in idxs]
        point, intervals = model.regressors[horizon].predict_interval(feature_matrix(chosen))
        for i, f, p, lo, hi in zip(idxs, chosen, point, intervals[:, 0, 0], intervals[:, 1, 0]):
            anchor = persistence(f)
            predicted = float(anchor + p)
            # Widen, never narrow, so lower <= point <= upper always holds (Part 7.3); widening can only
            # raise coverage.
            lower = min(float(anchor + lo), predicted)
            upper = max(float(anchor + hi), predicted)
            rate = drift_rate(f, predicted)
            out[i] = DriftForecast(
                component_id=f.component_id,
                parameter=f.parameter,
                horizon=horizon,
                predicted_168h=predicted,
                interval_lower=lower,
                interval_upper=upper,
                drift_rate=rate,
                safety_slope=model.safety_slope,
                exceeds_safety_slope=rate > model.safety_slope,
            )
    return out
