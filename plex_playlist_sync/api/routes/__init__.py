"""API routes package."""

from plex_playlist_sync.api.routes import (
    auth,
    discovery,
    download_clients,
    indexers,
    missing,
    playlists,
    queue,
    requests,
    settings,
    sync,
    users,
)

__all__ = [
    "auth",
    "discovery",
    "download_clients",
    "indexers",
    "missing",
    "playlists",
    "queue",
    "requests",
    "settings",
    "sync",
    "users",
]

