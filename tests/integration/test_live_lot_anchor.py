"""F24 regression anchor: LIVE-01 uploaded as the three demo files (POST /lots, then two POST checkpoints) ends
COMPLETE, REJECT, PDA 0.0649, 13 flagged - the numbers the live demo shows."""
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DEMO = Path(__file__).resolve().parent.parent.parent / "demo_data"


@pytest.fixture
def db(tmp_path, monkeypatch):
    from ingestion import store
    from storage import database, repository

    engine = create_engine(f"sqlite:///{tmp_path / 'live.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    monkeypatch.setattr(repository, "SessionLocal", session_local)
    repository.init_db()
    store.clear()
    repository.save_account("a.sharma", "A. Sharma", "Quality Engineer", PasswordHasher().hash("1234"))
    yield
    store.clear()


def test_live_lot_three_uploads_anchor(db):
    from fastapi.testclient import TestClient

    from api.main import app

    client = TestClient(app)
    token = client.post("/auth/login", json={"account_id": "a.sharma", "pin": "1234"}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    def csv(name):
        return {"file": (name, (DEMO / name).read_bytes(), "text/csv")}

    up = client.post("/lots", headers=h, files=csv("live_0h_24h.csv"),
                     data={"lot_id": "LIVE-01", "part_number": "DEMO-PN", "manufacturer": "Northvale Semiconductor",
                           "date_code": "2603", "account_id": "a.sharma"})
    assert up.status_code == 200
    assert client.get("/lots/LIVE-01", headers=h).json()["disposition"]["verdict"] in ("LOT_AT_RISK", "STOP_RUN_RECOMMENDED")
    for name in ("live_96h.csv", "live_168h.csv"):
        assert client.post("/lots/LIVE-01/checkpoints", headers=h, files=csv(name), data={"account_id": "a.sharma"}).status_code == 200
    lot = client.get("/lots/LIVE-01", headers=h).json()
    d = lot["disposition"]
    assert d["status"] == "COMPLETE" and d["verdict"] == "REJECT" and d["pda_result"] == pytest.approx(0.0649, abs=5e-5)
    assert sum(a["verdict"] != "PASS" for a in lot["assessments"]) == 13
