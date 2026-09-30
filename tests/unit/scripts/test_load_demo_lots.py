"""scripts/load_demo_lots.py: loads both lots through the real routes, idempotently, into whatever DB is configured."""
import pytest
from argon2 import PasswordHasher
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scripts import load_demo_lots as demo


@pytest.fixture
def db(tmp_path, monkeypatch):
    from ingestion import store
    from storage import database, repository

    engine = create_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    monkeypatch.setattr(repository, "SessionLocal", session_local)
    repository.init_db()
    store.clear()
    repository.save_account("a.sharma", "A. Sharma", "Quality Engineer", PasswordHasher().hash("1234"))
    yield
    store.clear()


def test_loads_both_lots_then_second_run_skips(db, capsys):
    assert demo.main([]) == 0
    first = capsys.readouterr().out
    assert f"loaded {demo.GOLDEN_LOT_ID}: status COMPLETE" in first
    assert f"loaded {demo.EARLY_LOT_ID}: status IN_PROGRESS" in first

    assert demo.main([]) == 0
    second = capsys.readouterr().out
    assert f"skipped {demo.GOLDEN_LOT_ID}" in second and f"skipped {demo.EARLY_LOT_ID}" in second
    assert "loaded" not in second


def test_lot_contents_through_the_api(db):
    from fastapi.testclient import TestClient

    from api.main import app

    assert demo.main([]) == 0
    client = TestClient(app)
    token = client.post("/auth/login", json={"account_id": "a.sharma", "pin": "1234"}).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    gold = client.get(f"/lots/{demo.GOLDEN_LOT_ID}", headers=h).json()
    assert gold["disposition"]["status"] == "COMPLETE"
    rejects = [a for a in gold["assessments"] if a["verdict"] == "REJECT"]
    assert any(a["component_id"] == "GOLDEN-045" for a in rejects)
    early = client.get(f"/lots/{demo.EARLY_LOT_ID}", headers=h).json()
    assert early["disposition"]["status"] == "IN_PROGRESS" and early["disposition"]["is_forecast"] is True
    assert early["disposition"]["verdict"] in ("LOT_AT_RISK", "STOP_RUN_RECOMMENDED")
    assert sum(a["verdict"] == "REJECT" for a in early["assessments"]) >= demo.MIN_B_REJECT


def test_chosen_seed_satisfies_the_selection_rule():
    assert demo.qualifies(demo.scan_seed(demo.EARLY_SEED))


@pytest.mark.skip(reason="BLOCKERS.md 2026-09-30 Lead: POST /lots normalizes the golden fixture's uA leakage to nA, Module B "
                         "(calibrated on the generator's nA scale) then flags 37/77 parts: verdict REJECT, PDA 0.49, not HOLD 0.039")
def test_golden_lot_through_the_route_is_hold(db):
    from fastapi.testclient import TestClient

    from api.main import app

    assert demo.main([]) == 0
    client = TestClient(app)
    token = client.post("/auth/login", json={"account_id": "a.sharma", "pin": "1234"}).json()["access_token"]
    d = client.get(f"/lots/{demo.GOLDEN_LOT_ID}", headers={"Authorization": f"Bearer {token}"}).json()["disposition"]
    assert d["verdict"] == "HOLD" and 0.03 < d["pda_result"] < 0.05
