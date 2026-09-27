from fastapi.testclient import TestClient
from fastapi import FastAPI
import pytest
from argon2 import PasswordHasher
from contracts import Account
from identity.router import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)
hasher = PasswordHasher()

@pytest.fixture
def dummy_accounts(monkeypatch):
    accounts = {
        "a.sharma": Account(
            account_id="a.sharma", 
            display_name="A. Sharma", 
            role="Quality Engineer", 
            pin_hash=hasher.hash("1234")
        ),
        "r.mehta": Account(
            account_id="r.mehta", 
            display_name="R. Mehta", 
            role="Reliability Engineer", 
            pin_hash=hasher.hash("5678")
        )
    }
    monkeypatch.setattr("identity.router.query_account", lambda acc_id: accounts.get(acc_id))
    monkeypatch.setattr("identity.auth.query_account", lambda acc_id: accounts.get(acc_id))
    return accounts

def test_login_success(dummy_accounts):
    response = client.post("/auth/login", json={"account_id": "a.sharma", "pin": "1234"})
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["account_id"] == "a.sharma"
    assert data["role"] == "Quality Engineer"

def test_login_invalid_account(dummy_accounts):
    response = client.post("/auth/login", json={"account_id": "unknown", "pin": "1234"})
    assert response.status_code == 401
    assert "Invalid account ID or PIN" in response.json()["detail"]

def test_login_invalid_pin(dummy_accounts):
    response = client.post("/auth/login", json={"account_id": "r.mehta", "pin": "wrong"})
    assert response.status_code == 401
    assert "Invalid account ID or PIN" in response.json()["detail"]

def test_login_missing_fields(dummy_accounts):
    # Missing PIN
    response = client.post("/auth/login", json={"account_id": "a.sharma"})
    assert response.status_code == 422

    # Missing account_id
    response = client.post("/auth/login", json={"pin": "1234"})
    assert response.status_code == 422

