"""Out-of-range input guard (F24 Part 1). Module B's models are calibrated on one scale per parameter (the
generator's canonical units); an input far outside what the calibration saw is not "a bad forecast" but no
forecast at all - `forecast_unavailable=True` with a reason, never a confident verdict from extrapolation.

What is recorded (per part number and parameter, from the calibration's own complete lots, train and
calibration sides together): the range of `value_0h`, of the lot median at 0h, and of the relative
changes (value_24h - value_0h) / value_0h and (value_96h - value_0h) / value_0h. An input is declined when

  - value_0h is not positive, or lies outside [min / LEVEL_MARGIN, max * LEVEL_MARGIN] (log-scale margin);
  - lot_median_0h lies outside [min / LOT_MARGIN, max * LOT_MARGIN] (a whole lot at the wrong scale);
  - a relative change lies outside [lo - REL_MARGIN_SPANS * span, hi + REL_MARGIN_SPANS * span].

Margins: see docs/FIXES_PLAN.md ("Margin choice"). Why not a relative-slope fallback: `safety_slope` is an
absolute drift rate (measured units per hour, compared directly against `drift_rate`), so a scale-
equivariant physics forecast cannot be judged against it - unavailable is the only honest answer.
"""

import math
from dataclasses import dataclass

from contracts import ModuleBInput

LEVEL_MARGIN = 3.0
LOT_MARGIN = 2.0
REL_MARGIN_SPANS = 1.0

Range = tuple[float, float]


@dataclass(frozen=True)
class InputRanges:
    value_0h: Range
    lot_median_0h: Range
    rel_24h: Range
    rel_96h: Range | None  # None when no calibration row had a 96h read


def _range(values: list[float]) -> Range:
    return (min(values), max(values))


def fit_ranges(inputs: list[ModuleBInput]) -> InputRanges | None:
    """None when there is nothing usable to measure (no positive value_0h)."""
    pos = [f for f in inputs if f.value_0h > 0]
    if not pos:
        return None
    rel96 = [(f.value_96h - f.value_0h) / f.value_0h for f in pos if f.value_96h is not None]
    return InputRanges(
        value_0h=_range([f.value_0h for f in pos]),
        lot_median_0h=_range([f.lot_median_0h for f in pos]),
        rel_24h=_range([(f.value_24h - f.value_0h) / f.value_0h for f in pos]),
        rel_96h=_range(rel96) if rel96 else None,
    )


def _log_outside(value: float, rng: Range, margin: float) -> bool:
    return not (rng[0] / margin <= value <= rng[1] * margin)


def _lin_outside(value: float, rng: Range) -> bool:
    w = REL_MARGIN_SPANS * (rng[1] - rng[0])
    return not (rng[0] - w <= value <= rng[1] + w)


def out_of_range_reason(ranges: InputRanges | None, frame: ModuleBInput) -> str | None:
    """None when the input is inside the allowed range (or there is no recorded range to compare with);
    otherwise a one-line reason naming the quantity and the allowed interval."""
    if ranges is None:
        return None
    p = frame.parameter
    if not frame.value_0h > 0:
        return f"{p}: the 0h value ({frame.value_0h:g}) is not positive, so its drift cannot be expressed relative to it"
    lo, hi = ranges.value_0h
    if _log_outside(frame.value_0h, ranges.value_0h, LEVEL_MARGIN):
        return (f"{p}: the 0h value {frame.value_0h:g} is outside the range the forecast model was calibrated on "
                f"({lo / LEVEL_MARGIN:g} to {hi * LEVEL_MARGIN:g}); the units or scale may differ")
    if not frame.lot_median_0h > 0 or _log_outside(frame.lot_median_0h, ranges.lot_median_0h, LOT_MARGIN):
        lo, hi = ranges.lot_median_0h
        return (f"{p}: the lot median {frame.lot_median_0h:g} is outside the range the forecast model was calibrated on "
                f"({lo / LOT_MARGIN:g} to {hi * LOT_MARGIN:g}); the units or scale may differ")
    rel24 = (frame.value_24h - frame.value_0h) / frame.value_0h
    if _lin_outside(rel24, ranges.rel_24h):
        return f"{p}: the 0h-to-24h relative change {rel24:+.3g} is outside the range the forecast model was calibrated on"
    if frame.value_96h is not None and ranges.rel_96h is not None:
        rel96 = (frame.value_96h - frame.value_0h) / frame.value_0h
        if _lin_outside(rel96, ranges.rel_96h):
            return f"{p}: the 0h-to-96h relative change {rel96:+.3g} is outside the range the forecast model was calibrated on"
    return None
