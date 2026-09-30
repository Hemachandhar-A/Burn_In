"""SQLAlchemy engine + session factory for the six tables in contracts.py Part 5.5.

P2-owned; nobody else touches this file (AGENTS.md rule 2 - call storage's repository
functions instead, never write SQL against these tables directly).
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contracts import (
    Account,
    Base,
    ConfirmedOutcome,
    DispositionSignoff,
    Event,
    Project,
    ProjectData,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./burnin.db")

# SQLite forbids sharing a connection across threads by default; FastAPI's request
# handling doesn't guarantee one thread per session, so this must be relaxed here.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

_ALL_TABLES = [
    Account.__table__,
    Project.__table__,
    ProjectData.__table__,
    Event.__table__,
    DispositionSignoff.__table__,
    ConfirmedOutcome.__table__,
]


# Columns added to an existing table after its first release: (table, column, SQL type). create_all never
# alters a table that already exists, so an old database file needs these added explicitly.
_ADDED_COLUMNS = [
    (Project.__tablename__, "manufacturer", "VARCHAR"),
    (Project.__tablename__, "date_code", "VARCHAR"),
]


def _add_missing_columns() -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        for table, column, sql_type in _ADDED_COLUMNS:
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")


def init_db() -> None:
    """Creates all six tables in contracts.py Part 5.5, then adds any nullable column an older database
    file lacks (idempotent: a second call adds nothing)."""
    Base.metadata.create_all(bind=engine, tables=_ALL_TABLES)
    _add_missing_columns()