def test_login_malformed_json(dummy_accounts):
    # Send bad JSON string instead of object
    response = client.post(
        "/auth/login", 
        data='{"account_id": "a.sharma", "pin": 1234', 
        headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422

@pytest.fixture
def dummy_token(dummy_accounts):
    from identity.auth import create_access_token
    return create_access_token("a.sharma", "Quality Engineer")

@pytest.fixture
def auth_headers(dummy_token):
    return {"Authorization": f"Bearer {dummy_token}"}

@pytest.fixture
def dummy_token2(dummy_accounts):
    from identity.auth import create_access_token
    return create_access_token("r.mehta", "Reliability Engineer")

@pytest.fixture
def auth_headers2(dummy_token2):
    return {"Authorization": f"Bearer {dummy_token2}"}

def test_disposition_accept(auth_headers, monkeypatch):
    from contracts import DispositionSignoff
    from datetime import datetime, UTC
    
    mock_save = []
    def mock_save_disposition(*args, **kwargs):
        mock_save.append(kwargs)
        return DispositionSignoff(
            project_id=kwargs["project_id"],
            component_id=kwargs["component_id"],
            account_id=kwargs["account_id"],
            verdict=kwargs["verdict"],
            rationale=kwargs["rationale"],
            timestamp=datetime.now(UTC),
            analysis_run_id=kwargs["analysis_run_id"]
        )
    monkeypatch.setattr("identity.router.save_disposition_signoff", mock_save_disposition)
    monkeypatch.setattr("identity.router.query_disposition_signoffs", lambda **kw: [])
    
    response = client.post(
        "/parts/comp1/disposition",
        params={"project_id": "proj1", "analysis_run_id": "run1"},
        json={"verdict": "ACCEPT", "rationale": "Looks good"},
        headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["verdict"] == "ACCEPT"
    assert len(mock_save) == 1
    assert mock_save[0]["account_id"] == "a.sharma"

def test_disposition_reject_dual_signoff_same_user(auth_headers, monkeypatch):
    from contracts import DispositionSignoff
    from datetime import datetime, UTC, timedelta
    
    existing = DispositionSignoff(
        project_id="proj1",
        component_id="comp1",
        analysis_run_id="run1",
        account_id="a.sharma",
        verdict="REJECT",
        rationale="Bad part",
        timestamp=datetime.now(UTC) - timedelta(minutes=5)
    )
    monkeypatch.setattr("identity.router.query_disposition_signoffs", lambda **kw: [existing])
    
    response = client.post(
        "/parts/comp1/disposition",
        params={"project_id": "proj1", "analysis_run_id": "run1"},
        json={"verdict": "REJECT", "rationale": "I agree it is bad"},
        headers=auth_headers
    )
    assert response.status_code == 400
    assert "two distinct account IDs" in response.json()["detail"]

def test_disposition_reject_dual_signoff_timing_flag(auth_headers, auth_headers2, monkeypatch):
    from contracts import DispositionSignoff, Event
    from datetime import datetime, UTC, timedelta
    
    existing = DispositionSignoff(
        project_id="proj1",
        component_id="comp1",
        analysis_run_id="run1",
        account_id="a.sharma",
        verdict="REJECT",
        rationale="Bad part",
        timestamp=datetime.now(UTC) - timedelta(minutes=1)
    )
    monkeypatch.setattr("identity.router.query_disposition_signoffs", lambda **kw: [existing])
    
    events_logged = []
    def mock_log_event(*args, **kwargs):
        events_logged.append(kwargs)
    monkeypatch.setattr("identity.router.log_event", mock_log_event)
    monkeypatch.setattr("capa.logic.evaluate_capa_trigger", lambda p: None)
    
    def mock_save_disposition(*args, **kwargs):
        return DispositionSignoff(
            project_id=kwargs["project_id"],
            component_id=kwargs["component_id"],
            account_id=kwargs["account_id"],
            verdict=kwargs["verdict"],
            rationale=kwargs["rationale"],
            timestamp=datetime.now(UTC),
            analysis_run_id=kwargs["analysis_run_id"]
        )
    monkeypatch.setattr("identity.router.save_disposition_signoff", mock_save_disposition)

    response = client.post(
        "/parts/comp1/disposition",
        params={"project_id": "proj1", "analysis_run_id": "run1"},
        json={"verdict": "REJECT", "rationale": "Confirmed bad part"},
        headers=auth_headers2
    )
    assert response.status_code == 200
    assert response.json()["account_id"] == "r.mehta"
    assert len(events_logged) == 1
    assert events_logged[0]["payload"]["timing_flag"] is True

def test_settings_propose(auth_headers, monkeypatch):
    monkeypatch.setattr("identity.router.query_events", lambda: [])
    events_logged = []
    def mock_log_event(*args, **kwargs):
        events_logged.append(kwargs)
    monkeypatch.setattr("identity.router.log_event", mock_log_event)

    response = client.post(
        "/settings/propose",
        json={"field": "fn_fp_cost_ratio", "proposed_value": 15.0},
        headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["proposed_by"] == "a.sharma"
    assert len(events_logged) == 1
    assert events_logged[0]["payload"]["action"] == "propose"

def test_settings_signoff_same_user(auth_headers, monkeypatch):
    from contracts import Event
    from datetime import datetime, UTC
    
    class DummyEvent:
        def __init__(self):
            self.event_type = "config_change"
            self.account_id = "a.sharma"
            self.payload = {"action": "propose", "field": "fn_fp_cost_ratio", "proposed_value": 15.0}

    monkeypatch.setattr("identity.router.query_events", lambda: [DummyEvent()])
    
    response = client.post(
        "/settings/signoff",
        json={"field": "fn_fp_cost_ratio"},
        headers=auth_headers
    )
    assert response.status_code == 400
    assert "two distinct account IDs" in response.json()["detail"]

def test_settings_signoff_distinct_user(auth_headers2, monkeypatch):
    from contracts import Event
    from datetime import datetime, UTC
    
    class DummyEvent:
        def __init__(self, action="propose", account_id="a.sharma"):
            self.event_type = "config_change"
            self.account_id = account_id
            self.payload = {"action": action, "field": "fn_fp_cost_ratio", "proposed_value": 15.0}

    events = [DummyEvent()]
    monkeypatch.setattr("identity.router.query_events", lambda: events)
    events_logged = []
    def mock_log_event(*args, **kwargs):
        events_logged.append(kwargs)
        # also append to events so subsequent query_events sees it
        events.append(DummyEvent(action=kwargs["payload"]["action"], account_id=kwargs["account_id"]))
        
    monkeypatch.setattr("identity.router.log_event", mock_log_event)

    response = client.post(
        "/settings/signoff",
        json={"field": "fn_fp_cost_ratio"},
        headers=auth_headers2
    )
    assert response.status_code == 200
    assert response.json()["fn_fp_cost_ratio"] == 15.0
    assert len(events_logged) == 1
    assert events_logged[0]["payload"]["action"] == "signoff"

def test_disposition_hold(auth_headers, monkeypatch):
    from contracts import DispositionSignoff
    from datetime import datetime, UTC
    
    mock_save = []
    def mock_save_disposition(*args, **kwargs):
        mock_save.append(kwargs)
        return DispositionSignoff(
            project_id=kwargs["project_id"],
            component_id=kwargs["component_id"],
            account_id=kwargs["account_id"],
            verdict=kwargs["verdict"],
            rationale=kwargs["rationale"],
            timestamp=datetime.now(UTC),
            analysis_run_id=kwargs["analysis_run_id"]
        )
    monkeypatch.setattr("identity.router.save_disposition_signoff", mock_save_disposition)
    monkeypatch.setattr("identity.router.query_disposition_signoffs", lambda **kw: [])
    
    response = client.post(
        "/parts/comp1/disposition",
        params={"project_id": "proj1", "analysis_run_id": "run1"},
        json={"verdict": "HOLD", "rationale": "Needs review"},
        headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["verdict"] == "HOLD"
    assert len(mock_save) == 1

def test_disposition_reject_dual_signoff_no_timing_flag(auth_headers, auth_headers2, monkeypatch):
    from contracts import DispositionSignoff
    from datetime import datetime, UTC, timedelta
    
    existing = DispositionSignoff(
        project_id="proj1",
        component_id="comp1",
        analysis_run_id="run1",
        account_id="a.sharma",
        verdict="REJECT",
        rationale="Bad part",
        timestamp=datetime.now(UTC) - timedelta(minutes=5)
    )
    monkeypatch.setattr("identity.router.query_disposition_signoffs", lambda **kw: [existing])
    
    events_logged = []
    def mock_log_event(*args, **kwargs):
        events_logged.append(kwargs)
    monkeypatch.setattr("identity.router.log_event", mock_log_event)
    monkeypatch.setattr("capa.logic.evaluate_capa_trigger", lambda p: None)
    
    def mock_save_disposition(*args, **kwargs):
        return DispositionSignoff(
            project_id=kwargs["project_id"],
            component_id=kwargs["component_id"],
            account_id=kwargs["account_id"],
            verdict=kwargs["verdict"],
            rationale=kwargs["rationale"],
            timestamp=datetime.now(UTC),
            analysis_run_id=kwargs["analysis_run_id"]
        )
    monkeypatch.setattr("identity.router.save_disposition_signoff", mock_save_disposition)

    response = client.post(
        "/parts/comp1/disposition",
        params={"project_id": "proj1", "analysis_run_id": "run1"},
        json={"verdict": "REJECT", "rationale": "Confirmed bad part"},
        headers=auth_headers2
    )
    assert response.status_code == 200
    assert response.json()["account_id"] == "r.mehta"
    assert len(events_logged) == 0

def test_settings_propose_already_pending(auth_headers, monkeypatch):
    class DummyEvent:
        def __init__(self, action="propose", account_id="a.sharma"):
            self.event_type = "config_change"
            self.account_id = account_id
            self.payload = {"action": action, "field": "fn_fp_cost_ratio", "proposed_value": 15.0}

    monkeypatch.setattr("identity.router.query_events", lambda: [DummyEvent()])

    response = client.post(
        "/settings/propose",
        json={"field": "fn_fp_cost_ratio", "proposed_value": 20.0},
        headers=auth_headers
    )
    assert response.status_code == 400
    assert "Change already pending for this field" in response.json()["detail"]

def test_settings_signoff_no_pending(auth_headers2, monkeypatch):
    monkeypatch.setattr("identity.router.query_events", lambda: [])

    response = client.post(
        "/settings/signoff",
        json={"field": "fn_fp_cost_ratio"},
        headers=auth_headers2
    )
    assert response.status_code == 400
    assert "No pending change for this field" in response.json()["detail"]

def test_settings_get(auth_headers, monkeypatch):
    class DummyEvent:
        def __init__(self, action="propose", account_id="a.sharma"):
            self.event_type = "config_change"
            self.account_id = account_id
            self.payload = {"action": action, "field": "fn_fp_cost_ratio", "proposed_value": 15.0}

    monkeypatch.setattr("identity.router.query_events", lambda: [DummyEvent()])

    response = client.get("/settings", headers=auth_headers)
    assert response.status_code == 200
    
    data = response.json()
    assert data["fn_fp_cost_ratio"] != 15.0 # Should be original value because it's only proposed
    assert len(data["pending_changes"]) == 1
    assert data["pending_changes"][0]["field"] == "fn_fp_cost_ratio"
    assert data["pending_changes"][0]["proposed_value"] == 15.0
