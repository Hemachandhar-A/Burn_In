"""Block 4d Part 3: lot metadata (manufacturer, date_code, test_date) is persisted on the project row and
exposed by GET /projects/{id}; init_db() upgrades a database created with the old schema."""
import csv
import io
import sqlite3
from datetime import UTC, datetime

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from harness.golden import GOLDEN_LOT_ID, golden_lot


def _isolate(monkeypatch, db_path):
    from storage import database, repository

    engine = create_engine(f"sqlite:///{db_path}")
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    monkeypatch.setattr(repository, "SessionLocal", session_local)
    return repository


def _csv_bytes(readings) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["component_id", "parameter", "checkpoint_hour", "value", "unit"])
    for r in readings:
        w.writerow([r.component_id, r.parameter, r.checkpoint_hour, r.value, r.unit])
    return buf.getvalue().encode()


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    from ingestion import store

    repository = _isolate(monkeypatch, tmp_path / "meta.db")
    repository.init_db()
    store.clear()
    repository.save_account("a.sharma", "A. Sharma", "Quality Engineer", PasswordHasher().hash("1234"))
    from api.main import app

    client = TestClient(app)
    token = client.post("/auth/login", json={"account_id": "a.sharma", "pin": "1234"}).json()["access_token"]
    yield client, {"Authorization": f"Bearer {token}"}, repository
    store.clear()


def test_upload_persists_and_exposes_manufacturer_date_code_test_date(app_client):
    client, headers, _ = app_client
    meta = {"lot_id": GOLDEN_LOT_ID, "part_number": "PN-GOLDEN", "manufacturer": "ACME-SEMI",
            "date_code": "2603", "account_id": "a.sharma", "test_date": "2026-03-14"}
    r = client.post("/lots", files={"file": ("lot.csv", _csv_bytes(golden_lot().readings), "text/csv")},
                    data=meta, headers=headers)
    assert r.status_code == 200, r.text
    body = client.get(f"/projects/{GOLDEN_LOT_ID}", headers=headers).json()
    assert body["manufacturer"] == "ACME-SEMI"
    assert body["date_code"] == "2603"
    assert body["test_date"].startswith("2026-03-14")
    listed = {p["project_id"]: p for p in client.get("/projects", headers=headers).json()}
    assert listed[GOLDEN_LOT_ID]["manufacturer"] == "ACME-SEMI"


def test_demo_lot_project_carries_generated_metadata(app_client):
    client, headers, _ = app_client
    lot_id = client.post("/lots/demo", data={"account_id": "a.sharma"}, headers=headers).json()["lot_id"]
    body = client.get(f"/projects/{lot_id}", headers=headers).json()
    assert body["manufacturer"] and body["date_code"] and body["test_date"]


def test_project_saved_without_metadata_returns_none(app_client):
    client, headers, repository = app_client
    repository.save_project("bare", "bare", "PN-1", datetime(2026, 1, 2, tzinfo=UTC), "a.sharma")
    body = client.get("/projects/bare", headers=headers).json()
    assert body["manufacturer"] is None and body["date_code"] is None
    assert body["test_date"].startswith("2026-01-02")


def test_init_db_upgrades_old_schema_database(tmp_path, monkeypatch):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE accounts (account_id VARCHAR PRIMARY KEY, display_name VARCHAR NOT NULL,
                               role VARCHAR NOT NULL, pin_hash VARCHAR NOT NULL);
        CREATE TABLE projects (project_id VARCHAR PRIMARY KEY, lot_id VARCHAR NOT NULL,
                               part_number VARCHAR NOT NULL, test_date DATETIME NOT NULL,
                               created_at DATETIME NOT NULL, created_by VARCHAR NOT NULL);
        INSERT INTO accounts VALUES ('a.sharma', 'A. Sharma', 'QE', 'h');
        INSERT INTO projects VALUES ('old-1', 'LOT-OLD', 'PN-OLD', '2025-05-05 00:00:00.000000',
                                     '2025-05-06 00:00:00.000000', 'a.sharma');
    """)
    con.commit()
    con.close()

    repository = _isolate(monkeypatch, db)
    repository.init_db()
    repository.init_db()  # idempotent: a second run adds nothing and does not fail

    cols = {row[1] for row in sqlite3.connect(db).execute("PRAGMA table_info(projects)")}
    assert {"manufacturer", "date_code"} <= cols
    old = repository.query_project("old-1")
    assert old.lot_id == "LOT-OLD" and old.part_number == "PN-OLD"
    assert old.manufacturer is None and old.date_code is None
    assert old.test_date.year == 2025
    repository.save_project("new-1", "LOT-NEW", "PN-NEW", datetime(2026, 1, 1, tzinfo=UTC), "a.sharma",
                            manufacturer="M", date_code="2601")
    assert repository.query_project("new-1").manufacturer == "M"
    assert len(repository.query_projects()) == 2
