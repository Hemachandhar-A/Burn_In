"""Block 4a-resume R3: capa.logic.evaluate_capa_trigger's call site was removed from
identity/router.py::create_disposition (CONTRACT_CHANGES.md 2026-09-30) after a live check
(scratchpad script, not part of the repo) proved its config_change/capa_action event leaked into
GET /events and GET /projects/{project_id}/events - real, registered History routes - polluting the
shared timeline with an unplanned event shape. evaluate_capa_trigger itself is left in capa/logic.py
as dead code, not deleted. This test proves three REJECT dispositions (dual signed-off, crossing the
function's own >=3 threshold) now add no event to the Settings history and no capa_action event
anywhere, using the real storage layer (not mocked query_events) so the proof is against actual rows.
"""
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from identity.auth import create_access_token
from storage import repository
from storage.repository import query_events, save_account, save_project


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
    save_account("account2", "User 2", "Reliability Engineer", "$argon2id$v=19$m=65536,t=3,p=4$x$y")
    save_project("proj1", "lot_001", "PN123", datetime.now(UTC), "account1")


@pytest.fixture
def client():
    from identity.router import router as identity_router

    app = FastAPI()
    app.include_router(identity_router)
    return TestClient(app)


@pytest.fixture
def headers1():
    return {"Authorization": f"Bearer {create_access_token('account1', 'Quality Engineer')}"}


@pytest.fixture
def headers2():
    return {"Authorization": f"Bearer {create_access_token('account2', 'Reliability Engineer')}"}


def test_three_reject_dispositions_add_no_capa_action_event_anywhere(client, headers1, headers2):
    for cid in ("comp1", "comp2", "comp3"):
        r1 = client.post(f"/parts/{cid}/disposition?project_id=proj1&analysis_run_id=run-1",
                          json={"verdict": "REJECT", "rationale": f"reject {cid}"}, headers=headers1)
        r2 = client.post(f"/parts/{cid}/disposition?project_id=proj1&analysis_run_id=run-1",
                          json={"verdict": "REJECT", "rationale": f"reject {cid} confirm"}, headers=headers2)
        assert r1.status_code == 200
        assert r2.status_code == 200

    events = query_events()
    assert not any(e.event_type == "config_change" and "capa_action" in e.payload for e in events)


def test_three_reject_dispositions_add_no_event_to_the_settings_history(client, headers1, headers2):
    for cid in ("comp1", "comp2", "comp3"):
        client.post(f"/parts/{cid}/disposition?project_id=proj1&analysis_run_id=run-1",
                    json={"verdict": "REJECT", "rationale": f"reject {cid}"}, headers=headers1)
        client.post(f"/parts/{cid}/disposition?project_id=proj1&analysis_run_id=run-1",
                    json={"verdict": "REJECT", "rationale": f"reject {cid} confirm"}, headers=headers2)

    resp = client.get("/settings", headers=headers1)
    assert resp.status_code == 200
    assert resp.json()["pending_changes"] == []
