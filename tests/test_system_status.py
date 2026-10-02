"""Unit and integration tests for System Diagnostics & Telemetry API (/api/system/status)."""

import os
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from plex_playlist_sync.api.app import create_app
from plex_playlist_sync.api.dependencies import get_config, get_db, get_plex_client
from plex_playlist_sync.api.routes.system import (
    _get_db_metrics,
    _get_disk_metrics,
    _get_worker_statuses,
    _ping_download_clients,
    _ping_indexers,
    _ping_plex,
)
from plex_playlist_sync.auth import create_session_token, get_or_create_secret_key
from plex_playlist_sync.config import Config
from plex_playlist_sync.storage import Database


@pytest.fixture
def test_db():
    """Provides an isolated in-memory Database instance."""
    db = Database(":memory:")
    yield db
    db.close()


@pytest.fixture
def secret_key(tmp_path):
    """Provides a consistent secret key."""
    return get_or_create_secret_key(data_dir=str(tmp_path))


@pytest.fixture
def test_config(tmp_path):
    """Provides a test Config."""
    return Config(
        plex_url="http://127.0.0.1:32400",
        plex_token="test-plex-token",
        data_dir=str(tmp_path),
    )


@pytest.fixture
def app_and_client(test_db, test_config):
    """Creates a TestClient with injected DB and Config."""
    app = create_app(db=test_db, config=test_config)
    app.dependency_overrides[get_db] = lambda: test_db
    app.dependency_overrides[get_config] = lambda: test_config
    client = TestClient(app)
    return app, client


@pytest.fixture
def seeded_users(test_db):
    """Seeds admin and non-admin users in DB."""
    admin = test_db.upsert_user("admin-1", "admin_user", "admin@plex.tv", is_admin=True)
    alice = test_db.upsert_user("user-alice", "alice", "alice@plex.tv", is_admin=False)
    return {"admin": admin, "alice": alice}


def create_auth_cookies(test_db, user: dict, secret_key: bytes):
    token = create_session_token(
        user_id=user["id"],
        username=user["username"],
        is_admin=user["is_admin"],
        secret_key=secret_key,
    )
    test_db.create_session(session_id=token, user_id=user["id"])
    return {"session_token": token}


# =============================================================================
# RBAC Tests
# =============================================================================


def test_unauthenticated_system_status_forbidden(app_and_client):
    """Unauthenticated GET /api/system/status must return HTTP 401."""
    _, client = app_and_client
    resp = client.get("/api/system/status")
    assert resp.status_code == 401
    assert "Authentication required" in resp.json()["detail"]


def test_non_admin_system_status_forbidden(app_and_client, seeded_users, secret_key, test_db):
    """Non-admin user GET /api/system/status must return HTTP 403."""
    _, client = app_and_client
    cookies = create_auth_cookies(test_db, seeded_users["alice"], secret_key)
    resp = client.get("/api/system/status", cookies=cookies)
    assert resp.status_code == 403
    assert "Administrator access required" in resp.json()["detail"]


def test_admin_system_status_success(app_and_client, seeded_users, secret_key, test_db):
    """Admin GET /api/system/status returns 200 with full telemetry schema."""
    app, client = app_and_client
    mock_plex = MagicMock()
    mock_plex.test_connection.return_value = (True, "Connected to Plex Media Server")
    app.dependency_overrides[get_plex_client] = lambda: mock_plex

    cookies = create_auth_cookies(test_db, seeded_users["admin"], secret_key)
    resp = client.get("/api/system/status", cookies=cookies)
    assert resp.status_code == 200

    data = resp.json()
    # 1. Environment Status
    env = data["environment"]
    assert env["version"] == "1.0.0"
    assert "python_version" in env
    assert "platform" in env
    assert "role" in env
    assert isinstance(env["uptime_seconds"], (int, float))

    # 2. Storage metrics
    storage = data["storage"]
    assert isinstance(storage, list)
    assert len(storage) >= 1
    assert "path" in storage[0]
    assert "label" in storage[0]
    assert "percent_used" in storage[0]

    # 3. Database status
    db_stat = data["database"]
    assert db_stat["path"] == ":memory:"
    assert "sqlite_version" in db_stat
    assert "table_counts" in db_stat
    assert db_stat["table_counts"]["users"] >= 2

    # 4. Plex status
    plex = data["plex"]
    assert plex["configured"] is True
    assert plex["online"] is True
    assert "Connected to Plex" in plex["message"]

    # 5. Download clients and indexers
    assert isinstance(data["download_clients"], list)
    assert isinstance(data["indexers"], list)

    # 6. Workers
    workers = data["workers"]
    assert "acquisition_worker" in workers
    assert "lidarr_worker" in workers
    assert "sync_coordinator" in workers

    # Also verify the /api/system alias endpoint
    alias_resp = client.get("/api/system", cookies=cookies)
    assert alias_resp.status_code == 200
    assert alias_resp.json()["environment"]["version"] == "1.0.0"


