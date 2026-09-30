"""Tied timestamps: the later-inserted sign-off (last in the ascending list) is the latest."""
from datetime import UTC, datetime
from types import SimpleNamespace

from fusion import router

_T = datetime(2026, 8, 1, tzinfo=UTC)


def test_staleness_uses_last_inserted_signoff_on_tied_timestamps(monkeypatch):
    signoffs = [
        SimpleNamespace(analysis_run_id="run-1", timestamp=_T),
        SimpleNamespace(analysis_run_id="run-2", timestamp=_T),  # inserted later
    ]
    rows = [SimpleNamespace(analysis_run_id=f"run-{i}") for i in (1, 2, 3)]
    monkeypatch.setattr(router, "query_disposition_signoffs", lambda **kw: signoffs)
    monkeypatch.setattr(router, "query_project_data", lambda pid: rows)
    latest_row = SimpleNamespace(analysis_run_id="run-3",
                                 diff_vs_prior={"verdict_changes": {"C1": {"from": "PASS", "to": "REJECT"}}})
    # signed against run-2 (second latest) -> stale note naming the change; against run-1 it would be None
    note = router._staleness_note_for("p1", "C1", latest_row)
    assert note is not None and "PASS to REJECT" in note
