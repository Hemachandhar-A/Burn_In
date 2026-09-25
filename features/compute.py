"""E8 steps 1-5 (session P2.4): deltas, lot-relative robust stats (median, IQR/1.35), the
<30-part small-lot fallback, per-part robust z-scores, and the joint MCD feature vector - real
logic replacing the P2.1 stub's fixed placeholder values.

Module B's own input vector (`[value_0h, value_24h, value_96h, lot_median_0h, lot_median_24h,
elapsed_hours]`, context.md 5.9) needs no separate assembly here - `FeatureFrame` already carries
every one of those fields directly, so E8 step 5's Module B half is satisfied by the contract
shape alone.

168h is intentionally excluded (CONTRACT_CHANGES.md, resolved): `FeatureFrame`/Module A never
score the 168h reading, so `compute()` never looks past 96h.

Pooled cross-lot fallback (E8 step 3): no storage query function exists yet to fetch another
lot's readings for the same part_number (that's P2.6/P2.8's repository surface) - see
CONTRACT_CHANGES.md 2026-09-25 P2 "Lead - FeatureFrame reshaped". Until then, `compute()` accepts
an optional `pooled_reference` argument the caller can supply once that query exists; absent one,
a small lot falls back to its own lot-relative stats as the best available substitute, still
flagged via `used_pooled_fallback` - never a silent, unflagged pass-through.
"""
import numpy as np

from contracts import FeatureFrame, LotDataset, Reading
from ingestion.checkpoints import label_for_hour

_ALL_LABELS = ("0h", "24h", "96h")
_NOMINAL_HOURS = {"0h": 0.0, "24h": 24.0, "96h": 96.0}
_SMALL_LOT_THRESHOLD = 30  # AEC-Q001's own "at least 30 parts" - context.md 1.6, 5.16


def _reading_for_label(readings: list[Reading], label: str) -> Reading | None:
    """Picks the reading closest to the nominal hour when more than one reading maps to the
    same label (irregular checkpoints, re-uploaded/jittered data) -
    `ingestion.quality.check_duplicate_component_ids` already flags this case for visibility;
    this just needs a deterministic tie-break to build one frame."""
    candidates = [r for r in readings if label_for_hour(r.checkpoint_hour) == label]
    if not candidates:
        return None
    nominal = _NOMINAL_HOURS[label]
    return min(candidates, key=lambda r: abs(r.checkpoint_hour - nominal))


def _robust_stats(values: list[float]) -> tuple[float, float]:
    """Lot-relative median and robust sigma (IQR/1.35, context.md Part 4.2) for one parameter
    at one checkpoint. A zero-MAD/zero-IQR population (all-identical values, or n=1) returns
    sigma=0.0 - callers must guard division by zero, not this function."""
    arr = np.asarray(values, dtype=float)
    median = float(np.median(arr))
    q75, q25 = np.percentile(arr, [75, 25])
    sigma = float((q75 - q25) / 1.35)
    return median, sigma


def _robust_z(value: float, median: float, sigma: float) -> float:
    """0.0 when sigma is 0 instead of dividing by zero - in a zero-MAD/single-part population
    every value equals the median by definition, so 0.0 is exact, not a fallback guess."""
    return (value - median) / sigma if sigma > 0 else 0.0


