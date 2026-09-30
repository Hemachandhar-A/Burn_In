"""Tied event timestamps: the later-inserted trigger event names the run's trigger."""
from datetime import UTC, datetime
from types import SimpleNamespace

from report.data import _trigger_for_run

_T = datetime(2026, 8, 1, tzinfo=UTC)


def test_tied_trigger_events_later_insert_wins():
    events = [SimpleNamespace(event_type="ingest", timestamp=_T),
              SimpleNamespace(event_type="checkpoint_add", timestamp=_T)]
    assert _trigger_for_run(events, _T) == "checkpoint_add"
