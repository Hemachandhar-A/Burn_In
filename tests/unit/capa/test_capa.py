import pytest
from fastapi.testclient import TestClient
from storage import repository
from storage.repository import save_account, save_project, save_analysis_run, log_event
from identity.auth import create_access_token
from datetime import datetime, UTC
import csv
from io import StringIO

@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    """Each test points every storage.repository call at its own temp SQLite file. Monkeypatching
    engine/SessionLocal in place (same pattern as tests/integration/test_golden_module_a.py:25-37)
    is required here, not importlib.reload: capa/router.py, capa/logic.py, identity/auth.py and
    identity/router.py all do `from storage.repository import ...` at module level, and reload only
    rebinds names in the module that calls it - it would leave those four modules' own bound names
    stale. Monkeypatching the shared SessionLocal that every one of those already-imported functions
    reads at call time fixes every call site without touching those modules.
    """
    from storage import database
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    test_engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(repository, "SessionLocal", TestSessionLocal)

    repository.init_db()

    # Create test accounts
    save_account("account1", "User 1", "Quality Engineer", "$argon2id$v=19$m=65536,t=3,p=4$D/F5HjX44qVJQc5y1jNqFw$j92rKxR4q3b+Q/1Wc9B/f4D2a1d2e3f4g5h6i7j8k9")
    save_account("account2", "User 2", "Reliability Engineer", "$argon2id$v=19$m=65536,t=3,p=4$D/F5HjX44qVJQc5y1jNqFw$j92rKxR4q3b+Q/1Wc9B/f4D2a1d2e3f4g5h6i7j8k9")

    # Create test project
    save_project("test_proj", "lot_001", "PN123", datetime.now(UTC), "account1")
    from contracts import AnalysisResults, LotDisposition
    res = AnalysisResults(
        assessments=[],
        disposition=LotDisposition(lot_id="lot_001", status="COMPLETE", pda_result=0.0, verdict="ACCEPT", is_forecast=False)
    )
    save_analysis_run("test_proj", {}, res)

    yield

@pytest.fixture
def client():
    # Need to include the capa router if it's not already in api/main.py
    # Since we can't edit api/main.py per instructions, wait, I can edit api/main.py?
    # Actually the instruction says "Stay in my owned directories (capa/, identity/, tests/unit/capa/)."
    # If I can't edit api/main.py, I'll just include the router directly in the test client for testing.
    from fastapi import FastAPI
    from capa.router import router as capa_router
    from identity.router import router as identity_router
    
    test_app = FastAPI()
    test_app.include_router(capa_router)
    test_app.include_router(identity_router)
    return TestClient(test_app)

def test_capa_trigger_fires_when_lot_reject_count_crosses_threshold(client):
    """Block 4a-resume R3: identity/router.py::create_disposition no longer calls
    capa.logic.evaluate_capa_trigger automatically (its config_change/capa_action event was leaking
    into GET /events and GET /projects/{project_id}/events - real History routes - CONTRACT_CHANGES.md
    2026-09-30). evaluate_capa_trigger itself is unchanged, dead code, still directly callable - this
    test now calls it explicitly after seeding the same disposition_signoffs rows via the real
    endpoint, to keep exercising the function's own threshold/resolve logic."""
    from capa.logic import evaluate_capa_trigger

    token1 = create_access_token("account1", "Quality Engineer")
    token2 = create_access_token("account2", "Reliability Engineer")
    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    # Reject part 1 (needs 2 distinct accounts)
    client.post("/parts/comp1/disposition?project_id=test_proj&analysis_run_id=run-1",
                json={"verdict": "REJECT", "rationale": "r1"}, headers=headers1)
    client.post("/parts/comp1/disposition?project_id=test_proj&analysis_run_id=run-1",
                json={"verdict": "REJECT", "rationale": "r1"}, headers=headers2)

    # Reject part 2
    client.post("/parts/comp2/disposition?project_id=test_proj&analysis_run_id=run-1",
                json={"verdict": "REJECT", "rationale": "r2"}, headers=headers1)
    client.post("/parts/comp2/disposition?project_id=test_proj&analysis_run_id=run-1",
                json={"verdict": "REJECT", "rationale": "r2"}, headers=headers2)

    # Not auto-triggered any more - call the (now dead-code) function directly.
    evaluate_capa_trigger("test_proj")

    # Check if CAPA triggered yet (threshold is 3 distinct reject signoffs, actually it's total rejects.
    # We added 4 reject signoffs. Let's see if CAPA is there.)
    resp = client.get("/capa", headers=headers1)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    capa = resp.json()[0]
    assert capa["status"] == "OPEN"
    assert "Lot reject count" in capa["trigger_reason"]

    # Test resolve
    capa_id = capa["id"]
    resolve_resp = client.post(f"/capa/{capa_id}/resolve", json={"rationale": "Fixed issue"}, headers=headers1)
    assert resolve_resp.status_code == 200
    assert resolve_resp.json()["status"] == "RESOLVED"

