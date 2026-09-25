"""E9 step 5: "Export the same structured content as JSON alongside the PDF/CSV - this
JSON is the same object stored as `project_data` (E11) for reload, not a separately
maintained copy." Built by serializing `report.data.ReportData` (which is itself already
read straight from stored `project_data`/`disposition_signoffs`/`events` plus a local
recompute of the delta table) - not a second, independently maintained structure.
"""
import dataclasses
from datetime import date, datetime
from typing import Any

from report.data import ReportData


def _jsonable(value: Any) -> Any:
    """`dataclasses.asdict` already flattens every nested dataclass to a plain dict/list -
    the only non-JSON-native type left in a `ReportData` tree is `datetime`."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def to_json_dict(report: ReportData) -> dict:
    return _jsonable(dataclasses.asdict(report))
