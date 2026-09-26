"""E3 step 2 (session P4.1): one global LightGBM quantile-regression model per part number, pooled across
lots - not separate per-lot models.

"Per part number" is applied per (part_number, parameter): a frame is parameter-scoped by contract, and
iddq/leakage/prop_delay carry different units and different physics (context.md 1.3-1.4), so one tree
ensemble spanning all three would mix scales in a single quantile loss.

Features. E3's input vector is [value_0h, value_24h, (value_96h), lot_median_0h, lot_median_24h,
elapsed_hours]. The model sees exactly that information, re-expressed as drift and lot-relative offsets
(FEATURE_NAMES) - trees split on thresholds and cannot subtract two columns, and absolute levels vary
from lot to lot, so raw levels overfit to the handful of training lots. The target is likewise the
residual on top of the persistence baseline (168h minus the latest reading); `predict_168h` adds the
latest reading back, so the output is a Value_168h prediction.

Leakage (AGENTS.md rule 6). Features are built only from `ModuleBInput`, which has no 168h field; the
target is read from the `FeatureFrame` separately. Training also adds a 96h-masked "24h view" of every
Complete-lot part, since early rejection runs on 24h-only In-Progress lots and a model trained only on
rows that always had 96h would never have learned its NaN branch.
"""

import math
from dataclasses import dataclass

import numpy as np
from lightgbm import LGBMRegressor

from contracts import FeatureFrame, ModuleBInput, to_module_b_input
from module_b.baselines import persistence

FEATURE_NAMES = (
    "delta_24h",  # value_24h - value_0h
    "delta_96h",  # value_96h - value_0h, NaN when absent (LightGBM's native missing-value branch)
    "offset_0h",  # value_0h - lot_median_0h
    "offset_24h",  # value_24h - lot_median_24h
    "lot_drift_24h",  # lot_median_24h - lot_median_0h
    "elapsed_24h",  # actual hours from this part's 0h read to its 24h read
    "elapsed_96h",  # likewise for 96h, NaN when absent
    "value_0h",  # absolute level, for level-dependent drift (leakage-style mechanisms)
)

DEFAULT_SEED = 0

# Deliberately small trees for small tabular data (tens of lots x ~77 parts). Fixed, not tuned per run.
_LGBM_PARAMS = {
    "n_estimators": 300,
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_child_samples": 20,
    # Determinism across runs and machines (AGENTS.md rule 9).
    "deterministic": True,
    "force_row_wise": True,
    "n_jobs": 1,
    "verbose": -1,
}


def make_quantile_regressor(alpha: float = 0.5, seed: int = DEFAULT_SEED) -> LGBMRegressor:
    """The single place the LightGBM quantile model is configured - P4.2's MAPIE CQR wraps this."""
    return LGBMRegressor(objective="quantile", alpha=alpha, random_state=seed, **_LGBM_PARAMS)


def view_at_24h(frame: ModuleBInput) -> ModuleBInput:
    """The same part as seen before its 96h read: 96h removed from every field that carries it."""
    return frame.model_copy(
        update={
            "value_96h": None,
            "delta_96h": None,
            "robust_z": {k: v for k, v in frame.robust_z.items() if k != "96h"},
            "elapsed_hours": {k: v for k, v in frame.elapsed_hours.items() if k != "96h"},
        }
    )


def usable_input(frame: ModuleBInput) -> ModuleBInput | None:
    """The one gate every input passes before training, calibration or prediction. `Reading.value` accepts
    NaN/inf and a literal "NaN" CSV cell reaches FeatureFrame unchanged (CONTRACT_CHANGES.md 2026-09-26 P4
    non-finite readings), so finiteness is checked here rather than assumed.

    None when a required input - value_0h/24h, lot_median_0h/24h, elapsed 0h/24h - is non-finite, or the
    24h read isn't after the 0h read: a missing required input is forecast_unavailable, never a guess
    (AGENTS.md rule 7). A non-finite or out-of-order 96h read is an absent 96h read: the 24h view, not a
    value - the same thing a None 96h already means (rule 7: missing 96h is allowed, never filled in)."""
    t0 = frame.elapsed_hours.get("0h", math.nan)
    t24 = frame.elapsed_hours.get("24h", math.nan)
    required = (frame.value_0h, frame.value_24h, frame.lot_median_0h, frame.lot_median_24h, t0, t24)
    if not all(math.isfinite(v) for v in required) or t24 <= t0:
        return None
    if frame.value_96h is None:
        return frame
    t96 = frame.elapsed_hours.get("96h", math.nan)
    if not (math.isfinite(frame.value_96h) and math.isfinite(t96) and t96 > t24):
        return view_at_24h(frame)
    return frame


