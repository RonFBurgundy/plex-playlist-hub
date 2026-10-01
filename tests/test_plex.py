from pathlib import Path
from unittest.mock import MagicMock, patch

from plexapi.exceptions import NotFound

from plex_playlist_sync.clients.plex import PlexClient, clean_title
from plex_playlist_sync.models import Playlist, Track


def test_clean_title():
    assert clean_title("Bohemian Rhapsody (2011 Remaster)") == "Bohemian Rhapsody"
    assert clean_title("Song Name (feat. Drake)") == "Song Name"
    assert clean_title("Hotel California - Remastered 2013") == "Hotel California"
    assert clean_title("Comfortably Numb [Deluxe Edition]") == "Comfortably Numb"
    assert clean_title("Clean Title") == "Clean Title"


class MockArtist:
    def __init__(self, title):
        self.title = title


class MockAlbum:
    def __init__(self, title):
        self.title = title


class MockPlexTrack:
    def __init__(self, title, artist, album):
        self.title = title
        self._artist = MockArtist(artist)
        self._album = MockAlbum(album)

    def artist(self):
        return self._artist

    def album(self):
        return self._album


@patch("plex_playlist_sync.clients.plex.PlexServer")
def test_plex_client_ssl_verification(mock_server):
    # Verify SSL True
    PlexClient("https://plex.example.com", "token", verify_ssl=True)
    session_arg = mock_server.call_args[1].get("session")
    assert session_arg.verify is True

    # Verify SSL False
    PlexClient("https://plex.example.com", "token", verify_ssl=False)
    session_arg2 = mock_server.call_args[1].get("session")
    assert session_arg2.verify is False


@patch("plex_playlist_sync.clients.plex.PlexServer")
def test_match_track_direct(mock_server):
    client = PlexClient("http://localhost:32400", "token")
    mock_track = MockPlexTrack("Karma Police", "Radiohead", "OK Computer")
    client.server.search.return_value = [mock_track]

    t = Track(title="Karma Police", artist="Radiohead", album="OK Computer")
    matched = client.match_track(t)
    assert matched is mock_track


@patch("plex_playlist_sync.clients.plex.PlexServer")
def test_match_track_fallback_cleaned_title(mock_server):
    client = PlexClient("http://localhost:32400", "token")
    mock_track = MockPlexTrack("Karma Police", "Radiohead", "OK Computer")
    # First search fails, second search (cleaned title) returns match
    client.server.search.side_effect = [[], [mock_track]]

    t = Track(title="Karma Police (2017 Remaster)", artist="Radiohead", album="OK Computer")
    matched = client.match_track(t)
    assert matched is mock_track
    assert client.server.search.call_count == 2


@patch("plex_playlist_sync.clients.plex.PlexServer")
def test_sync_playlist_creates_new(mock_server, tmp_path):
    client = PlexClient("http://localhost:32400", "token")
    mock_track = MockPlexTrack("Song 1", "Artist 1", "Album 1")
    client.server.search.return_value = [mock_track]

    # Playlist doesn't exist initially
    client.server.playlist.side_effect = [NotFound("Not found"), MagicMock()]

    playlist = Playlist(
        id="p1",
        name="Test Playlist",
        description="A great test playlist",
        poster="http://img.com/p.jpg",
        tracks=[Track("Song 1", "Artist 1", "Album 1")],
    )

    result = client.sync_playlist(playlist, data_dir=str(tmp_path))
    assert result.success is True
    assert result.matched_tracks == 1
    assert result.missing_tracks == 0
    client.server.createPlaylist.assert_called_once()


@patch("plex_playlist_sync.clients.plex.PlexServer")
def test_sync_playlist_missing_tracks_csv(mock_server, tmp_path):
    client = PlexClient("http://localhost:32400", "token")
    # No matches found
    client.server.search.return_value = []

    playlist = Playlist(
        id="p1",
        name="Missing Only",
        tracks=[Track("Missing Song", "Unknown Artist", "Unknown Album", "http://spotify.com/1")],
    )

    result = client.sync_playlist(playlist, write_missing_as_csv=True, data_dir=str(tmp_path))
    assert result.success is False
    assert result.missing_tracks == 1

    csv_file = tmp_path / "Missing Only.csv"
    assert csv_file.exists()
    content = csv_file.read_text()
    assert "Missing Song" in content
