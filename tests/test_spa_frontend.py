"""Tests for Modern React + Vite Single Page Application Integration."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from plex_playlist_sync.api.app import create_app
from plex_playlist_sync.config import Config
from plex_playlist_sync.storage import Database


@pytest.fixture
def memory_db():
    db = Database(":memory:")
    yield db
    db.close()


@pytest.fixture
def mock_config(tmp_path):
    return Config(
        plex_url="http://127.0.0.1:32400",
        plex_token="test-token",
        data_dir=str(tmp_path),
    )


class TestSPAFastAPIIntegration:
    """Verifies that FastAPI correctly serves the Vite-built React SPA."""

    def test_app_mounts_assets_when_dist_exists(self, memory_db, mock_config):
        app = create_app(db=memory_db, config=mock_config)
        mounted_routes = [getattr(route, "path", None) for route in app.routes]
        assert "/assets" in mounted_routes

    def test_spa_index_served_when_legacy_env_is_disabled(self, memory_db, mock_config):
        with patch.dict(os.environ, {"TRACKSEERR_LEGACY_UI": "0"}):
            app = create_app(db=memory_db, config=mock_config)
            with TestClient(app) as client:
                resp = client.get("/")
                assert resp.status_code == 200
                assert "text/html" in resp.headers.get("content-type", "")
                html = resp.text

                # React root mount element
                assert '<div id="root"></div>' in html
                # Vite script tag
                assert "src=\"/assets/" in html or 'type="module"' in html
                # Brand and meta tags
                assert "TrackSeerr" in html
                assert 'name="theme-color" content="#0a0a0a"' in html
                assert 'rel="manifest"' in html

    def test_legacy_index_served_when_legacy_env_is_enabled(self, memory_db, mock_config):
        with patch.dict(os.environ, {"TRACKSEERR_LEGACY_UI": "1"}):
            app = create_app(db=memory_db, config=mock_config)
            with TestClient(app) as client:
                resp = client.get("/")
                assert resp.status_code == 200
                html = resp.text
                assert "plexHubApp()" in html
                assert "x-data" in html

    def test_fallback_to_static_when_dist_index_missing(self, memory_db, mock_config):
        with patch.dict(os.environ, {"TRACKSEERR_LEGACY_UI": "0"}):
            original_is_file = Path.is_file

            def mock_is_file(self):
                if "dist" in str(self) and self.name == "index.html":
                    return False
                return original_is_file(self)

            with patch.object(Path, "is_file", mock_is_file):
                app = create_app(db=memory_db, config=mock_config)
                with TestClient(app) as client:
                    resp = client.get("/")
                    assert resp.status_code == 200
                    assert "plexHubApp()" in resp.text

    def test_public_pwa_assets_served_at_root(self, memory_db, mock_config):
        with patch.dict(os.environ, {"TRACKSEERR_LEGACY_UI": "0"}):
            app = create_app(db=memory_db, config=mock_config)
            with TestClient(app) as client:
                resp_manifest = client.get("/manifest.json")
                assert resp_manifest.status_code == 200
                assert "TrackSeerr" in resp_manifest.text

                resp_favicon = client.get("/favicon.svg")
                assert resp_favicon.status_code == 200

                resp_logo = client.get("/trackseerr-logo.svg")
                assert resp_logo.status_code == 200

    def test_static_assets_chunk_served(self, memory_db, mock_config):
        dist_assets = Path("frontend/dist/assets")
        if dist_assets.is_dir():
            js_files = list(dist_assets.glob("*.js"))
            if js_files:
                target_chunk = js_files[0].name
                app = create_app(db=memory_db, config=mock_config)
                with TestClient(app) as client:
                    resp = client.get(f"/assets/{target_chunk}")
                    assert resp.status_code == 200
                    assert len(resp.content) > 0
