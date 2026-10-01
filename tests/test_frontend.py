"""Tests for Frontend Single-Page Dashboard & Static Assets (Phase 4)."""

import pytest
from fastapi.testclient import TestClient

from plex_playlist_sync.api.app import create_app
from plex_playlist_sync.api.dependencies import get_config, get_db
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
        spotify_client_id="sp-client-id",
        spotify_client_secret="sp-client-secret",
    )


@pytest.fixture
def client(test_db, test_config):
    """Creates a FastAPI test client configured with in-memory DB and test Config."""
    app = create_app(db=test_db, config=test_config)
    app.dependency_overrides[get_db] = lambda: test_db
    app.dependency_overrides[get_config] = lambda: test_config

    with TestClient(app) as test_client:
        yield test_client


class TestFrontendDashboard:
    """Validates root route serving and HTML structure."""

    def test_root_returns_200_and_index_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Plex Playlist Hub" in resp.text

    def test_root_contains_dashboard_elements(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text

        # Alpine.js state hook
        assert "plexHubApp()" in html
        assert "x-data" in html

        # Plex / Seerr dark styling and accents
        assert "#e5a00d" in html
        assert "bg-slate-950" in html

        # Key navigation & header elements
        assert "Plex Playlist Hub" in html
        assert "Live Sync Status" in html or "syncStatus" in html

        # Modals & drawers
        assert "Add Playlist" in html
        assert "Unmatched Tracks" in html or "Missing Tracks" in html
        assert "Sync Engine Live Console" in html or "terminal-console" in html

        # PIN auth flow elements
        assert "Sign In with Plex" in html
        assert "plex.tv" in html

        # Target toggling and CSV export
        assert "target-pill" in html or "toggleUserTarget" in html
        assert "Export Safe CSV" in html

        # Keyless Spotify & Multi-tab Import Features
        assert "By Link" in html
        assert "Paste Tracks" in html
        assert "1-Click Helper" in html
        assert "No Spotify API Key Needed" in html
        assert "Send to Plexamp" in html
        assert "Import to Plexamp" in html


class TestStaticAssets:
    """Validates that JavaScript, CSS, and asset files are served correctly."""

    def test_static_app_js_served(self, client):
        resp = client.get("/static/app.js")
        assert resp.status_code == 200
        content_type = resp.headers.get("content-type", "")
        assert "javascript" in content_type or "text/plain" in content_type
        assert "plexHubApp" in resp.text
        assert "api/sync/stream" in resp.text
        assert "api/auth/plex/pin" in resp.text
        assert "api/missing/csv" in resp.text
        assert "api/playlists/import" in resp.text
        assert "parseImportText" in resp.text
        assert "pasteFromClipboard" in resp.text
        assert "getBookmarkletHref" in resp.text
        assert "checkHashImport" in resp.text

    def test_static_style_css_served(self, client):
        resp = client.get("/static/style.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers.get("content-type", "")
        assert "#e5a00d" in resp.text
        assert "glass-panel" in resp.text
        assert "terminal-console" in resp.text

    def test_static_placeholder_svg_served(self, client):
        resp = client.get("/static/placeholder.svg")
        assert resp.status_code == 200
        assert "svg" in resp.headers.get("content-type", "")


class TestContentSecurityPolicy:
    """Validates CSP header allows CDN scripts, Google Fonts, and external artwork."""

    def test_csp_header_values(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

        csp = resp.headers.get("Content-Security-Policy", "")
        assert csp, "Content-Security-Policy header is missing"

        # Default self
        assert "default-src 'self'" in csp

        # Scripts: self, eval, inline, tailwindcdn, unpkg, jsdelivr
        assert "script-src 'self' 'unsafe-eval' 'unsafe-inline'" in csp
        assert "https://cdn.tailwindcss.com" in csp
        assert "https://unpkg.com" in csp
        assert "https://cdn.jsdelivr.net" in csp

        # Styles: self, inline, google fonts
        assert "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com" in csp

        # Fonts: self, gstatic
        assert "font-src 'self' https://fonts.gstatic.com" in csp

        # Images: self, data:, https: (for Spotify/Deezer artwork)
        assert "img-src 'self' data: https:" in csp

        # Connections: self (SSE and API)
        assert "connect-src 'self'" in csp

        # Frame ancestors: none
        assert "frame-ancestors 'none'" in csp

    def test_csp_header_on_api_endpoints(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp
