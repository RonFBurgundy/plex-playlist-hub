"""Unit and integration tests for Media Management settings, permissions, and live preview API."""

import pytest
from fastapi.testclient import TestClient

from plex_playlist_sync.api.app import create_app
from plex_playlist_sync.api.dependencies import get_config, get_db
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
def test_config(tmp_path):
    """Provides a test Config pointing to tmp_path."""
    return Config(
        plex_url="http://127.0.0.1:32400",
        plex_token="test-plex-token",
        data_dir=str(tmp_path),
    )


@pytest.fixture
def seeded_users(test_db):
    """Seeds admin and regular users into test DB."""
    admin = test_db.upsert_user("admin-1", "admin_user", "admin@plex.tv", is_admin=True)
    alice = test_db.upsert_user("user-alice", "alice", "alice@plex.tv", is_admin=False)
    return {"admin": admin, "alice": alice}


@pytest.fixture
def app_and_client(test_db, test_config):
    """Creates a FastAPI test client with injected test database and config."""
    app = create_app(db=test_db, config=test_config)
    app.dependency_overrides[get_db] = lambda: test_db
    app.dependency_overrides[get_config] = lambda: test_config

    client = TestClient(app)
    return app, client


def _auth_headers(user: dict, test_db: Database, config: Config) -> dict[str, str]:
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


class TestMediaManagementStorage:
    """Validates DB migration v7 and CRUD operations."""

    def test_default_settings_initialized(self, test_db):
        settings = test_db.get_media_management_settings()
        assert settings["artist_folder_format"] == "{Artist Name}"
        assert settings["album_folder_format"] == "{Album Title} ({Release Year}){[ - Album Type]}"
        assert settings["standard_track_format"] == "{track:00} - {Track Title}{[ (Quality Full)]}"
        assert settings["compilation_track_format"] == "{track:00} - {Artist Name} - {Track Title}{[ (Quality Full)]}"
        assert settings["multi_disc_folder_format"] == "{Medium Format} {medium:00}"
        assert settings["root_folder_path"] == "/music"
        assert settings["colon_replacement_format"] == " - "
        assert settings["clean_artist_names"] is True

    def test_update_settings_partial_and_full(self, test_db):
        updated = test_db.update_media_management_settings({
            "artist_folder_format": "{Artist CleanName}",
            "clean_artist_names": False,
            "colon_replacement_format": "_",
        })
        assert updated["artist_folder_format"] == "{Artist CleanName}"
        assert updated["clean_artist_names"] is False
        assert updated["colon_replacement_format"] == "_"
        # Unchanged fields remain intact
        assert updated["root_folder_path"] == "/music"

        # Verify persistence on subsequent fetch
        fetched = test_db.get_media_management_settings()
        assert fetched["artist_folder_format"] == "{Artist CleanName}"
        assert fetched["clean_artist_names"] is False


class TestMediaManagementAPI:
    """Validates API endpoints, permission checks, and live preview rendering."""

    def test_unauthenticated_access_rejected(self, app_and_client):
        _, client = app_and_client
        resp = client.get("/api/settings/media-management")
        assert resp.status_code == 401

        resp_preview = client.post("/api/settings/media-management/preview", json={})
        assert resp_preview.status_code == 401

    def test_regular_user_can_get_settings_and_presets(self, app_and_client, test_db, test_config, seeded_users):
        _, client = app_and_client
        headers = _auth_headers(seeded_users["alice"], test_db, test_config)

        resp = client.get("/api/settings/media-management", headers=headers)
        assert resp.status_code == 200
        data = resp.json()

        assert "settings" in data
        assert data["settings"]["artist_folder_format"] == "{Artist Name}"
        assert "presets" in data
        assert "Lidarr Standard" in data["presets"]
        assert "Clean Minimal" in data["presets"]
        assert "Audiophile / Detailed" in data["presets"]

    def test_non_admin_cannot_update_settings_forbidden(self, app_and_client, test_db, test_config, seeded_users):
        _, client = app_and_client
        headers = _auth_headers(seeded_users["alice"], test_db, test_config)

        payload = {"artist_folder_format": "{Artist CleanName}"}
        resp = client.post("/api/settings/media-management", json=payload, headers=headers)
        assert resp.status_code == 403
        assert "Administrator access required" in resp.json()["detail"]

    def test_admin_can_update_settings(self, app_and_client, test_db, test_config, seeded_users):
        _, client = app_and_client
        admin_headers = _auth_headers(seeded_users["admin"], test_db, test_config)

        payload = {
            "root_folder_path": "/data/music",
            "colon_replacement_format": "_",
            "clean_artist_names": False,
        }
        resp = client.post("/api/settings/media-management", json=payload, headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["root_folder_path"] == "/data/music"
        assert data["colon_replacement_format"] == "_"
        assert data["clean_artist_names"] is False

        # Verify DB persisted
        db_settings = test_db.get_media_management_settings()
        assert db_settings["root_folder_path"] == "/data/music"

    def test_live_preview_renders_valid_paths(self, app_and_client, test_db, test_config, seeded_users):
        _, client = app_and_client
        headers = _auth_headers(seeded_users["alice"], test_db, test_config)

        resp = client.post("/api/settings/media-management/preview", json={}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "previews" in data
        assert len(data["previews"]) == 3

        previews_by_id = {p["id"]: p for p in data["previews"]}

        # 1. Standard single disc
        std = previews_by_id["standard"]
        assert std["name"] == "Standard Single-Disc Track"
        assert std["output_path"] == "/music/Pink Floyd/The Dark Side of the Moon (1973)/01 - Speak to Me (FLAC 24bit 96kHz).flac"

        # 2. Multi-disc track
        multi = previews_by_id["multi_disc"]
        assert multi["name"] == "Multi-Disc Track (Disc 2)"
        assert multi["output_path"] == "/music/The Beatles/The Beatles (White Album) (1968)/CD 02/01 - Revolution 1 (FLAC 16bit 44.1kHz).flac"

        # 3. Compilation track
        comp = previews_by_id["compilation"]
        assert comp["name"] == "Compilation / Various Artists Track"
        assert comp["output_path"] == "/music/Various Artists/Wayne's World - Music from the Motion Picture (1992) - Soundtrack/01 - Queen - Bohemian Rhapsody (MP3 320kbps).mp3"

    def test_live_preview_with_custom_template_overrides(self, app_and_client, test_db, test_config, seeded_users):
        _, client = app_and_client
        headers = _auth_headers(seeded_users["alice"], test_db, test_config)

        custom_override = {
            "root_folder_path": "/library",
            "standard_track_format": "{track:0} {Track Title}",
        }
        resp = client.post("/api/settings/media-management/preview", json=custom_override, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        previews_by_id = {p["id"]: p for p in data["previews"]}

        std = previews_by_id["standard"]
        assert std["output_path"] == "/library/Pink Floyd/The Dark Side of the Moon (1973)/1 Speak to Me.flac"
