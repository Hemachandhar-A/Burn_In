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
