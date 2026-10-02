"""E13 step 4 (Block 4a Part 4): GET /settings/worklist - signed-off dispositions with no matching
confirmed-outcome record for that (project_id, component_id) pair. Tracking only, changes nothing.
One entry per disposition_signoffs row (WorklistResponse.pending: list[DispositionRecord], the
contract's own literal shape) - a REJECT's two dual-sign-off rows both appear if neither part has a
confirmed outcome yet, since the contract wraps DispositionRecord directly, not a deduped-by-part view.
"""
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from identity.auth import create_access_token
from storage import repository
from storage.repository import (
    save_account, save_confirmed_outcome, save_disposition_signoff, save_project,
)


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    from storage import database
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    test_engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(repository, "SessionLocal", TestSessionLocal)

    repository.init_db()
    save_account("account1", "User 1", "Quality Engineer", "$argon2id$v=19$m=65536,t=3,p=4$x$y")
    save_project("proj1", "lot_001", "PN123", datetime.now(UTC), "account1")


@pytest.fixture
def client():
    from capa.router import planned_router

    app = FastAPI()
    app.include_router(planned_router)
    return TestClient(app)


@pytest.fixture
def auth_headers():
    token = create_access_token("account1", "Quality Engineer")
    return {"Authorization": f"Bearer {token}"}


def test_a_disposition_with_no_outcome_appears(client, auth_headers):
    save_disposition_signoff(
        project_id="proj1", component_id="comp1", analysis_run_id="run-1",
        account_id="account1", verdict="HOLD", rationale="needs review",
    )

    resp = client.get("/settings/worklist", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["pending"]) == 1
    assert body["pending"][0]["component_id"] == "comp1"
    assert body["pending"][0]["project_id"] == "proj1"
    assert body["pending"][0]["verdict"] == "HOLD"


def test_disappears_after_confirmed_outcome_recorded(client, auth_headers):
    save_disposition_signoff(
        project_id="proj1", component_id="comp1", analysis_run_id="run-1",
        account_id="account1", verdict="HOLD", rationale="needs review",
    )
    save_confirmed_outcome(
        project_id="proj1", component_id="comp1", analysis_run_id="run-1",
        account_id="account1", confirmed_outcome="Confirmed Good",
    )

    resp = client.get("/settings/worklist", headers=auth_headers)
    assert resp.json()["pending"] == []


def test_another_part_unaffected(client, auth_headers):
    save_disposition_signoff(
        project_id="proj1", component_id="comp1", analysis_run_id="run-1",
        account_id="account1", verdict="HOLD", rationale="r1",
    )
    save_disposition_signoff(
        project_id="proj1", component_id="comp2", analysis_run_id="run-1",
        account_id="account1", verdict="ACCEPT", rationale="r2",
    )
    save_confirmed_outcome(
        project_id="proj1", component_id="comp1", analysis_run_id="run-1",
        account_id="account1", confirmed_outcome="Confirmed Good",
    )

    resp = client.get("/settings/worklist", headers=auth_headers)
    pending = resp.json()["pending"]
    assert len(pending) == 1
    assert pending[0]["component_id"] == "comp2"


def test_count_matches_n_dispositions_awaiting_a_confirmed_outcome(client, auth_headers):
    for i in range(4):
        save_disposition_signoff(
            project_id="proj1", component_id=f"comp{i}", analysis_run_id="run-1",
            account_id="account1", verdict="ACCEPT", rationale=f"r{i}",
        )
    save_confirmed_outcome(
        project_id="proj1", component_id="comp0", analysis_run_id="run-1",
        account_id="account1", confirmed_outcome="Confirmed Good",
    )

    resp = client.get("/settings/worklist", headers=auth_headers)
    assert len(resp.json()["pending"]) == 3


def test_requires_auth(client):
    resp = client.get("/settings/worklist")
    assert resp.status_code in (401, 403)


def test_endpoint_writes_nothing(client, auth_headers):
    save_disposition_signoff(
        project_id="proj1", component_id="comp1", analysis_run_id="run-1",
        account_id="account1", verdict="HOLD", rationale="r1",
    )
    from storage.repository import query_confirmed_outcomes, query_disposition_signoffs
    before_outcomes = len(query_confirmed_outcomes())
    before_signoffs = len(query_disposition_signoffs())

    client.get("/settings/worklist", headers=auth_headers)

    assert len(query_confirmed_outcomes()) == before_outcomes
    assert len(query_disposition_signoffs()) == before_signoffs