# =============================================================================
# Unit Tests for Subsystems
# =============================================================================


def test_disk_metrics_handles_missing_paths(test_db, tmp_path):
    """Ensures _get_disk_metrics handles non-existent paths gracefully."""
    cfg = Config(
        plex_url="http://127.0.0.1:32400",
        plex_token="test-token",
        data_dir="/tmp/nonexistent_test_dir_12345/missing",
    )
    test_db.update_media_management_settings(
        {
            "root_folder_path": "/var/nonexistent_storage_9999/music",
            "staging_folder_path": "/var/nonexistent_storage_9999/downloads",
        }
    )

    metrics = _get_disk_metrics(cfg, test_db)
    assert isinstance(metrics, list)
    # Should at least resolve root /
    assert any(m.path == "/" for m in metrics)

    # Test error resilience when disk_usage raises OSError on all paths
    with patch("shutil.disk_usage", side_effect=OSError("Drive unmounted")):
        empty_metrics = _get_disk_metrics(cfg, test_db)
        assert empty_metrics == []


def test_db_metrics_with_file_and_memory(test_db, tmp_path):
    """Validates _get_db_metrics on memory DB and disk DB."""
    # 1. In-memory DB
    mem_stat = _get_db_metrics(test_db)
    assert mem_stat.path == ":memory:"
    assert mem_stat.size_bytes == 0
    assert "users" in mem_stat.table_counts

    # 2. File-based DB
    db_file = tmp_path / "sync_db.sqlite"
    file_db = Database(str(db_file))
    file_stat = _get_db_metrics(file_db)
    assert file_stat.path == str(db_file)
    assert file_stat.size_bytes > 0
    file_db.close()


def test_plex_offline_and_online(test_db, test_config):
    """Validates Plex ping handling when unconfigured, online, and offline."""
    # 1. Plex client is None (not configured)
    unconf = _ping_plex(None, test_config, test_db)
    assert unconf.configured is False
    assert unconf.online is False
    assert "Plex not configured" in unconf.message
    assert unconf.latency_ms is None

    # 2. Plex online
    mock_plex = MagicMock()
    mock_plex.test_connection.return_value = (True, "Connected to MyServer (v1.40.1)")
    online_stat = _ping_plex(mock_plex, test_config, test_db)
    assert online_stat.configured is True
    assert online_stat.online is True
    assert online_stat.latency_ms is not None
    assert "Connected to MyServer" in online_stat.message

    # 3. Plex offline with exception
    mock_plex.test_connection.side_effect = ConnectionError("Connection refused by Plex")
    offline_stat = _ping_plex(mock_plex, test_config, test_db)
    assert offline_stat.configured is True
    assert offline_stat.online is False
    assert offline_stat.latency_ms is None
    assert "Connection refused by Plex" in offline_stat.message

    # 4. Plex returning boolean
    mock_plex.test_connection.side_effect = None
    mock_plex.test_connection.return_value = False
    bool_stat = _ping_plex(mock_plex, test_config, test_db)
    assert bool_stat.configured is True
    assert bool_stat.online is False


