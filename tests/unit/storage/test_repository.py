"""Session P2.1: accounts/projects tables + save_account/save_project (IMPLEMENTATION_PLAN.md
Part 10, E11 steps 1-3). Each test points at its own temp SQLite file and reloads
storage.database/storage.repository so DATABASE_URL takes effect for that engine.
"""
import importlib

import pytest


@pytest.fixture()
def repository(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    from storage import database

    importlib.reload(database)
    from storage import repository

    importlib.reload(repository)
    repository.init_db()
    return repository


def test_save_account_persists_and_returns_the_row(repository):
    account = repository.save_account(
        account_id="a.sharma", display_name="A. Sharma", role="Quality Engineer", pin_hash="argon2-hash"
    )
    assert account.account_id == "a.sharma"
    assert account.display_name == "A. Sharma"
    assert account.role == "Quality Engineer"
    assert account.pin_hash == "argon2-hash"


def test_save_project_persists_with_generated_created_at(repository):
    repository.save_account(account_id="a.sharma", display_name="A. Sharma", role="QE", pin_hash="h")

    project = repository.save_project(
        project_id="proj-1", lot_id="L1", part_number="PN-100", created_by="a.sharma"
    )
    assert project.project_id == "proj-1"
    assert project.lot_id == "L1"
    assert project.part_number == "PN-100"
    assert project.created_by == "a.sharma"
    assert project.created_at is not None


def test_init_db_is_idempotent(repository):
    # Calling init_db twice (e.g. seed.py re-run) must not raise on existing tables.
    repository.init_db()