def test_audit_log_export_produces_valid_csv_matching_schema(client):
    token = create_access_token("account1", "Quality Engineer")
    headers = {"Authorization": f"Bearer {token}"}
    
    # Log a dummy event
    log_event("test_proj", "account1", "config_change", {"dummy": "data"})
    
    resp = client.get("/audit/export", headers=headers)
    assert resp.status_code == 200
    
    content = resp.text
    f = StringIO(content)
    reader = csv.reader(f)
    rows = list(reader)
    
    assert len(rows) >= 2 # Header + at least one event
    assert rows[0] == ["event_id", "project_id", "account_id", "event_type", "timestamp", "payload"]
    assert "test_proj" in rows[-1]
    assert "account1" in rows[-1]
    assert "config_change" in rows[-1]

def test_capa_trigger_does_not_fire_below_threshold(client):
    """Block 4a-resume R3: calls evaluate_capa_trigger directly - see the note on
    test_capa_trigger_fires_when_lot_reject_count_crosses_threshold above."""
    from capa.logic import evaluate_capa_trigger

    token1 = create_access_token("account1", "Quality Engineer")
    headers1 = {"Authorization": f"Bearer {token1}"}

    client.post("/parts/comp3/disposition?project_id=test_proj&analysis_run_id=run-1",
                json={"verdict": "REJECT", "rationale": "r3"}, headers=headers1)
    evaluate_capa_trigger("test_proj")

    resp = client.get("/capa", headers=headers1)
    assert resp.status_code == 200
    assert len(resp.json()) == 0

def test_capa_trigger_does_not_fire_duplicates(client):
    """Block 4a-resume R3: calls evaluate_capa_trigger directly - see the note on
    test_capa_trigger_fires_when_lot_reject_count_crosses_threshold above."""
    from capa.logic import evaluate_capa_trigger

    token1 = create_access_token("account1", "Quality Engineer")
    token2 = create_access_token("account2", "Reliability Engineer")
    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    # Add 3 rejects
    for i in range(1, 4):
        client.post(f"/parts/comp_{i}/disposition?project_id=test_proj&analysis_run_id=run-1",
                    json={"verdict": "REJECT", "rationale": f"r{i}"}, headers=headers1)
    evaluate_capa_trigger("test_proj")

    resp = client.get("/capa", headers=headers1)
    assert len(resp.json()) == 1

    # Add 4th reject
    client.post("/parts/comp_4/disposition?project_id=test_proj&analysis_run_id=run-1",
                json={"verdict": "REJECT", "rationale": "r4"}, headers=headers1)
    evaluate_capa_trigger("test_proj")

    resp2 = client.get("/capa", headers=headers1)
    # Should still be exactly 1 CAPA open for this project
    assert len(resp2.json()) == 1

def test_resolve_capa_not_found(client):
    token = create_access_token("account1", "Quality Engineer")
    headers = {"Authorization": f"Bearer {token}"}
    
    resp = client.post("/capa/invalid-id/resolve", json={"rationale": "Fixed"}, headers=headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "CAPA not found"

def test_resolve_capa_already_resolved(client):
    """Block 4a-resume R3: calls evaluate_capa_trigger directly - see the note on
    test_capa_trigger_fires_when_lot_reject_count_crosses_threshold above."""
    from capa.logic import evaluate_capa_trigger

    token1 = create_access_token("account1", "Quality Engineer")
    headers1 = {"Authorization": f"Bearer {token1}"}

    # Create 3 rejects to trigger CAPA
    for i in range(1, 4):
        client.post(f"/parts/comp_{i}_dup/disposition?project_id=test_proj&analysis_run_id=run-1",
                    json={"verdict": "REJECT", "rationale": f"r{i}"}, headers=headers1)
    evaluate_capa_trigger("test_proj")

    capas = client.get("/capa", headers=headers1).json()
    assert len(capas) > 0
    capa_id = capas[0]["id"]
    
    # Resolve first time
    resp1 = client.post(f"/capa/{capa_id}/resolve", json={"rationale": "Fixed"}, headers=headers1)
    assert resp1.status_code == 200
    
    # Resolve second time
    resp2 = client.post(f"/capa/{capa_id}/resolve", json={"rationale": "Double fix"}, headers=headers1)
    assert resp2.status_code == 400
    assert resp2.json()["detail"] == "CAPA already resolved"