def test_client_and_indexer_pings(test_db):
    """Validates disabled clients/indexers return disabled message without network call,

    and enabled ones return driver result, plus SSRF defense.
    """
    # 1. Seed Download Clients
    test_db.create_download_client(
        {
            "id": "c1",
            "name": "Disabled SLSKD",
            "driver_type": "slskd",
            "host_url": "http://127.0.0.1:5030",
            "enabled": False,
        }
    )
    test_db.create_download_client(
        {
            "id": "c2",
            "name": "Active SABnzbd",
            "driver_type": "sabnzbd",
            "host_url": "http://127.0.0.1:8080",
            "api_key": "sab-key",
            "enabled": True,
        }
    )
    test_db.create_download_client(
        {
            "id": "c3",
            "name": "SSRF Client",
            "driver_type": "slskd",
            "host_url": "http://169.254.169.254/latest/meta-data",
            "enabled": True,
        }
    )

    mock_driver = MagicMock()
    mock_driver.test_connection.return_value = (True, "Connected to SABnzbd")

    with patch(
        "plex_playlist_sync.api.routes.system.get_acquisition_driver",
        return_value=mock_driver,
    ) as mock_get_driver:
        client_results = _ping_download_clients(test_db)
        assert len(client_results) == 3

        # Disabled client:
        c1_res = next(c for c in client_results if c.id == "c1")
        assert c1_res.enabled is False
        assert c1_res.online is False
        assert c1_res.message == "Disabled in settings"

        # Enabled client:
        c2_res = next(c for c in client_results if c.id == "c2")
        assert c2_res.enabled is True
        assert c2_res.online is True
        assert c2_res.latency_ms is not None
        assert "Connected to SABnzbd" in c2_res.message

        # SSRF blocked client:
        c3_res = next(c for c in client_results if c.id == "c3")
        assert c3_res.enabled is True
        assert c3_res.online is False
        assert "SSRF defense" in c3_res.message

        # Factory should have only been called for c2 (not c1 or c3)
        assert mock_get_driver.call_count == 1

    # 2. Seed Indexers
    test_db.create_indexer(
        {
            "id": "idx1",
            "name": "Disabled Indexer",
            "indexer_type": "torznab",
            "host_url": "http://127.0.0.1:9696",
            "enabled": False,
        }
    )
    test_db.create_indexer(
        {
            "id": "idx2",
            "name": "Active Prowlarr",
            "indexer_type": "torznab",
            "host_url": "http://127.0.0.1:9696",
            "api_key": "prowl-key",
            "enabled": True,
        }
    )
    test_db.create_indexer(
        {
            "id": "idx3",
            "name": "SSRF Indexer",
            "indexer_type": "torznab",
            "host_url": "http://169.254.169.254/latest",
            "enabled": True,
        }
    )

    mock_idx_driver = MagicMock()
    mock_idx_driver.test_connection.return_value = (True, "Torznab caps OK")

    with patch(
        "plex_playlist_sync.api.routes.system.get_indexer_driver",
        return_value=mock_idx_driver,
    ) as mock_get_idx:
        indexer_results = _ping_indexers(test_db)
        assert len(indexer_results) == 3

        idx1_res = next(i for i in indexer_results if i.id == "idx1")
        assert idx1_res.enabled is False
        assert idx1_res.online is False
        assert idx1_res.message == "Disabled in settings"

        idx2_res = next(i for i in indexer_results if i.id == "idx2")
        assert idx2_res.enabled is True
        assert idx2_res.online is True
        assert idx2_res.latency_ms is not None
        assert "Torznab caps OK" in idx2_res.message

        idx3_res = next(i for i in indexer_results if i.id == "idx3")
        assert idx3_res.enabled is True
        assert idx3_res.online is False
        assert "SSRF defense" in idx3_res.message

        # Factory only called for idx2
        assert mock_get_idx.call_count == 1


def test_worker_statuses():
    """Validates _get_worker_statuses returns dicts for all 3 worker subsystems."""
    status = _get_worker_statuses()
    assert isinstance(status.acquisition_worker, dict)
    assert isinstance(status.lidarr_worker, dict)
    assert isinstance(status.sync_coordinator, dict)
    assert "running" in status.acquisition_worker
    assert "is_syncing" in status.sync_coordinator
