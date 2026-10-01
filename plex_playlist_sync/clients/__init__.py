"""Clients package for Plex, Spotify, and Deezer."""

from .deezer import DeezerClient
from .plex import PlexClient
from .spotify import SpotifyClient

__all__ = ["PlexClient", "SpotifyClient", "DeezerClient"]
