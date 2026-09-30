import logging
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

logger = logging.getLogger(__name__)

# Dev-only fallback, >= 32 bytes so PyJWT never raises InsecureKeyLengthWarning for HS256 (RFC
# 7518 3.2). Never used when JWT_SECRET is set - real deployments must set it.
_DEV_DEFAULT_JWT_SECRET = "dev-only-insecure-default-jwt-secret-min-32-bytes-not-for-prod"

JWT_SECRET = os.environ.get("JWT_SECRET")
if JWT_SECRET is None:
    JWT_SECRET = _DEV_DEFAULT_JWT_SECRET
    logger.warning(
        "JWT_SECRET is not set - falling back to an insecure dev-only default. "
        "Set the JWT_SECRET environment variable before running in production."
    )
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
