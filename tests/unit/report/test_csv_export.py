"""E9 step 4: attach the raw CSV as the underlying electronic data record. Long format,
one row per `Reading`, field names verbatim - the layout CONTRACT_CHANGES.md ("Wide-format
CSV: P1's proposed layout adopted...") already pinned for the long side.
"""
import csv
import io

from contracts import LotDataset, Reading
from report import csv_export


def _lot():
    readings = [
        Reading(component_id="C0", lot_id="L1", part_number="PN-100", manufacturer="Acme",
                date_code="2450", parameter="iddq", checkpoint_hour=0.0, value=10.0, unit="uA"),
        Reading(component_id="C0", lot_id="L1", part_number="PN-100", manufacturer="Acme",
                date_code="2450", parameter="iddq", checkpoint_hour=24.0, value=12.0, unit="uA"),
    ]
    return LotDataset(lot_id="L1", part_number="PN-100", status="IN_PROGRESS", readings=readings, account_id="a.sharma")


def test_render_csv_one_row_per_reading():
    text = csv_export.render_csv(_lot().model_dump(mode="json"))
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 2
    assert rows[0]["component_id"] == "C0"
    assert rows[0]["checkpoint_hour"] == "0.0"
    assert set(rows[0].keys()) == set(Reading.model_fields.keys())


def test_render_csv_empty_lot_has_header_only():
    empty = LotDataset(lot_id="L1", part_number="PN-100", status="IN_PROGRESS", readings=[], account_id="a.sharma")
    text = csv_export.render_csv(empty.model_dump(mode="json"))
    rows = list(csv.DictReader(io.StringIO(text)))
    assert rows == []
