"""E7 steps 1, 5: CSV upload parsing and schema validation with visible, specific errors.

Long format: one row per Reading (component_id, parameter, checkpoint_hour, value, unit) -
lot-level metadata (lot_id, part_number, manufacturer, date_code) comes from the surrounding
upload form, not repeated per row.

Wide format (P2.3): layout pinned in IMPLEMENTATION_PLAN.md Part 5.2 and essential-features.md
E7 step 1 - `parse_wide_lot_csv` below implements it exactly (one row per (component_id,
checkpoint_hour), a `<parameter>_<unit>` value column per parameter). Both formats parse to
the same `Reading` list for equivalent data - see tests/unit/ingestion/test_parsing.py's
format-equivalence tests.
"""
import csv
import io
import re

from contracts import Reading

# Wide CSV layout (pinned, IMPLEMENTATION_PLAN.md Part 5.2 / essential-features.md E7 step 1):
# fixed columns component_id, checkpoint_hour, then one <parameter>_<unit> value column per
# parameter present (e.g. "iddq_uA").
_WIDE_FIXED_COLUMNS = ("component_id", "checkpoint_hour")
_WIDE_VALUE_COLUMN = re.compile(r"^(?P<parameter>.+)_(?P<unit>[^_]+)$")

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


def parse_wide_lot_csv(
    raw_csv: bytes, *, lot_id: str, part_number: str, manufacturer: str, date_code: str
) -> list[Reading]:
    """Parses a wide-format CSV (pinned layout, see module docstring) into the same
    `Reading` list a long-format upload of equivalent data would produce: one row per
    (component_id, checkpoint_hour), with a `<parameter>_<unit>` value column per parameter
    present (e.g. "iddq_uA"). A row's blank cell for a given parameter column means that
    component/checkpoint has no reading for that parameter - skipped, not an error, mirroring
    how real per-checkpoint files don't necessarily cover every parameter every time."""
    text = raw_csv.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise IngestionValidationError(["file is empty or has no header row"])

    value_columns: list[tuple[str, str, str]] = []  # (header, parameter, unit)
    errors: list[str] = []
    for header in reader.fieldnames:
        if _normalize(header) in {"componentid", "partid"} or _normalize(header) in {"checkpointhour", "hour", "elapsedhours"}:
            continue
        match = _WIDE_VALUE_COLUMN.match(header.strip())
        if match is None:
            errors.append(f"column '{header}' doesn't match the wide format's '<parameter>_<unit>' pattern")
            continue
        value_columns.append((header, match.group("parameter"), match.group("unit")))
    if not value_columns and not errors:
        errors.append("no parameter value columns found (expected '<parameter>_<unit>' headers)")

    fixed_columns = _resolve_columns_subset(list(reader.fieldnames), errors)
    if errors:
        raise IngestionValidationError(errors)

    readings: list[Reading] = []
    seen: set[tuple[str, str, float]] = set()
    for line_no, row in enumerate(reader, start=2):
        component_id = (row[fixed_columns["component_id"]] or "").strip()
        if not component_id:
            errors.append(f"line {line_no}: component_id is empty")
            continue
        raw_hour = row[fixed_columns["checkpoint_hour"]]
        try:
            checkpoint_hour = float(raw_hour)
        except (TypeError, ValueError):
            errors.append(f"line {line_no}: checkpoint_hour {raw_hour!r} is not a number")
            continue

        for header, parameter, unit in value_columns:
            raw_value = (row.get(header) or "").strip()
            if raw_value == "":
                continue  # no reading for this parameter at this checkpoint - not an error
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                errors.append(f"line {line_no}: value {raw_value!r} for column '{header}' is not a number")
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


def _resolve_columns_subset(fieldnames: list[str], errors: list[str]) -> dict[str, str]:
    """Like `_resolve_columns`, restricted to the wide format's two fixed columns
    (component_id, checkpoint_hour) - the rest of the header is parameter value columns, not a
    fixed set to fuzzy-match against."""
    matches: dict[str, list[str]] = {}
    for header in fieldnames:
        canonical = _ALIASES.get(_normalize(header))
        if canonical in _WIDE_FIXED_COLUMNS:
            matches.setdefault(canonical, []).append(header)

    resolved: dict[str, str] = {}
    for field in _WIDE_FIXED_COLUMNS:
        candidates = matches.get(field, [])
        if not candidates:
            errors.append(f"missing required column for '{field}' (no header matched a known name)")
        elif len(candidates) > 1:
            errors.append(f"ambiguous column for '{field}': headers {candidates!r} all match")
        else:
            resolved[field] = candidates[0]
    return resolved
