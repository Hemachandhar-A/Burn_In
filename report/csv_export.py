"""E9 step 4: the raw CSV attached alongside the PDF - the underlying electronic data
record, one row per `Reading`, field names verbatim (long format, per CONTRACT_CHANGES.md
2026-09-25 "Wide-format CSV: P1's proposed layout adopted...", which pinned the long side
as "one row per `Reading` using its field names verbatim").
"""
import csv
import io

from contracts import Reading

_FIELDNAMES = list(Reading.model_fields.keys())


def render_csv(raw_data: dict) -> str:
    """`raw_data` is `LotDataset.model_dump(mode="json")` (report/data.py's pinned shape)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_FIELDNAMES)
    writer.writeheader()
    for reading in raw_data.get("readings", []):
        writer.writerow({k: reading[k] for k in _FIELDNAMES})
    return buffer.getvalue()
