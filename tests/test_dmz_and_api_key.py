"""Unit and integration tests for DMZ isolation mode and Machine API Key authentication.

Verifies:
1. Schema migration v18 auto-creation and seeding of api_key in general_settings.
2. Database validate_api_key, get_api_key, and regenerate_api_key behavior.
3. GET /api/settings/api-key and POST /api/settings/api-key/regenerate endpoints.
4. X-Api-Key and query parameter machine authentication across protected endpoints.
5. In ROLE=gateway mode, library mutation endpoints return HTTP 403 Forbidden.
6. In ROLE=gateway mode, GET /api/library/availability forwards to Core via CoreClient.
7. In ROLE=gateway mode, request creation forwards to Core with X-Internal-Token.
8. Error handling when Core is unreachable (HTTP 502 Bad Gateway).
9. Internal token authentication (X-Internal-Token and Bearer internal secret).
10. Single-container mode (ROLE=all-in-one) backward compatibility.
11. Config environment variable parsing for DMZ settings.
"""

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from plex_playlist_sync.api.app import create_app
from plex_playlist_sync.api.dependencies import get_config, get_db
from plex_playlist_sync.auth import create_session_token, get_or_create_secret_key
from plex_playlist_sync.clients.core_client import CoreClient
from plex_playlist_sync.config import Config
from plex_playlist_sync.storage import Database


@pytest.fixture
def test_db():
    """Provides an isolated in-memory Database instance with migration v18 applied."""
    db = Database(":memory:")
    yield db
    db.close()


@pytest.fixture
def test_config(tmp_path: Path):
    """Provides a default all-in-one Config pointing to tmp_path."""
    return Config(
        plex_url="http://127.0.0.1:32400",
        plex_token="test-plex-token",
        data_dir=str(tmp_path),
        role="all-in-one",
        user_request_quota=10,
    )


@pytest.fixture
def seeded_users(test_db: Database):
    """Seeds admin and standard test users into the test database."""
    admin = test_db.upsert_user("admin-1", "admin_user", "admin@plex.tv", is_admin=True)
    alice = test_db.upsert_user("user-alice", "alice", "alice@plex.tv", is_admin=False)
    return {"admin": admin, "alice": alice}


