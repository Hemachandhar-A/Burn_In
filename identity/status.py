"""F24 Part 2 (E10): the per-part disposition status, derived from stored sign-offs - never stored itself, so
the history stays an immutable record of decisions and the status can only follow it. The rule is the Lead's
ruling in docs/FIXES_PLAN.md: the LATEST decision per account counts."""

from typing import Literal, Sequence

from storage.repository import query_disposition_signoffs

DispositionStatus = Literal[
    "NONE", "ACCEPT_RECORDED", "HOLD_RECORDED", "REJECT_PENDING_SECOND", "REJECT_FINAL", "CONFLICT"
]


def derive_status(decisions: Sequence[tuple[str, str]]) -> DispositionStatus:
    """`decisions`: (account_id, verdict) in the order they were made (oldest first)."""
    latest: dict[str, str] = {}
    for account_id, verdict in decisions:
        latest[account_id] = verdict
    if not latest:
        return "NONE"
    if sum(v == "REJECT" for v in latest.values()) >= 2:
        return "REJECT_FINAL"
    verdicts = set(latest.values())
    if len(verdicts) > 1:
        return "CONFLICT"
    only = next(iter(verdicts))
    return {"ACCEPT": "ACCEPT_RECORDED", "HOLD": "HOLD_RECORDED", "REJECT": "REJECT_PENDING_SECOND"}[only]


def disposition_status_for(project_id: str, component_id: str, analysis_run_id: str) -> DispositionStatus:
    """Status of one part within one analysis run, from its stored sign-offs (query order is chronological)."""
    signoffs = query_disposition_signoffs(project_id=project_id, component_id=component_id)
    return derive_status([(s.account_id, s.verdict) for s in signoffs if s.analysis_run_id == analysis_run_id])
