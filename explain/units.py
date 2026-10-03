"""F24 Part 3: the one Python helper that turns a canonical-unit value into a readable one with an automatic SI
prefix - 10000 nA is shown as "10 uA". Used by the explanation sentences (explain/text.py) and the PDF
(report/pdf.py); the frontend has its own twin (frontend/src/format/units.ts) with the same rule and the same
tests, because the two sides never share code.

Only the two unit families ingestion normalises (current and time, ingestion/units.py) get a prefix change; any
other unit is shown exactly as given. Labels stay ASCII ("uA", not the micro sign) so a CSV, a PDF and a sentence
spell a unit the same way. `scale_for_display` also returns `factor` with `display_value * factor == value`, so
the canonical value can always be recovered from what is shown.
"""
import math

from ingestion.units import _CURRENT_UNITS, _TIME_UNITS

# (label, power of ten relative to the family's base unit), largest first; the labels are what a person reads.
# Integer exponents, not 1e-9-style floats: 1e-6 / 1e-9 is 999.9999999999999, and a displayed 45 must not be 45.00000000000001.
_CURRENT_LABELS = (("A", 0), ("mA", -3), ("uA", -6), ("nA", -9), ("pA", -12))
_TIME_LABELS = (("s", 0), ("ms", -3), ("us", -6), ("ns", -9), ("ps", -12))
_FAMILIES = ((_CURRENT_UNITS, _CURRENT_LABELS), (_TIME_UNITS, _TIME_LABELS))


def scale_for_display(value: float, unit: str | None) -> tuple[float, str, float]:
    """(display_value, display_unit, factor) with display_value * factor == value. The prefix is the largest unit
    in the family that leaves |display_value| >= 1 (the smallest unit when the value is tinier than all of them).
    Zero, a non-finite value, a missing unit or an unrecognised unit is returned unchanged with factor 1."""
    if unit is None or not unit.strip() or not math.isfinite(value) or value == 0:
        return value, (unit or "").strip(), 1.0
    key = unit.strip().lower()
    for table, labels in _FAMILIES:
        if key in table:
            own = next(e for lb, e in labels if lb.lower() == key)
            base = abs(value) * 10.0**own
            label, exp = next(((lb, e) for lb, e in labels if base >= 10.0**e * (1 - 1e-12)), labels[-1])
            factor = 10.0 ** (exp - own)
            return value / factor, label, factor
    return value, unit.strip(), 1.0


def format_quantity(value: float, unit: str | None, significant: int = 4) -> str:
    """"10 uA" for (10000, "nA"); the bare number when there is no unit."""
    shown, label, _ = scale_for_display(value, unit)
    text = f"{shown:.{significant}g}"
    return f"{text} {label}" if label else text
