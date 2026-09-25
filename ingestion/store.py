"""Interim in-process store for a lot's accumulating readings, test-date metadata, and
ingestion attribution.

Bridges P2.2's incremental-merge logic to P2.6's `project_data`/`events`-backed persistence,
which doesn't exist yet - process-lifetime only, not durable, not for production. P2.5 (real
pipeline wiring) and P2.6 (project_data + events tables) replace this with real storage.

`test_date` is stashed here rather than on any frozen contract type, per the
CONTRACT_CHANGES.md gap logged in P2.2 (no field for it on Reading/LotDataset/Project).

`events` is this session's (P2.3, E7 step 11) interim stand-in for the real `events` table
(context.md 5.10: event_type `ingest`/`checkpoint_add`, account_id, timestamp) - every ingest
or checkpoint-add call appends one, so attribution survives a checkpoint upload and isn't only
visible on the lot's *original* `account_id`.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from contracts import LotDataset


@dataclass(frozen=True)
class IngestionEvent:
    event_type: str  # "ingest" | "checkpoint_add"
    account_id: str
    timestamp: datetime


@dataclass
class LotRecord:
    dataset: LotDataset
    test_date: str | None = None
    events: list[IngestionEvent] = field(default_factory=list)


_LOTS: dict[str, LotRecord] = {}


def get(lot_id: str) -> LotRecord | None:
    return _LOTS.get(lot_id)


def put(
    lot_id: str,
    dataset: LotDataset,
    test_date: str | None = None,
    *,
    event_type: str | None = None,
    account_id: str | None = None,
) -> None:
    existing = _LOTS.get(lot_id)
    events = list(existing.events) if existing else []
    if event_type is not None and account_id is not None:
        events.append(IngestionEvent(event_type=event_type, account_id=account_id, timestamp=datetime.now(timezone.utc)))
    _LOTS[lot_id] = LotRecord(
        dataset=dataset,
        test_date=test_date if test_date is not None else (existing.test_date if existing else None),
        events=events,
    )


def clear() -> None:
    """Test-only: resets the interim store between test runs."""
    _LOTS.clear()
