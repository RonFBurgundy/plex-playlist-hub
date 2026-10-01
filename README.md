# Plex Playlist Hub

[![CI](https://github.com/RonFBurgundy/plex-playlist-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/RonFBurgundy/plex-playlist-hub/actions/workflows/ci.yml)
[![Docker](https://github.com/RonFBurgundy/plex-playlist-hub/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/RonFBurgundy/plex-playlist-hub/actions/workflows/docker-publish.yml)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE.md)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![Status: Work in Progress](https://img.shields.io/badge/status-active%20development-orange.svg)](#roadmap)

> [!NOTE]
> **Active Development / Work in Progress**: Plex Playlist Hub is currently undergoing active development. The multi-user control hub, Plex OAuth authentication, and web dashboard are being actively built and hardened.

---

## Overview

**Plex Playlist Hub** is a self-hosted, multi-user playlist management and synchronization platform for your local **Plex Media Server** and **Plexamp**. It allows server administrators and Plex Home users to seamlessly import, manage, and synchronize playlists from **Spotify** and **Deezer** directly into their personal Plex profiles.

> [!IMPORTANT]
> This tool matches existing tracks within your local Plex music library. It **does not** download or scrape audio files from third-party services.

---

## Lineage & Acknowledgments

Plex Playlist Hub was originally conceived from [rnagabhyrava/plex-playlist-sync](https://github.com/rnagabhyrava/plex-playlist-sync). We extend our sincere gratitude to the original author for the foundational playlist matching concept. 

This project has been completely re-architected and rewritten from the ground up as an independent, multi-user web application with modern security controls, dynamic target routing, and Plex OAuth support.

---

## Key Features

- **Multi-User Plex Home Routing**:
  - Dynamically share playlists with specific individual users, groups, or the entire household (e.g. *Today's Top Hits* &rarr; Ron & Sarah; *Disney Singalongs* &rarr; Kids).
  - Syncs directly into individual user libraries so playlists render natively in **Plexamp**.
- **Zero Spotify API Key Required (Keyless Scraper)**:
  - Synchronize public Spotify playlists with zero developer credentials or API registration.
  - Automatically falls back to built-in SSR web scraper when `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` are omitted.
- **Personal & Private Playlist Transfer**:
  - Non-technical Plex Home users can import their private playlists, personal mixes, and *Liked Songs*.
  - **1-Click Browser Bookmarklet Helper**: Drag the bookmarklet into your browser, click it on Spotify Web Player, and transfer playlists directly into Plexamp with one click.
  - **Clipboard & Text Parsing**: Paste track lists, table rows, or `Artist - Title` lines with automatic format recognition.
- **Spotify Integration**:
  - Automatic dynamic pagination across all user-owned and followed playlists (no 50-item limit).
  - Explicit playlist syncing via Spotify URLs, Spotify URIs, or IDs.
  - Built-in retry backoff handling for Spotify API rate limits (HTTP 429) and gateway errors.
- **Deezer Integration**:
  - Full sync for Deezer user profiles and numerical playlist IDs using modern HTTPX models.
- **Smart Track Matching**:
  - Multi-tier matching (exact title & artist fuzzy comparison).
  - Automated title sanitization for fallback searching (cleans remaster tags, deluxe edition brackets, and feature tags).
  - Configurable similarity threshold (`SEARCH_SIMILARITY_THRESHOLD`).
- **Security-First Architecture**:
  - Zero execution seams: strictly zero subprocess or shell commands executed from API routes.
  - Strict SSRF defense: user-supplied links are validated against whitelist regexes and converted to pure IDs before API calls.
  - Path traversal containment for all export paths.
  - Parameterized SQLite persistence with foreign key cascades.
  - Non-root Docker container (`uid 1000`).
- **Flexible Execution Modes**:
  - **Web Dashboard**: Interactive management hub on port `5250`.
  - **Daemon / Cron Mode**: Runs continuous background sync loops or single-pass scheduled syncs (`RUN_ONCE=1`).

---

## Quick Start with Docker

### Docker Compose (Recommended)

```yaml
services:
  playlistHub:
    image: ghcr.io/ronfburgundy/plex-playlist-hub:latest
    container_name: playlistHub
    restart: unless-stopped
    ports:
      - "5250:5250"
    volumes:
      - ./data:/data
    environment:
      - PORT=5250
      - PLEX_URL=http://192.168.1.100:32400
      - PLEX_TOKEN=your_plex_token_here
      - PLEX_VERIFY_SSL=1
      - SECONDS_TO_WAIT=86400
      - RUN_ONCE=0
      - APPEND_SERVICE_SUFFIX=1
      - ADD_PLAYLIST_POSTER=1
      - ADD_PLAYLIST_DESCRIPTION=1
      - WRITE_MISSING_AS_CSV=0
      - SPOTIFY_CLIENT_ID=your_spotify_client_id
      - SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
      - SPOTIFY_USER_ID=your_spotify_user_id
```

Run with:
```bash
docker compose up -d
```

Access the hub in your browser at: `http://<your-server-ip>:5250`

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `PORT` | `5250` | Port for the web service |
| `PLEX_URL` | *Required* | Base URL to your Plex Media Server |
| `PLEX_TOKEN` | *Required* | Plex authentication token ([Find your token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)) |
| `PLEX_VERIFY_SSL` | `1` | Set to `0` or `false` to disable SSL certificate checks (self-signed certs) |
| `RUN_ONCE` / `CRON` | `0` | Set to `1` to run a single sync cycle and exit |
| `SECONDS_TO_WAIT` | `86400` | Wait duration in seconds between background sync cycles |
| `APPEND_SERVICE_SUFFIX` | `1` | Append ` - Spotify` or ` - Deezer` to synced playlist titles |
| `ADD_PLAYLIST_POSTER` | `1` | Synchronize playlist cover posters to Plex |
| `ADD_PLAYLIST_DESCRIPTION` | `1` | Synchronize playlist descriptions/summaries to Plex |
| `APPEND_INSTEAD_OF_SYNC` | `0` | `0` = sync/mirror playlist; `1` = append tracks only |
| `WRITE_MISSING_AS_CSV` | `0` | Write missing track CSV reports to `/data` |
| `SEARCH_SIMILARITY_THRESHOLD` | `0.9` | Fuzzy match ratio (0.0 to 1.0) for artist/album titles |
| `LOG_LEVEL` | `INFO` | Log verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `SPOTIFY_CLIENT_ID` | *Optional* | Spotify Developer Client ID |
| `SPOTIFY_CLIENT_SECRET` | *Optional* | Spotify Developer Client Secret |
| `SPOTIFY_USER_ID` | *Optional* | Spotify user profile ID |
| `SPOTIFY_PLAYLIST_ID` | *Optional* | Space- or comma-separated list of Spotify playlist IDs, URLs, or URIs |
| `DEEZER_USER_ID` | *Optional* | Deezer numerical user ID |
| `DEEZER_PLAYLIST_ID` | *Optional* | Space- or comma-separated list of Deezer playlist IDs |

---

## Security Policy

Security is a foundational design principle of Plex Playlist Hub. See [SECURITY.md](SECURITY.md) for details on our threat model, SSRF defenses, and vulnerability reporting process.

---

## License

GNU General Public License v3 (GPL-3.0). See [LICENSE.md](LICENSE.md) for details.
