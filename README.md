# Plex Playlist Sync

Synchronize Spotify and Deezer playlists with your local Plex Media Server using existing audio tracks in your library.

> [!NOTE]
> This tool matches and manages playlists in your Plex server against songs already present in your music library. It does not download music files from third-party services.

---

## Key Features

- **Spotify Synchronization**:
  - Automatically fetches all playlists for a Spotify user account with **full dynamic pagination** (no 50-playlist limit).
  - Sync specific curated, public, or shared playlists via `SPOTIFY_PLAYLIST_ID` (supports playlist IDs, URLs, and Spotify URIs).
  - Built-in retry backoff handling for Spotify API rate limits (HTTP 429) and gateway timeouts.
- **Deezer Synchronization**:
  - Sync all public playlists for a Deezer profile ID (`DEEZER_USER_ID`).
  - Sync explicit Deezer playlist IDs (`DEEZER_PLAYLIST_ID`).
- **Smart Plex Track Matching**:
  - Multi-tier matching (exact title & artist fuzzy comparison).
  - Automated title sanitization for fallback searching (cleans remaster tags, deluxe edition brackets, and feature tags).
  - Configurable similarity threshold (`SEARCH_SIMILARITY_THRESHOLD`).
- **Flexible Execution Modes**:
  - **Daemon Loop**: Continuous synchronization with configurable wait intervals (`SECONDS_TO_WAIT`).
  - **One-Shot / Cron Mode**: Runs a single synchronization cycle and exits cleanly (`RUN_ONCE=1` or `CRON=1`).
- **Security & Network Flexibility**:
  - Optional SSL verification bypass (`PLEX_VERIFY_SSL=0` or `IGNORE_SSL=1`) for self-signed certificates or internal reverse proxies.
  - Multi-architecture non-root Docker container (`uid 1000`).
- **Export Missing Tracks**:
  - Option to write unmatched tracks per playlist to CSV files in `/data` (`WRITE_MISSING_AS_CSV=1`). Automatically cleans up CSVs once all tracks are matched.

---

## Configuration & Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PLEX_URL` | *Required* | Base URL to your Plex server (e.g. `http://192.168.1.100:32400`) |
| `PLEX_TOKEN` | *Required* | Plex authentication token ([Find your Plex Token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)) |
| `PLEX_VERIFY_SSL` | `1` | Set to `0` or `false` to disable SSL certificate verification (useful for self-signed certs) |
| `RUN_ONCE` / `CRON` | `0` | Set to `1` to run a single sync pass and exit (ideal for cron or task schedulers) |
| `SECONDS_TO_WAIT` | `86400` | Seconds to wait between sync cycles when running as a continuous daemon |
| `APPEND_SERVICE_SUFFIX` | `1` | Appends ` - Spotify` or ` - Deezer` to the Plex playlist title (`1` = enabled, `0` = disabled) |
| `ADD_PLAYLIST_POSTER` | `1` | Copies playlist cover art to Plex (`1` = enabled, `0` = disabled) |
| `ADD_PLAYLIST_DESCRIPTION` | `1` | Copies playlist description to Plex (`1` = enabled, `0` = disabled) |
| `APPEND_INSTEAD_OF_SYNC` | `0` | `0` = keeps Plex playlist in sync with source; `1` = append tracks only without removing deletions |
| `WRITE_MISSING_AS_CSV` | `0` | `1` = writes unmatched tracks for each playlist to `/data/<playlist_name>.csv` |
| `SEARCH_SIMILARITY_THRESHOLD` | `0.9` | Float threshold between `0.0` and `1.0` for fuzzy artist/album title matching |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `SPOTIFY_CLIENT_ID` | *Optional* | Spotify Developer Application Client ID |
| `SPOTIFY_CLIENT_SECRET` | *Optional* | Spotify Developer Application Client Secret |
| `SPOTIFY_USER_ID` | *Optional* | Spotify user profile ID (syncs all owned/followed playlists) |
| `SPOTIFY_PLAYLIST_ID` | *Optional* | Space- or comma-separated list of Spotify playlist IDs, URLs, or URIs |
| `DEEZER_USER_ID` | *Optional* | Deezer numerical user ID |
| `DEEZER_PLAYLIST_ID` | *Optional* | Space- or comma-separated list of Deezer playlist IDs |

---

## Docker Deployment

### Docker Run

```bash
docker run -d \
  --name=playlistSync \
  --restart unless-stopped \
  -e PLEX_URL="http://192.168.1.100:32400" \
  -e PLEX_TOKEN="YOUR_PLEX_TOKEN" \
  -e SPOTIFY_CLIENT_ID="YOUR_SPOTIFY_CLIENT_ID" \
  -e SPOTIFY_CLIENT_SECRET="YOUR_SPOTIFY_CLIENT_SECRET" \
  -e SPOTIFY_USER_ID="YOUR_SPOTIFY_USER_ID" \
  -e WRITE_MISSING_AS_CSV=1 \
  -v /path/to/missing_data:/data \
  ghcr.io/ronfburgundy/plex-playlist-sync:latest
```

### Docker Compose

```yaml
services:
  playlistSync:
    image: ghcr.io/ronfburgundy/plex-playlist-sync:latest
    container_name: playlistSync
    restart: unless-stopped
    volumes:
      - ./data:/data
    environment:
      - PLEX_URL=http://localhost:32400
      - PLEX_TOKEN=your_plex_token_here
      - PLEX_VERIFY_SSL=1
      - SECONDS_TO_WAIT=86400
      - RUN_ONCE=0
      - APPEND_SERVICE_SUFFIX=1
      - ADD_PLAYLIST_POSTER=1
      - ADD_PLAYLIST_DESCRIPTION=1
      - WRITE_MISSING_AS_CSV=0
      - SPOTIFY_CLIENT_ID=your_client_id
      - SPOTIFY_CLIENT_SECRET=your_client_secret
      - SPOTIFY_USER_ID=your_spotify_user
      - DEEZER_USER_ID=
```

---

## Local Development & Testing

```bash
# Clone the repository
git clone https://github.com/RonFBurgundy/plex-playlist-sync.git
cd plex-playlist-sync

# Run test suite
pytest
```

---

## License

GNU General Public License v3 (GPL-3.0). See [LICENSE.md](LICENSE.md) for details.
