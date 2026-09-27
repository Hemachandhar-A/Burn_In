from fastapi import APIRouter, HTTPException, status
from contracts import LoginRequest, TokenResponse
from identity.auth import create_access_token, verify_pin
from storage.repository import query_account

router = APIRouter(tags=["Auth"])


@router.post("/auth/login", response_model=TokenResponse)
def login(request: LoginRequest):
    account = query_account(request.account_id)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid account ID or PIN",
        )

    if not verify_pin(request.pin, account.pin_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid account ID or PIN",
        )

    token = create_access_token(account.account_id, account.role)
    return TokenResponse(
        access_token=token,
        account_id=account.account_id,
        role=account.role,
    )
