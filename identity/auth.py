import os
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from contracts import Account
from storage.repository import query_account

# Load from environment or fallback for tests/dev
JWT_SECRET = os.environ.get("JWT_SECRET", "test-secret-key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = int(os.environ.get("JWT_EXPIRY_MINUTES", "60"))

security = HTTPBearer()
hasher = PasswordHasher()


def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    try:
        return hasher.verify(hashed_pin, plain_pin)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def create_access_token(account_id: str, role: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": account_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_account(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)]
) -> Account:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        account_id = payload.get("sub")
        if not account_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing subject",
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    account = query_account(account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account not found",
        )

    return account
