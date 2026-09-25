"""E7 step 7: data-quality checks - missing values, out-of-datasheet-range flags, duplicate
part IDs. Runs after parsing/merge, over an assembled set of `Reading`s - these are flags for
visibility (Part 7.3's checklist), not hard rejections the way `IngestionValidationError` is;
a flagged lot still ingests, per E7 step 5's "visible, specific error messages" philosophy
extended to warnings rather than failures.

Missing 0h/24h is the one flag rule 7 (AGENTS.md) treats as load-bearing downstream: a
component/parameter pair without both is `INSUFFICIENT_DATA` for forecasting and must never
be silently imputed. Missing 96h is explicitly allowed, just flagged (E7 "what it is").
"""
from dataclasses import dataclass

from contracts import Reading
from ingestion.checkpoints import label_for_hour


@dataclass(frozen=True)
class QualityFlag:
    component_id: str
    parameter: str
    flag_type: str  # "INSUFFICIENT_DATA" | "MISSING_96H" | "OUT_OF_RANGE" | "DUPLICATE_CHECKPOINT"
    message: str


def check_missing_checkpoints(readings: list[Reading]) -> list[QualityFlag]:
    """Per (component_id, parameter): flags `INSUFFICIENT_DATA` if 0h or 24h is absent (no
    downstream module may guess a value for either, AGENTS.md rule 7); flags `MISSING_96H`
    if 0h and 24h are both present but 96h isn't - allowed, not blocking."""
    labels_seen: dict[tuple[str, str], set[str]] = {}
    for reading in readings:
        label = label_for_hour(reading.checkpoint_hour)
        if label is None:
            continue
        labels_seen.setdefault((reading.component_id, reading.parameter), set()).add(label)

    flags: list[QualityFlag] = []
    for (component_id, parameter), labels in labels_seen.items():
        missing_required = {"0h", "24h"} - labels
        if missing_required:
            flags.append(QualityFlag(
                component_id, parameter, "INSUFFICIENT_DATA",
                f"missing required checkpoint(s) {sorted(missing_required)} - forecast_unavailable, not guessed",
            ))
        elif "96h" not in labels:
            flags.append(QualityFlag(
                component_id, parameter, "MISSING_96H",
                "96h reading not present - allowed, forecast proceeds on 0h/24h only",
            ))
    return flags


def check_out_of_range(readings: list[Reading], limits: dict[str, tuple[float, float]] | None) -> list[QualityFlag]:
    """Flags a reading whose value falls outside `limits[parameter] = (min, max)` - the
    datasheet range for that parameter. `limits` is caller-supplied (no fixed datasheet-limit
    table exists in `contracts.py`; per-parameter units are already form-driven the same way,
    E7 step 1) - absent entirely, this check is a no-op, not a guess at a threshold."""
    if not limits:
        return []
    flags: list[QualityFlag] = []
    for reading in readings:
        bounds = limits.get(reading.parameter)
        if bounds is None:
            continue
        low, high = bounds
        if not (low <= reading.value <= high):
            flags.append(QualityFlag(
                reading.component_id, reading.parameter, "OUT_OF_RANGE",
                f"value {reading.value} outside datasheet range [{low}, {high}] {reading.unit}",
            ))
    return flags


def check_duplicate_component_ids(readings: list[Reading]) -> list[QualityFlag]:
    """Flags a (component_id, parameter) pair with more than one reading mapped to the same
    nominal checkpoint label but a different `checkpoint_hour` - e.g. 24.0h and 24.3h both
    labeled "24h". `parsing.parse_lot_csv` already hard-rejects an exact-key repeat within one
    file; this catches the subtler case across a merged, multi-file lot history that exact-key
    dedup lets through."""
    seen: dict[tuple[str, str, str], set[float]] = {}
    for reading in readings:
        label = label_for_hour(reading.checkpoint_hour)
        if label is None:
            continue
        key = (reading.component_id, reading.parameter, label)
        seen.setdefault(key, set()).add(reading.checkpoint_hour)

    flags: list[QualityFlag] = []
    for (component_id, parameter, label), hours in seen.items():
        if len(hours) > 1:
            flags.append(QualityFlag(
                component_id, parameter, "DUPLICATE_CHECKPOINT",
                f"multiple readings ({sorted(hours)}) map to the same {label} checkpoint",
            ))
    return flags


def run_quality_checks(
    readings: list[Reading], *, limits: dict[str, tuple[float, float]] | None = None
) -> list[QualityFlag]:
    """Runs every E7-step-7 check and returns the combined flag list."""
    return [
        *check_missing_checkpoints(readings),
        *check_out_of_range(readings, limits),
        *check_duplicate_component_ids(readings),
    ]
