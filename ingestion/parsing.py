"""E7 steps 1, 5: CSV upload parsing and schema validation with visible, specific errors.

Long format only for now (one row per Reading: component_id, parameter, checkpoint_hour,
value, unit) - lot-level metadata (lot_id, part_number, manufacturer, date_code) comes from
the surrounding upload form, not repeated per row. No wide CSV layout has been pinned yet
between the generator and ingestion (CONTRACT_CHANGES.md, still OPEN); wide/long format
equivalence is P2.3's scope once that's resolved.
"""
import csv
import io

from contracts import Reading

REQUIRED_COLUMNS = ("component_id", "parameter", "checkpoint_hour", "value", "unit")

# Case/whitespace/separator-insensitive aliases for the required columns (E7 step 5's "fuzzy
# column-name matching"). A header that normalizes to none of these is reported by name so
# the uploader can fix their file - never silently dropped or guessed at.
_ALIASES = {
    "componentid": "component_id", "partid": "component_id",
    "parameter": "parameter", "param": "parameter",
    "checkpointhour": "checkpoint_hour", "hour": "checkpoint_hour", "elapsedhours": "checkpoint_hour",
    "value": "value", "reading": "value",
    "unit": "unit", "units": "unit",
}


class IngestionValidationError(ValueError):
    """Carries every problem found, not just the first - E7 step 5's "visible, specific
    error messages", not one opaque failure."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _normalize(header: str) -> str:
    return header.strip().lower().replace(" ", "").replace("-", "").replace("_", "")


def _resolve_columns(fieldnames: list[str]) -> dict[str, str]:
    """Maps each required canonical field to the actual CSV header supplying it, raising a
    specific error for any field with zero or more-than-one matching header."""
    matches: dict[str, list[str]] = {}
    for header in fieldnames:
        canonical = _ALIASES.get(_normalize(header))
        if canonical is not None:
            matches.setdefault(canonical, []).append(header)

    errors: list[str] = []
    resolved: dict[str, str] = {}
    for field in REQUIRED_COLUMNS:
        candidates = matches.get(field, [])
        if not candidates:
            errors.append(f"missing required column for '{field}' (no header matched a known name)")
        elif len(candidates) > 1:
            errors.append(
                f"ambiguous column for '{field}': headers {candidates!r} all match - "
                "rename all but one before re-uploading"
            )
        else:
            resolved[field] = candidates[0]
    if errors:
        raise IngestionValidationError(errors)
    return resolved


def parse_lot_csv(
    raw_csv: bytes, *, lot_id: str, part_number: str, manufacturer: str, date_code: str
) -> list[Reading]:
    """Parses a long-format CSV into validated `Reading` objects, stamping every row with the
    lot-level metadata supplied by the upload form. Raises `IngestionValidationError` with
    every problem found, not just the first."""
    text = raw_csv.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise IngestionValidationError(["file is empty or has no header row"])
    columns = _resolve_columns(list(reader.fieldnames))

    errors: list[str] = []
    readings: list[Reading] = []
    seen: set[tuple[str, str, float]] = set()
    for line_no, row in enumerate(reader, start=2):  # header is line 1
        component_id = (row[columns["component_id"]] or "").strip()
        parameter = (row[columns["parameter"]] or "").strip()
        unit = (row[columns["unit"]] or "").strip()
        if not component_id:
            errors.append(f"line {line_no}: component_id is empty")
            continue
        if not parameter:
            errors.append(f"line {line_no}: parameter is empty")
            continue

        raw_hour = row[columns["checkpoint_hour"]]
        try:
            checkpoint_hour = float(raw_hour)
        except (TypeError, ValueError):
            errors.append(f"line {line_no}: checkpoint_hour {raw_hour!r} is not a number")
            continue

        raw_value = row[columns["value"]]
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            errors.append(f"line {line_no}: value {raw_value!r} is not a number")
            continue

        key = (component_id, parameter, checkpoint_hour)
        if key in seen:
            errors.append(
                f"line {line_no}: duplicate reading for component '{component_id}', "
                f"parameter '{parameter}' at checkpoint {checkpoint_hour}h"
            )
            continue
        seen.add(key)
        readings.append(
            Reading(
                component_id=component_id, lot_id=lot_id, part_number=part_number,
                manufacturer=manufacturer, date_code=date_code, parameter=parameter,
                checkpoint_hour=checkpoint_hour, value=value, unit=unit,
            )
        )

    if errors:
        raise IngestionValidationError(errors)
    if not readings:
        raise IngestionValidationError(["file contains no data rows"])
    return readings
