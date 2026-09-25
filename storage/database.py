"""SQLAlchemy engine + session factory for the six tables in contracts.py Part 5.5.

P2-owned; nobody else touches this file (AGENTS.md rule 2 - call storage's repository
functions instead, never write SQL against these tables directly).
"""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contracts import Account, Base, Project

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./burnin.db")

# SQLite forbids sharing a connection across threads by default; FastAPI's request
# handling doesn't guarantee one thread per session, so this must be relaxed here.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Creates the tables session P2.1 owns: accounts + projects.

    Session P2.6 extends this to the remaining four (project_data, events,
    disposition_signoffs, confirmed_outcomes), once their repository functions land.
    """
    Base.metadata.create_all(bind=engine, tables=[Account.__table__, Project.__table__])
