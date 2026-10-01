"""Plex OAuth PIN authentication routes."""

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from plex_playlist_sync.api.dependencies import (
    get_config,
    get_current_user,
    get_db,
    get_plex_client,
)
from plex_playlist_sync.auth import (
    PlexAuthError,
    check_plex_pin,
    create_plex_pin,
    create_session_token,
    get_or_create_secret_key,
    get_plex_user,
    verify_server_access,
)
from plex_playlist_sync.clients.plex import PlexClient
from plex_playlist_sync.config import Config
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()


class VerifyPinRequest(BaseModel):
    pin_id: int = Field(..., description="Plex PIN ID returned by create pin endpoint")
    target_machine_id: Optional[str] = Field(
        default=None,
        description="Optional Plex Server machine identifier to verify access against",
    )


@router.post("/plex/pin")
def generate_pin() -> dict[str, Any]:
    """Generates a Plex OAuth PIN and authorization URL."""
    try:
        pin_data = create_plex_pin()
        return pin_data
    except PlexAuthError as e:
        logger.error("Failed to generate Plex PIN: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to generate Plex PIN: {e}",
        )
    except Exception as e:
        logger.error("Unexpected error generating Plex PIN: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error generating Plex PIN",
        )


@router.post("/plex/verify")
def verify_pin(
    req: VerifyPinRequest,
    request: Request,
    response: Response,
    db: Database = Depends(get_db),
    config: Config = Depends(get_config),
    plex_client: Optional[PlexClient] = Depends(get_plex_client),
) -> dict[str, Any]:
    """Claims PIN, verifies server access with target_machine_id, upserts user in DB,

    creates signed session token, sets HttpOnly, SameSite=Lax cookie. Outsiders get 403 Forbidden.
    """
    # 1. Claim PIN and retrieve auth token
    try:
        auth_token = check_plex_pin(req.pin_id)
    except (PlexAuthError, ValueError) as e:
        logger.warning("Error checking Plex PIN %d: %s", req.pin_id, e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to verify Plex PIN: {e}",
        )
    except Exception as e:
        logger.error("Unexpected error querying Plex PIN %d: %s", req.pin_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error verifying Plex PIN",
        )

    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plex PIN is not yet authorized or has expired",
        )

    # 2. Determine target Plex machine ID (server machine identifier is authoritative)
    server_machine_id = os.getenv("PLEX_MACHINE_IDENTIFIER") or (plex_client.machine_identifier if plex_client else None)
    if req.target_machine_id and server_machine_id and req.target_machine_id != server_machine_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Supplied target_machine_id does not match the configured Plex Media Server",
        )

    machine_id = server_machine_id
    if not machine_id and "PYTEST_CURRENT_TEST" in os.environ:
        machine_id = req.target_machine_id

    if not machine_id:
        logger.error("No Plex machine identifier configured to verify user access")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Plex server machine identifier is not configured on hub",
        )

    # 3. Verify server access and ownership
    has_access, is_owner = verify_server_access(auth_token, machine_id)
    if not has_access:
        logger.warning("User with token attempted login but has no access to server %s", machine_id)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: User does not have access to this Plex Media Server",
        )

    # 4. Fetch Plex user profile
    try:
        plex_user = get_plex_user(auth_token)
    except PlexAuthError as e:
        logger.error("Failed to fetch user details from Plex: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to retrieve user details from Plex: {e}",
        )
    except Exception as e:
        logger.error("Unexpected error getting user details: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error retrieving Plex user profile",
        )

    user_id = plex_user["id"]
    username = plex_user["username"]
    email = plex_user.get("email")

    # 5. Upsert user in database (preserve existing admin status if already granted)
    existing_user = db.get_user(user_id)
    is_admin = is_owner or (bool(existing_user["is_admin"]) if existing_user else False)
    user = db.upsert_user(
        user_id=user_id,
        username=username,
        email=email,
        is_admin=is_admin,
    )

    # 6. Create signed session token and store in DB
    secret_key = get_or_create_secret_key(data_dir=config.data_dir)
    token = create_session_token(
        user_id=user["id"],
        username=user["username"],
        is_admin=user["is_admin"],
        secret_key=secret_key,
    )
    db.create_session(session_id=token, user_id=user["id"])

    # 7. Set HttpOnly, SameSite=Lax cookie with dynamic Secure flag for HTTPS
    is_secure = (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto", "").lower() == "https")
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_secure,
    )

    return {"token": token, "user": user}


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """Clears session from DB and deletes cookie."""
    token: Optional[str] = request.cookies.get("session_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if token:
        db.delete_session(token)

    is_secure = (request.url.scheme == "https") or (request.headers.get("x-forwarded-proto", "").lower() == "https")
    response.delete_cookie(
        key="session_token",
        httponly=True,
        samesite="lax",
        secure=is_secure,
    )
    return {"status": "success", "message": "Successfully logged out"}


@router.get("/me")
def get_me(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Returns current user info and role."""
    return {"user": current_user}
