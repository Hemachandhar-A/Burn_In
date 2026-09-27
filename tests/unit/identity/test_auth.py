import time
from datetime import UTC, datetime, timedelta
import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from contracts import Account
from identity.auth import (
    JWT_ALGORITHM,
    JWT_SECRET,
    create_access_token,
    get_current_account,
    hasher,
    verify_pin,
)


def test_argon2_pin_hashing():
    plain = "1234"
    hashed = hasher.hash(plain)
    assert verify_pin(plain, hashed) is True
    assert verify_pin("wrong", hashed) is False


def test_jwt_round_trip(monkeypatch):
    # Mock query_account to return a dummy account
    dummy_account = Account(account_id="a.sharma", display_name="A. Sharma", role="Quality Engineer", pin_hash="hashed")
    monkeypatch.setattr("identity.auth.query_account", lambda acc_id: dummy_account if acc_id == "a.sharma" else None)

    # Valid token
    token = create_access_token("a.sharma", "Quality Engineer")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    account = get_current_account(creds)
    assert account.account_id == "a.sharma"
    assert account.role == "Quality Engineer"


def test_jwt_expired_token(monkeypatch):
    # Create an expired token manually
    now = datetime.now(UTC)
    payload = {
        "sub": "a.sharma",
        "role": "Quality Engineer",
        "iat": now - timedelta(minutes=10),
        "exp": now - timedelta(minutes=5),  # expired 5 mins ago
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc:
        get_current_account(creds)
    assert exc.value.status_code == 401
    assert "Token expired" in exc.value.detail


def test_jwt_tampered_token():
    # Valid token but altered
    token = create_access_token("a.sharma", "Quality Engineer")
    tampered_token = token[:-5] + "aaaaa"
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tampered_token)

    with pytest.raises(HTTPException) as exc:
        get_current_account(creds)
    assert exc.value.status_code == 401
    assert "Invalid token" in exc.value.detail


def test_jwt_missing_subject():
    now = datetime.now(UTC)
    payload = {
        "role": "Quality Engineer",
        "exp": now + timedelta(minutes=60),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    with pytest.raises(HTTPException) as exc:
        get_current_account(creds)
    assert exc.value.status_code == 401
    assert "Token missing subject" in exc.value.detail
