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
  - *Read the full [Spotify Import & Keyless Sync Guide](docs/SPOTIFY_IMPORT_GUIDE.md) for step-by-step instructions.*
- **Lidarr Integration & Self-Healing Missing Tracks**:
  - Automatically track songs in synchronized or imported playlists that are missing from your local Plex Music Library.
  - **Direct Lidarr Push & Paced Trickle**: Monitor artists and trigger targeted album searches directly from the web dashboard or paced via background trickle worker.
  - **Automated Feeds**: Expose missing tracks to universal RSS 2.0 feeds or plain text lists for external download automation.
  - **Self-Healing Webhook Loop**: When Lidarr downloads and Plex indexes a missing song, a webhook ping automatically injects the track into the user's Plexamp playlist and clears it from missing tracks!
  - *Read the full [Lidarr Integration & Automation Guide](docs/LIDARR_AND_AUTOMATION_GUIDE.md) for step-by-step instructions.*
- **Spotify Integration**:
  - Automatic dynamic pagination across all user-owned and followed playlists (no 50-item limit).
  - Explicit playlist syncing via Spotify URLs, Spotify URIs, or IDs.
  - Built-in retry backoff handling for Spotify API rate limits (HTTP 429) and gateway errors.
- **Deezer Integration**:
  - Full sync for Deezer user profiles and numerical playlist IDs using modern HTTPX models.
- **Match Memory & Manual Correction Picker**:
  - Search your Plex music library directly from unmatched track rows and manually link songs.
  - Automatically records pairings in **Match Memory** (`match_overrides`), permanently overriding fuzzy matching across all future sync cycles.
  - View and delete stored overrides at any time from the web dashboard.
- **Featured Charts Catalog**:
  - 1-click subscription to popular curated music charts (Billboard Hot 100, Today's Top Hits, Viral 50, Rock Classics, Chill Hits, Deezer Top Worldwide) without searching or copying URLs.
- **Local Smart Mixes**:
  - Dynamically generate Plexamp-style smart playlists directly from your local Plex listening history (*Heavy Rotation*, *Forgotten Favorites*, *Deep Cuts*).
- **Direct `.m3u` / `.m3u8` File Drag-and-Drop**:
  - Drag and drop legacy playlist files from Winamp, iTunes, foobar2000, or exported audio players.
  - Robust parser supporting extended `#EXTINF` metadata attributes, duration, and path normalization.
- **Per-Playlist Active / Paused Toggles**:
  - Pause auto-synchronization for individual playlists with one click without deleting them. Existing tracks remain static in Plexamp until re-enabled.
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

## Quick Start

### Unraid Deployment (Instant Template)

Installing on Unraid takes less than 2 minutes. Open your Unraid Terminal (`>_` icon in the top right menu) and run:

```bash
curl -o /boot/config/plugins/dockerMan/templates-user/my-plex-playlist-hub.xml \
  https://raw.githubusercontent.com/RonFBurgundy/plex-playlist-hub/main/unraid/plex-playlist-hub.xml
```

Then navigate to **Docker** &rarr; **Add Container** &rarr; select **my-plex-playlist-hub** from the **Template** dropdown, verify your Plex LAN IP address, and click **Apply**!

> [!TIP]
> *Read the complete, human-friendly [Unraid Installation Guide](docs/UNRAID_INSTALL_GUIDE.md) for step-by-step walkthroughs, token tips, and troubleshooting.*

---

### Docker Compose

```yaml
services:
  plex-playlist-hub:
    image: ghcr.io/ronfburgundy/plex-playlist-hub:latest
    container_name: plex-playlist-hub
    restart: unless-stopped
    ports:
      - "5250:5250"
    volumes:
      - ./data:/data
    environment:
      - PUID=1000
      - PGID=1000
      - PORT=5250
      # Use your Plex server's local LAN IP (do NOT use localhost inside Docker bridge)
      - PLEX_URL=http://192.168.1.100:32400
      - PLEX_TOKEN=your_plex_token_here
      - PLEX_MUSIC_SECTION=Music
      - PLEX_VERIFY_SSL=1
      - SECONDS_TO_WAIT=14400 # 4 hours
      - LOG_LEVEL=INFO
      # Spotify: Leave blank to use the built-in KEYLESS web scraper!
      - SPOTIFY_CLIENT_ID=
      - SPOTIFY_CLIENT_SECRET=
      # Optional: Lidarr integration & automated trickle
      # - LIDARR_URL=http://192.168.1.100:8686
      # - LIDARR_API_KEY=your_lidarr_api_key
      # - LIDARR_TRICKLE_RATE_SECONDS=3.0
      # - LIDARR_TRICKLE_BATCH_SIZE=25
      # - LIDARR_AUTO_TRICKLE=0
      # - FEED_TOKEN=my-secure-token
```

Run with:
```bash
docker compose up -d
```

Access the web dashboard in your browser at: `http://<your-server-ip>:5250`

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
| `LIDARR_URL` | *Optional* | Base URL of Lidarr server (e.g. `http://192.168.1.100:8686`) |
| `LIDARR_API_KEY` | *Optional* | Lidarr API Key |
| `LIDARR_AUTO_SEARCH` | `1` | Automatically trigger interactive search when pushing to Lidarr |
| `LIDARR_TRICKLE_RATE_SECONDS` | `3.0` | Delay between artist lookups in seconds during background trickle push |
| `LIDARR_TRICKLE_BATCH_SIZE` | `25` | Number of missing tracks pushed per manual batch or scheduled drip |
| `LIDARR_AUTO_TRICKLE` | `0` | Set to `1` to enable scheduled automated background drip |
| `LIDARR_AUTO_TRICKLE_INTERVAL_MINUTES` | `30` | Interval in minutes between automated drip runs |
| `LIDARR_ROOT_FOLDER` | *Auto* | Custom Lidarr root folder path |
| `LIDARR_QUALITY_PROFILE_ID` | *Auto* | Custom Lidarr quality profile ID |
| `LIDARR_METADATA_PROFILE_ID` | *Auto* | Custom Lidarr metadata profile ID |
| `FEED_TOKEN` | *Optional* | Secret token protecting RSS feeds, plain text lists, and webhooks |

---

## Security Policy

Security is a foundational design principle of Plex Playlist Hub. See [SECURITY.md](SECURITY.md) for details on our threat model, SSRF defenses, and vulnerability reporting process.

---

## License

GNU General Public License v3 (GPL-3.0). See [LICENSE.md](LICENSE.md) for details.
