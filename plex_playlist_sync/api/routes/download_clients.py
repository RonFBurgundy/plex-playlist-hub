"""REST API endpoints for managing download clients and connection testing."""

import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from plex_playlist_sync.api.dependencies import get_db, require_admin, require_user
from plex_playlist_sync.clients.acquisition import get_acquisition_driver
from plex_playlist_sync.models import DownloadClientConfig, DownloadDriverType
from plex_playlist_sync.security import is_safe_service_url, mask_secret
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()


class DownloadClientItem(BaseModel):
    id: str
    name: str
    driver_type: str
    host_url: str
    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    enabled: bool = True
    priority: int = 1
    extra_settings_json: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DownloadClientPayload(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=120)
    driver_type: str
    host_url: str
    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    enabled: bool = True
    priority: int = 1
    extra_settings_json: Optional[str] = None


class TestConnectionPayload(BaseModel):
    driver_type: str
    host_url: str
    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    extra_settings_json: Optional[str] = None


class TestConnectionResponse(BaseModel):
    success: bool
    message: str


def _mask_client_dict(client: dict[str, Any]) -> dict[str, Any]:
    c = dict(client)
    if c.get("api_key"):
        c["api_key"] = mask_secret(c["api_key"])
    if c.get("password"):
        c["password"] = mask_secret(c["password"])
    return c


@router.get("", response_model=list[DownloadClientItem], summary="List configured download clients")
@router.get("/", response_model=list[DownloadClientItem], include_in_schema=False)
def list_download_clients(
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_user),
) -> list[dict[str, Any]]:
    """Lists all configured download clients with masked credentials."""
    clients = db.list_download_clients()
    return [_mask_client_dict(c) for c in clients]


@router.post("", response_model=DownloadClientItem, summary="Create or update download client")
@router.post("/", response_model=DownloadClientItem, include_in_schema=False)
def create_or_update_download_client(
    payload: DownloadClientPayload,
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Admin-only endpoint to save or update a download client."""
    # SSRF Validation
    clean_host = payload.host_url.strip()
    if not is_safe_service_url(clean_host):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prohibited or invalid host URL (SSRF protection)",
        )

    # Validate driver type
    valid_types = {t.value for t in DownloadDriverType}
    clean_type = payload.driver_type.strip().lower()
    if clean_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid driver type '{payload.driver_type}'. Supported: {', '.join(sorted(valid_types))}",
        )

    client_id = payload.id.strip() if payload.id and payload.id.strip() else str(uuid.uuid4())
    existing = db.get_download_client(client_id)

    # Preserve secret if masked or omitted during edit
    api_key = payload.api_key
    if api_key and "•••" in api_key and existing:
        api_key = existing.get("api_key")
    elif not api_key and existing:
        api_key = existing.get("api_key")

    password = payload.password
    if password and "•••" in password and existing:
        password = existing.get("password")
    elif not password and existing:
        password = existing.get("password")

    config = DownloadClientConfig(
        id=client_id,
        name=payload.name.strip(),
        driver_type=clean_type,
        host_url=clean_host,
        api_key=api_key,
        username=payload.username.strip() if payload.username else None,
        password=password,
        enabled=payload.enabled,
        priority=payload.priority,
        extra_settings_json=payload.extra_settings_json,
    )

    saved = db.create_download_client(config)
    return _mask_client_dict(saved)


@router.post("/test", response_model=TestConnectionResponse, summary="Test download client connection")
def test_download_client_connection(
    payload: TestConnectionPayload,
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_user),
) -> TestConnectionResponse:
    """Tests connectivity to a download client before saving."""
    clean_host = payload.host_url.strip()
    if not is_safe_service_url(clean_host):
        return TestConnectionResponse(
            success=False,
            message="Prohibited or invalid host URL (SSRF defense)",
        )

    try:
        driver = get_acquisition_driver(
            {
                "driver_type": payload.driver_type,
                "host_url": clean_host,
                "api_key": payload.api_key,
                "username": payload.username,
                "password": payload.password,
                "extra_settings_json": payload.extra_settings_json,
            }
        )
        success, msg = driver.test_connection()
        return TestConnectionResponse(success=success, message=msg)
    except Exception as e:
        logger.warning("Download client connection test failed: %s", e)
        return TestConnectionResponse(success=False, message=str(e))


@router.delete("/{client_id}", summary="Delete download client")
def delete_download_client(
    client_id: str,
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Admin-only deletion of a download client."""
    deleted = db.delete_download_client(client_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Download client '{client_id}' not found",
        )
    return {"status": "deleted", "id": client_id}