def compute(
    lot: LotDataset,
    pooled_reference: dict[tuple[str, str, str], tuple[float, float]] | None = None,
) -> list[FeatureFrame]:
    """One `FeatureFrame` per (component_id, parameter) pair that has both a 0h and a 24h
    reading. A pair missing either gets no frame at all (AGENTS.md rule 7 - `value_0h`/
    `value_24h` are non-optional on the contract, so there is nothing valid to construct;
    `ingestion.quality.check_missing_checkpoints` already flags this as `INSUFFICIENT_DATA`).

    `pooled_reference`, keyed `(part_number, parameter, checkpoint_label)` -> `(median, sigma)`,
    is the TEMP cross-lot pooling source described in the module docstring - when supplied and
    the lot is small, it replaces the lot-relative median/sigma used for `lot_median_*` and
    `robust_z`.
    """
    by_pair: dict[tuple[str, str], list[Reading]] = {}
    for r in lot.readings:
        by_pair.setdefault((r.component_id, r.parameter), []).append(r)

    picked: dict[tuple[str, str], dict[str, Reading]] = {}
    for (component_id, parameter), readings in by_pair.items():
        by_label = {label: _reading_for_label(readings, label) for label in _ALL_LABELS}
        if by_label["0h"] is None or by_label["24h"] is None:
            continue
        picked[(component_id, parameter)] = {k: v for k, v in by_label.items() if v is not None}

    parameters = sorted({parameter for _, parameter in picked})
    lot_size_by_parameter: dict[str, int] = {}
    stats_by_parameter_label: dict[tuple[str, str], tuple[float, float]] = {}
    for parameter in parameters:
        component_ids = [cid for (cid, p) in picked if p == parameter]
        lot_size_by_parameter[parameter] = len(component_ids)
        for label in _ALL_LABELS:
            values = [
                picked[(cid, parameter)][label].value
                for cid in component_ids
                if label in picked[(cid, parameter)]
            ]
            if values:
                stats_by_parameter_label[(parameter, label)] = _robust_stats(values)

    frames: list[FeatureFrame] = []
    for (component_id, parameter), by_label in picked.items():
        lot_size = lot_size_by_parameter[parameter]
        used_pooled_fallback = lot_size < _SMALL_LOT_THRESHOLD

        elapsed_hours = {label: reading.checkpoint_hour for label, reading in by_label.items()}
        robust_z: dict[str, float] = {}
        median_by_label: dict[str, float] = {}
        for label, reading in by_label.items():
            pooled = pooled_reference.get((lot.part_number, parameter, label)) if pooled_reference else None
            if used_pooled_fallback and pooled is not None:
                median, sigma = pooled
            else:
                median, sigma = stats_by_parameter_label[(parameter, label)]
            median_by_label[label] = median
            robust_z[label] = _robust_z(reading.value, median, sigma)

        value_0h = by_label["0h"].value
        value_24h = by_label["24h"].value
        value_96h = by_label["96h"].value if "96h" in by_label else None

        frames.append(FeatureFrame(
            component_id=component_id,
            lot_id=lot.lot_id,
            part_number=lot.part_number,
            parameter=parameter,
            value_0h=value_0h,
            value_24h=value_24h,
            value_96h=value_96h,
            delta_24h=value_24h - value_0h,
            delta_96h=(value_96h - value_0h) if value_96h is not None else None,
            lot_median_0h=median_by_label["0h"],
            lot_median_24h=median_by_label["24h"],
            robust_z=robust_z,
            lot_size=lot_size,
            used_pooled_fallback=used_pooled_fallback,
            elapsed_hours=elapsed_hours,
        ))

    return frames


def build_mcd_matrix(
    frames: list[FeatureFrame], checkpoint: str
) -> tuple[list[str], list[str], list[list[float]]]:
    """E8 step 5: the joint feature vector for MCD (context.md Part 4.2 - "locked default:
    per-checkpoint MCD", one column per parameter, fit jointly across all three at that
    checkpoint). Only components with a robust-z value for every parameter at `checkpoint` are
    included - MCD needs a rectangular matrix, and a component missing a parameter at this
    checkpoint has nothing principled to fill in (AGENTS.md rule 7).

    Returns `(component_ids, parameters, matrix)`, both sorted for determinism (AGENTS.md rule 9)
    - `matrix[i][j]` is `component_ids[i]`'s robust z-score for `parameters[j]` at `checkpoint`.
    Uses `robust_z`, not raw `value`, so parameters on different scales/units (uA vs ns) don't
    dominate the covariance estimate by unit alone.
    """
    parameters = sorted({f.parameter for f in frames})
    by_component: dict[str, dict[str, float]] = {}
    for frame in frames:
        if checkpoint in frame.robust_z:
            by_component.setdefault(frame.component_id, {})[frame.parameter] = frame.robust_z[checkpoint]

    component_ids = sorted(
        cid for cid, values in by_component.items() if all(p in values for p in parameters)
    )
    matrix = [[by_component[cid][p] for p in parameters] for cid in component_ids]
    return component_ids, parameters, matrix
