"""E3 step 1 (session P4.1): the three physics baselines any deployed Module B model must beat -
persistence, linear extrapolation, and power-law extrapolation fit from the current lot's healthy parts.

Every baseline reads only a `ModuleBInput` (168h is absent by construction - AGENTS.md rule 6) and uses
the actual elapsed hours of each reading, not an assumed 0/24/96 (irregular checkpoints, context.md 5.9).
"Latest reading" means 96h when present, else 24h.

Power law (context.md 1.4): NBTI-style drift grows as delta(t) = A * t^n, so a part's 168h value is
extrapolated from its own latest drift as v0 + delta_last * ((168 - t0) / (t_last - t0))^n. The exponent n
is fit per (lot, parameter) from the lot's healthy parts - the ratio of their median drift at 96h to their
median drift at 24h - rather than per part, because a single part's two-point ratio is dominated by
measurement noise at these drift magnitudes.
"""

import math
from dataclasses import dataclass

import numpy as np

from contracts import ModuleBInput

TARGET_HOURS = 168.0

# Disclosed default, used only when the lot itself cannot identify n: no 96h readings yet (a 24h-only
# In-Progress lot has two points per part, which fixes A but not n), or healthy drift with no consistent
# direction. n ~ 0.25 is the commonly used NBTI value (context.md 1.4, OptGM), inside the measured
# 0.15-0.30 spread (LJMU Fig. 1a) - a literature prior, not a fit to this lot.
DEFAULT_POWER_LAW_EXPONENT = 0.25

# n is clipped to [0, 1]: n > 1 would extrapolate faster than a straight line, which no cited aging
# mechanism supports, and n < 0 would predict drift shrinking back over time. A fitted value outside this
# range means the lot's median drift is noise-dominated, not that the physics changed.
EXPONENT_RANGE = (0.0, 1.0)

# "Healthy" for the exponent fit = inside the lot's robust core at every checkpoint the part has. 3.5 is
# the standard robust-z outlier cutoff (Iglewicz & Hoaglin); a judgment call, disclosed as one.
HEALTHY_ROBUST_Z_MAX = 3.5


@dataclass(frozen=True)
class BaselinePredictions:
    persistence: float
    linear: float
    power_law: float
    power_law_exponent: float  # the lot's fitted n (or the disclosed default) used for power_law


def _latest(frame: ModuleBInput) -> tuple[float, float]:
    """(elapsed hours, value) of the latest reading - 96h when present, else 24h."""
    if frame.value_96h is not None:
        return frame.elapsed_hours["96h"], frame.value_96h
    return frame.elapsed_hours["24h"], frame.value_24h


def _horizon_ratio(frame: ModuleBInput) -> float:
    """(168 - t0) / (t_last - t0): how far past the latest reading 168h is, in units of elapsed time."""
    t0 = frame.elapsed_hours["0h"]
    t_last, _ = _latest(frame)
    return (TARGET_HOURS - t0) / (t_last - t0)


def persistence(frame: ModuleBInput) -> float:
    """168h = the latest reading (E3's "168h = 24h" when no 96h exists)."""
    return _latest(frame)[1]


def linear(frame: ModuleBInput) -> float:
    """Straight line from the 0h reading through the latest reading, extended to 168h."""
    _, v_last = _latest(frame)
    return frame.value_0h + (v_last - frame.value_0h) * _horizon_ratio(frame)


def power_law(frame: ModuleBInput, exponent: float) -> float:
    """v0 + delta_last * ratio^n. With n = 1 this is exactly `linear`."""
    _, v_last = _latest(frame)
    return frame.value_0h + (v_last - frame.value_0h) * _horizon_ratio(frame) ** exponent


def _is_healthy(frame: ModuleBInput) -> bool:
    return all(abs(z) <= HEALTHY_ROBUST_Z_MAX for z in frame.robust_z.values())


def fit_lot_exponent(frames: list[ModuleBInput]) -> float:
    """Fits n from one lot's healthy parts for one parameter:
    n = log(median delta_96h / median delta_24h) / log(median t96 elapsed / median t24 elapsed),
    with elapsed measured from each part's own 0h read. Falls back to DEFAULT_POWER_LAW_EXPONENT when the
    lot has no 96h readings or its median drift has no consistent nonzero direction."""
    if not frames:
        return DEFAULT_POWER_LAW_EXPONENT
    if len({(f.lot_id, f.parameter) for f in frames}) > 1:
        raise ValueError("fit_lot_exponent takes frames from exactly one (lot_id, parameter)")

    usable = [f for f in frames if f.value_96h is not None and _is_healthy(f)]
    if not usable:
        return DEFAULT_POWER_LAW_EXPONENT

    d24 = float(np.median([f.value_24h - f.value_0h for f in usable]))
    d96 = float(np.median([f.value_96h - f.value_0h for f in usable]))
    t24 = float(np.median([f.elapsed_hours["24h"] - f.elapsed_hours["0h"] for f in usable]))
    t96 = float(np.median([f.elapsed_hours["96h"] - f.elapsed_hours["0h"] for f in usable]))
    if d24 == 0.0 or d96 == 0.0 or (d24 > 0) != (d96 > 0) or t96 <= t24:
        return DEFAULT_POWER_LAW_EXPONENT

    n = math.log(d96 / d24) / math.log(t96 / t24)
    return float(min(max(n, EXPONENT_RANGE[0]), EXPONENT_RANGE[1]))


def physics_baselines(frames: list[ModuleBInput]) -> dict[tuple[str, str], BaselinePredictions]:
    """All three baselines for every frame, keyed (component_id, parameter). The power-law exponent is fit
    once per (lot_id, parameter) group, so a mixed batch of lots/parameters is handled correctly."""
    groups: dict[tuple[str, str], list[ModuleBInput]] = {}
    for f in frames:
        groups.setdefault((f.lot_id, f.parameter), []).append(f)

    out: dict[tuple[str, str], BaselinePredictions] = {}
    for group in groups.values():
        n = fit_lot_exponent(group)
        for f in group:
            out[(f.component_id, f.parameter)] = BaselinePredictions(
                persistence=persistence(f),
                linear=linear(f),
                power_law=power_law(f, n),
                power_law_exponent=n,
            )
    return out
