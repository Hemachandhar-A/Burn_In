import pytest
from fastapi.testclient import TestClient
from api.main import app
from storage.database import Base, engine, SessionLocal
from storage.repository import save_account, save_project, save_analysis_run, log_event
from identity.auth import create_access_token
from datetime import datetime, UTC
import csv
from io import StringIO

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    
    # Create test accounts
    save_account("account1", "User 1", "Quality Engineer", "$argon2id$v=19$m=65536,t=3,p=4$D/F5HjX44qVJQc5y1jNqFw$j92rKxR4q3b+Q/1Wc9B/f4D2a1d2e3f4g5h6i7j8k9")
    save_account("account2", "User 2", "Reliability Engineer", "$argon2id$v=19$m=65536,t=3,p=4$D/F5HjX44qVJQc5y1jNqFw$j92rKxR4q3b+Q/1Wc9B/f4D2a1d2e3f4g5h6i7j8k9")
    
    # Create test project
    save_project("test_proj", "lot_001", "PN123", datetime.now(UTC), "account1")
    save_analysis_run("test_proj", {}, {})
    
    yield
    Base.metadata.drop_all(bind=engine)

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
