"""Interim in-process store for a lot's accumulating readings and test-date metadata.

Bridges P2.2's incremental-merge logic to P2.6's `project_data`-backed persistence, which
doesn't exist yet - process-lifetime only, not durable, not for production. P2.5 (real
pipeline wiring) and P2.6 (project_data table) replace this with real storage.

`test_date` is stashed here rather than on any frozen contract type, per the
CONTRACT_CHANGES.md gap logged this session (no field for it on Reading/LotDataset/Project).
"""
from dataclasses import dataclass

from contracts import LotDataset


@dataclass
class LotRecord:
    dataset: LotDataset
    test_date: str | None = None


_LOTS: dict[str, LotRecord] = {}


def get(lot_id: str) -> LotRecord | None:
    return _LOTS.get(lot_id)


def put(lot_id: str, dataset: LotDataset, test_date: str | None = None) -> None:
    existing = _LOTS.get(lot_id)
    _LOTS[lot_id] = LotRecord(dataset=dataset, test_date=test_date if test_date is not None else (existing.test_date if existing else None))


def clear() -> None:
    """Test-only: resets the interim store between test runs."""
    _LOTS.clear()
