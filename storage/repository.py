"""P2's repository API (contracts.py Part 5.5) - the only place that writes SQL against
these tables; every other stage calls these functions instead (AGENTS.md rule 2).

Session P2.1 scope: `save_account` and `save_project` only, per IMPLEMENTATION_PLAN.md
Part 10. `save_analysis_run`, `save_disposition_signoff`, `save_confirmed_outcome`,
`log_event` (and every function's `query_*` counterpart) land in session P2.6.
"""
from datetime import UTC, datetime

from contracts import Account, Project
from storage.database import SessionLocal, init_db  # noqa: F401 - re-exported for scripts/seed.py


def save_account(account_id: str, display_name: str, role: str, pin_hash: str) -> Account:
    with SessionLocal() as session:
        account = Account(account_id=account_id, display_name=display_name, role=role, pin_hash=pin_hash)
        session.add(account)
        session.commit()
        return account


def save_project(project_id: str, lot_id: str, part_number: str, created_by: str) -> Project:
    with SessionLocal() as session:
        project = Project(
            project_id=project_id,
            lot_id=lot_id,
            part_number=part_number,
            created_at=datetime.now(UTC),
            created_by=created_by,
        )
        session.add(project)
        session.commit()
        return project
