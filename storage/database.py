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


def init_db() -> None:
    """Creates all six tables in contracts.py Part 5.5."""
    Base.metadata.create_all(bind=engine, tables=_ALL_TABLES)