def feature_matrix(inputs: list[ModuleBInput]) -> np.ndarray:
    rows = []
    for f in inputs:
        t0 = f.elapsed_hours["0h"]
        has_96h = f.value_96h is not None
        rows.append(
            [
                f.value_24h - f.value_0h,
                f.value_96h - f.value_0h if has_96h else np.nan,
                f.value_0h - f.lot_median_0h,
                f.value_24h - f.lot_median_24h,
                f.lot_median_24h - f.lot_median_0h,
                f.elapsed_hours["24h"] - t0,
                f.elapsed_hours["96h"] - t0 if has_96h else np.nan,
                f.value_0h,
            ]
        )
    return np.asarray(rows, dtype=float).reshape(len(rows), len(FEATURE_NAMES))


@dataclass(frozen=True)
class TrainingSet:
    X: np.ndarray
    y: np.ndarray  # residual target: value_168h - persistence(input)
    groups: tuple[str, ...]  # lot_id per row - every split must respect it (AGENTS.md rule 8)
    component_ids: tuple[str, ...]


def build_training_set(frames: list[FeatureFrame]) -> TrainingSet:
    """Rows from frames that have a measured 168h reading, for one (part_number, parameter). Each such
    frame gives its as-measured row, plus a 24h-view row when it has a 96h read."""
    if len({(f.part_number, f.parameter) for f in frames}) > 1:
        raise ValueError("build_training_set takes frames from exactly one (part_number, parameter)")

    inputs: list[ModuleBInput] = []
    targets: list[float] = []
    for frame in frames:
        if frame.value_168h is None or not math.isfinite(frame.value_168h):
            continue
        seen = usable_input(to_module_b_input(frame))
        if seen is None:
            continue
        views = [seen, view_at_24h(seen)] if seen.value_96h is not None else [seen]
        for view in views:
            inputs.append(view)
            targets.append(frame.value_168h - persistence(view))

    return TrainingSet(
        X=feature_matrix(inputs),
        y=np.asarray(targets, dtype=float),
        groups=tuple(i.lot_id for i in inputs),
        component_ids=tuple(i.component_id for i in inputs),
    )


def train_drift_models(
    frames: list[FeatureFrame], *, alpha: float = 0.5, seed: int = DEFAULT_SEED
) -> dict[tuple[str, str], LGBMRegressor]:
    """One fitted quantile model per (part_number, parameter) that has at least one training row."""
    by_key: dict[tuple[str, str], list[FeatureFrame]] = {}
    for f in frames:
        by_key.setdefault((f.part_number, f.parameter), []).append(f)

    models: dict[tuple[str, str], LGBMRegressor] = {}
    for key in sorted(by_key):
        ts = build_training_set(by_key[key])
        if len(ts.y) == 0:
            continue
        models[key] = make_quantile_regressor(alpha, seed).fit(ts.X, ts.y)
    return models


def predict_168h(models: dict[tuple[str, str], LGBMRegressor], inputs: list[ModuleBInput]) -> list[float | None]:
    """Predicted Value_168h per input, in input order; None where no model exists for its
    (part_number, parameter) - never a guess (context.md 5.9)."""
    out: list[float | None] = [None] * len(inputs)
    by_key: dict[tuple[str, str], list[int]] = {}
    for idx, f in enumerate(inputs):
        if (f.part_number, f.parameter) in models:
            by_key.setdefault((f.part_number, f.parameter), []).append(idx)

    for key, idxs in by_key.items():
        chosen = [inputs[i] for i in idxs]
        residual = models[key].predict(feature_matrix(chosen))
        for i, f, r in zip(idxs, chosen, residual):
            out[i] = float(persistence(f) + r)
    return out