def _auth_headers(user: dict[str, Any], test_db: Database, config: Config) -> dict[str, str]:
    """Generates an authenticated Bearer header for a given user."""
    secret = get_or_create_secret_key(data_dir=config.data_dir)
    token = create_session_token(
        user_id=user["id"],
        username=user["username"],
        is_admin=user["is_admin"],
        secret_key=secret,
    )
    test_db.create_session(token, user["id"], {"auth": "test"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app_and_client(test_db: Database, test_config: Config):
    """Creates a FastAPI test client with injected test database and config."""
    app = create_app(db=test_db, config=test_config)
    app.dependency_overrides[get_db] = lambda: test_db
    app.dependency_overrides[get_config] = lambda: test_config

    client = TestClient(app)
    return app, client


# =============================================================================
# 1. Database Schema Migration v18 & API Key Storage CRUD
# =============================================================================


def test_migration_v18_seeds_api_key(test_db: Database):
    """Test 1: Schema migration v18 creates api_key column and auto-seeds a 32-char hex key."""
    with test_db._lock:
        cur = test_db.conn.execute("PRAGMA table_info(general_settings);")
        columns = [row[1] for row in cur.fetchall()]
        assert "api_key" in columns, "Column 'api_key' must exist in general_settings"

        cur = test_db.conn.execute("SELECT api_key FROM general_settings WHERE id = 1;")
        row = cur.fetchone()
        assert row is not None
        api_key = row[0]
        assert api_key and isinstance(api_key, str)
        assert len(api_key) == 32, f"Seeded API key must be 32 characters, got '{api_key}'"

        cur = test_db.conn.execute("SELECT MAX(version) FROM schema_migrations;")
        migration_version = cur.fetchone()[0]
        assert migration_version >= 18


def test_validate_api_key_logic(test_db: Database):
    """Test 2: validate_api_key succeeds for matching key, rejects invalid/empty keys."""
    current_key = test_db.get_api_key()
    assert test_db.validate_api_key(current_key) is True
    assert test_db.validate_api_key(f" {current_key} ") is True  # Strips whitespace

    # Invalid cases
    assert test_db.validate_api_key("wrong_key_12345678901234567890") is False
    assert test_db.validate_api_key("") is False
    assert test_db.validate_api_key("   ") is False
    assert test_db.validate_api_key(None) is False


def test_regenerate_api_key(test_db: Database):
    """Tests regenerating the API key updates persistent storage and revokes old key."""
    old_key = test_db.get_api_key()
    new_key = test_db.regenerate_api_key()

    assert new_key != old_key
    assert len(new_key) == 32
    assert test_db.get_api_key() == new_key
    assert test_db.validate_api_key(new_key) is True
    assert test_db.validate_api_key(old_key) is False


# =============================================================================
# 2. Settings API Key Endpoints
# =============================================================================


def test_settings_api_key_endpoints(app_and_client, test_db: Database, test_config: Config, seeded_users):
    """Test 3: GET /api/settings/api-key and POST /api/settings/api-key/regenerate."""
    _, client = app_and_client
    admin_headers = _auth_headers(seeded_users["admin"], test_db, test_config)
    alice_headers = _auth_headers(seeded_users["alice"], test_db, test_config)

    # 1. Unauthenticated access rejected
    res = client.get("/api/settings/api-key")
    assert res.status_code == 401

    # 2. Non-admin access forbidden
    res = client.get("/api/settings/api-key", headers=alice_headers)
    assert res.status_code == 403

    # 3. Admin access gets current API key
    res = client.get("/api/settings/api-key", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert "api_key" in data
    original_key = data["api_key"]
    assert original_key == test_db.get_api_key()

    # 4. Admin regenerates key
    res = client.post("/api/settings/api-key/regenerate", headers=admin_headers)
    assert res.status_code == 200
    regen_data = res.json()
    assert "api_key" in regen_data
    assert regen_data["api_key"] != original_key
    assert "successfully regenerated" in regen_data["message"]

    # 5. Subsequent GET returns new key
    res = client.get("/api/settings/api-key", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["api_key"] == regen_data["api_key"]


# =============================================================================
# 3. Universal Machine Authentication (X-Api-Key)
# =============================================================================


def test_machine_auth_via_x_api_key(app_and_client, test_db: Database, test_config: Config):
    """Test 4: External access via X-Api-Key allows querying protected endpoints."""
    _, client = app_and_client
    api_key = test_db.get_api_key()

    # Access queue with X-Api-Key header
    res = client.get("/api/queue", headers={"X-Api-Key": api_key})
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # Access settings with X-Api-Key header (grants admin privileges)
    res = client.get("/api/settings/general", headers={"X-Api-Key": api_key})
    assert res.status_code == 200
    assert "application_url" in res.json()

    # Access via query parameters apikey and api_key
    res = client.get(f"/api/queue?apikey={api_key}")
    assert res.status_code == 200

    res = client.get(f"/api/queue?api_key={api_key}")
    assert res.status_code == 200

    # Invalid API key rejected with 401
    res = client.get("/api/queue", headers={"X-Api-Key": "invalid_bogus_key"})
    assert res.status_code == 401
    assert "Invalid API key" in res.json()["detail"]


def test_internal_token_auth(app_and_client, test_config: Config):
    """Tests machine authentication via X-Internal-Token and Authorization Bearer internal secret."""
    test_config.internal_core_secret = "super_internal_token_secret_12345"
    _, client = app_and_client

    # Access via X-Internal-Token
    res = client.get("/api/queue", headers={"X-Internal-Token": "super_internal_token_secret_12345"})
    assert res.status_code == 200

    # Access via Authorization Bearer
    res = client.get("/api/queue", headers={"Authorization": "Bearer super_internal_token_secret_12345"})
    assert res.status_code == 200

    # Invalid internal token rejected with 401
    res = client.get("/api/queue", headers={"X-Internal-Token": "wrong_secret"})
    assert res.status_code == 401


# =============================================================================
# 4. DMZ Role Isolation: Gateway Route Gating
# =============================================================================


def test_gateway_blocks_library_mutations(app_and_client, test_db: Database, test_config: Config, seeded_users):
    """Test 5: In ROLE=gateway, library mutation endpoints return HTTP 403 Forbidden."""
    test_config.role = "gateway"
    _, client = app_and_client
    admin_headers = _auth_headers(seeded_users["admin"], test_db, test_config)

    expected_detail = "Library management is restricted to TrackSeerr Core tier. Gateway tier cannot execute library mutations."

    # 1. POST /api/library/scan
    res = client.post("/api/library/scan", json={}, headers=admin_headers)
    assert res.status_code == 403
    assert res.json()["detail"] == expected_detail

    # 2. POST /api/library/scan/cancel
    res = client.post("/api/library/scan/cancel", headers=admin_headers)
    assert res.status_code == 403

    # 3. POST /api/library/migrate-lidarr
    res = client.post("/api/library/migrate-lidarr", json={}, headers=admin_headers)
    assert res.status_code == 403

    # 4. POST /api/library/manual-import/scan
    res = client.post("/api/library/manual-import/scan", json={}, headers=admin_headers)
    assert res.status_code == 403
    assert res.json()["detail"] == expected_detail

    # 5. POST /api/library/manual-import/commit
    res = client.post("/api/library/manual-import/commit", json={"items": []}, headers=admin_headers)
    assert res.status_code == 403

    # 6. POST /api/library/rename/preview
    res = client.post("/api/library/rename/preview", json={}, headers=admin_headers)
    assert res.status_code == 403

    # 7. POST /api/library/rename/apply
    res = client.post("/api/library/rename/apply", json={"file_ids": []}, headers=admin_headers)
    assert res.status_code == 403

    # 8. DELETE endpoints
    res = client.delete("/api/library/artists/artist-123", headers=admin_headers)
    assert res.status_code == 403
    assert res.json()["detail"] == expected_detail

    res = client.delete("/api/library/albums/album-123", headers=admin_headers)
    assert res.status_code == 403

    res = client.delete("/api/library/tracks/track-123", headers=admin_headers)
    assert res.status_code == 403

    res = client.delete("/api/library/files/file-123", headers=admin_headers)
    assert res.status_code == 403

    # 9. PUT monitoring endpoints
    res = client.put("/api/library/artists/artist-123/monitored", json={"monitored": False}, headers=admin_headers)
    assert res.status_code == 403

    res = client.put("/api/library/albums/album-123/monitored", json={"monitored": False}, headers=admin_headers)
    assert res.status_code == 403

    res = client.put("/api/library/tracks/track-123/monitored", json={"monitored": False}, headers=admin_headers)
    assert res.status_code == 403


def test_all_in_one_allows_library_mutations(app_and_client, test_db: Database, test_config: Config, seeded_users):
    """Verifies that in single-container mode (ROLE=all-in-one), mutations are NOT blocked by require_core_tier."""
    test_config.role = "all-in-one"
    _, client = app_and_client
    admin_headers = _auth_headers(seeded_users["admin"], test_db, test_config)

    # Calling scan endpoint does not yield 403
    res = client.post("/api/library/scan", json={}, headers=admin_headers)
    assert res.status_code != 403


# =============================================================================
# 5. Gateway Forwarding to Core (Availability & Requests)
# =============================================================================


def test_gateway_forwards_availability_to_core(app_and_client, test_db: Database, test_config: Config, seeded_users):
    """Test 6: In ROLE=gateway, GET /api/library/availability forwards query to Core using CoreClient."""
    test_config.role = "gateway"
    test_config.trackseerr_core_url = "http://mock-core:5250"
    test_config.internal_core_secret = "secret-gateway-token"

    _, client = app_and_client
    user_headers = _auth_headers(seeded_users["alice"], test_db, test_config)

    mock_core_response = {
        "in_library": True,
        "monitored": True,
        "status": "available",
        "quality": "FLAC 24bit",
        "file_count": 1,
        "track_count": 1,
    }

    with patch("httpx.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_instance

        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_core_response
        mock_resp.status_code = 200
        mock_instance.get.return_value = mock_resp

        res = client.get(
            "/api/library/availability?artist_name=Radiohead&album_title=OK+Computer",
            headers=user_headers,
        )

        assert res.status_code == 200
        assert res.json() == mock_core_response

        # Verify CoreClient called Core with expected URL, parameters, and secret header
        mock_instance.get.assert_called_once()
        call_args, call_kwargs = mock_instance.get.call_args
        assert call_args[0] == "http://mock-core:5250/api/library/availability"
        assert call_kwargs["params"] == {"artist_name": "Radiohead", "album_title": "OK Computer"}
        assert call_kwargs["headers"]["X-Internal-Token"] == "secret-gateway-token"


def test_gateway_forwards_request_creation_to_core(app_and_client, test_db: Database, test_config: Config, seeded_users):
    """Test 7: In ROLE=gateway, request creation forwards to mock Core server with X-Internal-Token."""
    test_config.role = "gateway"
    test_config.trackseerr_core_url = "http://mock-core:5250"
    test_config.internal_core_secret = "secret-gateway-token"

    _, client = app_and_client
    user_headers = _auth_headers(seeded_users["alice"], test_db, test_config)

    mock_created_response = {
        "id": "req-core-12345",
        "title": "Time",
        "artist": "Pink Floyd",
        "status": "pending",
    }

    with patch("httpx.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_instance

        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_created_response
        mock_resp.status_code = 201
        mock_instance.post.return_value = mock_resp

        payload = {
            "title": "Time",
            "artist": "Pink Floyd",
            "item_type": "track",
        }
        res = client.post("/api/requests", json=payload, headers=user_headers)

        assert res.status_code == 201
        assert res.json() == mock_created_response

        mock_instance.post.assert_called_once()
        call_args, call_kwargs = mock_instance.post.call_args
        assert call_args[0] == "http://mock-core:5250/api/requests"
        assert call_kwargs["json"]["title"] == "Time"
        assert call_kwargs["headers"]["X-Internal-Token"] == "secret-gateway-token"
        assert call_kwargs["headers"]["X-User-Id"] == "user-alice"


def test_gateway_forwards_batch_requests_and_deletion(app_and_client, test_db: Database, test_config: Config, seeded_users):
    """Tests forwarding of batch requests and request cancellation in gateway mode."""
    test_config.role = "gateway"
    test_config.trackseerr_core_url = "http://mock-core:5250"
    test_config.internal_core_secret = "secret-gateway-token"

    _, client = app_and_client
    user_headers = _auth_headers(seeded_users["alice"], test_db, test_config)

    with patch("httpx.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_instance

        # Test batch forwarding
        mock_batch_resp = MagicMock()
        mock_batch_resp.json.return_value = {"created": [{"id": "req-1"}], "total": 1}
        mock_batch_resp.status_code = 201
        mock_instance.post.return_value = mock_batch_resp

        res = client.post(
            "/api/requests/batch",
            json={"requests": [{"title": "Song A", "artist": "Artist A", "item_type": "track"}]},
            headers=user_headers,
        )
        assert res.status_code == 201

        # Test delete forwarding
        mock_del_resp = MagicMock()
        mock_del_resp.is_success = True
        mock_del_resp.status_code = 200
        mock_instance.delete.return_value = mock_del_resp

        res = client.delete("/api/requests/req-core-123", headers=user_headers)
        assert res.status_code == 200
        assert res.json() == {"status": "deleted", "id": "req-core-123"}


def test_gateway_unreachable_core_returns_502(app_and_client, test_db: Database, test_config: Config, seeded_users):
    """Tests that connection failure to Core returns HTTP 502 Bad Gateway with standard detail."""
    test_config.role = "gateway"
    test_config.trackseerr_core_url = "http://offline-core:5250"
    test_config.internal_core_secret = "secret-gateway-token"

    _, client = app_and_client
    user_headers = _auth_headers(seeded_users["alice"], test_db, test_config)

    with patch("httpx.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_instance
        mock_instance.post.side_effect = httpx.ConnectError("Connection refused")
        mock_instance.get.side_effect = httpx.ConnectError("Connection refused")

        # 1. Requests endpoint returns 502
        res = client.post(
            "/api/requests",
            json={"title": "Song", "artist": "Artist", "item_type": "track"},
            headers=user_headers,
        )
        assert res.status_code == 502
        assert "Unable to communicate with TrackSeerr Core engine" in res.json()["detail"]

        # 2. Availability endpoint returns 502
        res = client.get("/api/library/availability?artist_name=Artist", headers=user_headers)
        assert res.status_code == 502
        assert "Unable to communicate with TrackSeerr Core engine" in res.json()["detail"]


# =============================================================================
# 6. CoreClient Unit Tests & Config Env Parsing
# =============================================================================


def test_core_client_direct_unit():
    """Unit test for CoreClient request crafting, parameters, and headers."""
    client = CoreClient("http://localhost:5250/", secret="my-secret-123")
    assert client.core_url == "http://localhost:5250"

    headers = client._headers(user_info={"id": "usr-1", "username": "bob"})
    assert headers["X-Internal-Token"] == "my-secret-123"
    assert headers["X-Api-Key"] == "my-secret-123"
    assert headers["X-User-Id"] == "usr-1"
    assert headers["X-User-Name"] == "bob"


def test_config_dmz_from_env(monkeypatch: pytest.MonkeyPatch):
    """Tests Config.from_env() parsing of ROLE, TRACKSEERR_CORE_URL, and INTERNAL_CORE_SECRET."""
    monkeypatch.setenv("ROLE", "GATEWAY")
    monkeypatch.setenv("TRACKSEERR_CORE_URL", "https://core.internal:5250/")
    monkeypatch.setenv("INTERNAL_CORE_SECRET", "supersecret123")

    cfg = Config.from_env()
    assert cfg.role == "gateway"
    assert cfg.trackseerr_core_url == "https://core.internal:5250"
    assert cfg.internal_core_secret == "supersecret123"
