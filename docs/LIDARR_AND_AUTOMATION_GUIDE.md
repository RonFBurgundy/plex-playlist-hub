# Lidarr Integration & Automated Self-Healing Sync Guide

Plex Playlist Hub features end-to-end integration with [Lidarr](https://lidarr.audio/) and RSS-compatible download managers to automatically acquire missing music and seamlessly inject it into your Plexamp playlists once downloaded.

---

## The Self-Healing Lifecycle

When a playlist from Spotify or Deezer contains songs that don't yet exist in your Plex Music Library, Plex Playlist Hub handles the entire acquisition and healing lifecycle:

```mermaid
flowchart TD
    A["Spotify / Deezer Playlist"] -->|Sync or Import| B["Plex Playlist Hub"]
    B -->|Match Local Tracks| C["Plex Media Server"]
    C -->|Found Tracks| D["Plexamp Playlists (Per User)"]
    B -->|Unmatched Tracks| E["Missing Tracks Database"]
    
    E -->|Direct REST API Push (+ Lidarr / Push All)| F["Lidarr"]
    F -->|Monitors & Downloads| G["Music Downloader (Usenet / Torrents)"]
    G -->|Imports New Files| C
    
    F -->|Webhook: On Download| H["POST /api/sync/webhook"]
    H --> B
    B -->|Self-Healing Sync Cycle| C
    C -->|Newly Discovered Tracks| D
    B -->|Clears Acquired Tracks| E
```

1. **Detection**: Tracks in synchronized or imported playlists that are not found in Plex are logged to the Hub's persistent SQLite database.
2. **Acquisition**: Missing tracks are queued into Lidarr via **Direct REST API Push**, or exported via **RSS 2.0 Feeds** and **Plain Text** for external download managers.
3. **Automatic Notification**: When Lidarr finishes importing a track and notifies Plex to scan its library, Lidarr fires a webhook back to the Hub.
4. **Self-Healing Sync**: The Hub re-matches the newly acquired tracks and injects them directly into the targeted users' Plexamp playlists, automatically removing them from the missing list.

---

## Integration Methods

### Option 1: Direct Lidarr API Push (Recommended & Supported)

Direct API integration is the official and supported method to connect Lidarr to Plex Playlist Hub. It is built from the ground up for high scalability when onboarding massive libraries with thousands of missing tracks.

> [!NOTE]
> **Why not Lidarr's "Custom List"?**
> Lidarr's internal Custom Import List parser is strictly limited to importing entire artists via MusicBrainz Artist UUIDs (`musicBrainzId`). It does not support track-level or single-album scoping and ignores artist/album title text, which causes "no list items to process" errors or downloads entire artist discographies. The Direct API completely avoids this by searching Lidarr's metadata lookup for the exact artist, monitoring only the specific missing album, and triggering a targeted `AlbumSearch`.

#### Scalable Trickle Architecture

When onboarding thousands of missing tracks, sending rapid synchronous requests can easily overwhelm Lidarr, hit MusicBrainz rate limits (`api.lidarr.audio`), or choke downstream Usenet/BitTorrent indexers. Plex Playlist Hub protects your infrastructure with an enterprise-grade trickle architecture:

1. **Artist-First Batching & Deduplication**: Missing tracks are grouped by artist. Lidarr's metadata lookup runs only **once** per artist rather than once per track, reducing API lookups by 60–80%.
2. **Targeted Album Monitoring**: When a new artist is added, their root monitoring profile is set to `monitor: "none"`. Only the specific missing album(s) are set to monitored. A batched `AlbumSearch` command is queued specifically for those albums, avoiding unwanted discography downloads.
3. **Paced Background Trickle Worker**: A dedicated background worker drips requests with configurable delays (default: 3.0s + gentle jitter) between artists.
4. **Adaptive Rate-Limit Backoff**: If Lidarr or MusicBrainz responds with HTTP 429 (Too Many Requests) or HTTP 503 (Service Unavailable), the worker automatically pauses for 60 seconds before retrying, preventing IP bans.
5. **Interactive Queue Controls**: Monitor live worker progress in the dashboard with an animated progress bar, active artist indicator, and instant **Pause**, **Resume**, and **Cancel** buttons.
6. **Persistent Tracking**: Once a track has been submitted to Lidarr, it is marked as `Monitored` in the local SQLite database. Subsequent playlist syncs preserve this status so duplicate searches are never sent.

#### 1. Configure Environment Variables

Add the following environment variables to your `docker-compose.yml`:

```yaml
services:
  playlistHub:
    image: ghcr.io/ronfburgundy/plex-playlist-hub:latest
    environment:
      # Lidarr Direct Connection
      - LIDARR_URL=http://192.168.1.100:8686
      - LIDARR_API_KEY=your_lidarr_api_key_here
      - LIDARR_AUTO_SEARCH=1
      # Trickle & Rate-Limiting Controls
      - LIDARR_TRICKLE_RATE_SECONDS=3.0      # Delay between artist lookups in seconds
      - LIDARR_TRICKLE_BATCH_SIZE=25         # Number of tracks per manual chunk or cron drip
      - LIDARR_AUTO_TRICKLE=0                # Set to 1 to enable automated background drip
      - LIDARR_AUTO_TRICKLE_INTERVAL_MINUTES=30 # Run automated drip every 30 minutes
      # Optional Lidarr Profile Overrides
      # - LIDARR_ROOT_FOLDER=/music
      # - LIDARR_QUALITY_PROFILE_ID=1
      # - LIDARR_METADATA_PROFILE_ID=1
```

*Note: Your Lidarr API key can be found in Lidarr under **Settings** &rarr; **General** &rarr; **Security** &rarr; **API Key**.*

#### 2. Using the Web Dashboard

1. In Plex Playlist Hub, click the **Unmatched Tracks** button in the dashboard navigation.
2. A green badge **"Direct API Connected"** will appear in the **Lidarr & Feeds** section.
3. Choose your push strategy:
   - **"Push Next 25"**: Enqueues the next chunk of 25 unmonitored tracks into the trickle worker. Ideal for incremental testing.
   - **"Push All (Paced)"**: Enqueues all unmonitored tracks into the background worker. The worker smoothly drips artist searches with jitter and backoff.
   - **Row-level `+ Lidarr`**: Instantly queue an individual track without touching the rest of the queue. Once queued, the button transitions to an emerald **Monitored** badge.
4. While the worker is running, a live banner appears showing real-time progress, currently processing artist, completed count, and **Pause** / **Resume** / **Cancel** controls.

---

### Option 2: RSS 2.0 & Plain Text Feeds (For External Downloaders)

For universal compatibility with third-party RSS aggregators, Prowlarr, qBittorrent RSS rules, or command-line batch scripts, Plex Playlist Hub provides standard RSS and text feeds.

#### RSS 2.0 Feed
- **URL**: `http://<your-hub-ip>:5250/api/missing/rss`
- **Format**: Standard RSS 2.0 XML with `<channel>` and `<item>` elements. Each item includes track title, artist, album, and publication timestamp.
- **Filtering**: Add `?playlist_id=<id>` to scope the feed to a single playlist.

#### Plain Text Feed
- **URL**: `http://<your-hub-ip>:5250/api/missing/text`
- **Format**: Plain text `Artist - Title` (or `Artist - Title (Album: ...)`), one entry per line.
- **Use Case**: Shell scripts, batch download tools, or local logging.

---

## Closing the Loop: Automated Self-Healing Webhook

To achieve instant playlist updates as soon as music is downloaded—without waiting for the scheduled background sync—configure Lidarr to ping Plex Playlist Hub.

### Step-by-Step Webhook Setup in Lidarr:

1. In Lidarr, navigate to **Settings** &rarr; **Connect**.
2. Click the **`+`** icon and choose **Webhook**.
3. Configure the notification webhook:
   - **Name**: `Plex Playlist Hub Re-Sync`
   - **Notification Triggers**:
     - Check **On Download**
     - Check **On Upgrade**
   - **URL**: `http://<your-hub-ip>:5250/api/sync/webhook`
   - **Method**: `POST`
4. Click **Test** and then **Save**.

### How the Webhook Works:
When Lidarr finishes downloading a song, it fires a webhook payload to `/api/sync/webhook`. 
The Hub immediately triggers a background re-sync:
1. Re-scans all playlists containing missing tracks (including 1-Click imported playlists).
2. Matches newly imported tracks in your local Plex library.
3. Adds them directly to the targeted Plexamp playlists for every assigned user.
4. Cleans up the missing tracks registry.

---

## Feed Security & Token Protection

If your Plex Playlist Hub instance is exposed to the internet or an untrusted local network, protect the feed and webhook endpoints with a feed access token:

```yaml
environment:
  - FEED_TOKEN=my-secure-random-token-here
```

When `FEED_TOKEN` is configured, requests to `/api/missing/rss`, `/api/missing/text`, and `/api/sync/webhook` must provide the token via:
- URL query parameter: `?token=my-secure-random-token-here`
- Header: `X-Api-Key: my-secure-random-token-here`
- Header: `Authorization: Bearer my-secure-random-token-here`

*Note: In trusted LAN environments where `FEED_TOKEN` is not set, read-only feed endpoints and local webhooks are accessible without authentication for ease of setup with network containers.*

---

## Configuration Reference

| Environment Variable | Default | Description |
|---|---|---|
| `LIDARR_URL` | *None* | Base URL to your Lidarr server (e.g. `http://192.168.1.100:8686`) |
| `LIDARR_API_KEY` | *None* | Lidarr API Key (from *Settings -> General -> Security*) |
| `LIDARR_AUTO_SEARCH` | `1` | Automatically trigger an interactive search in Lidarr when pushing tracks (`1` or `0`) |
| `LIDARR_TRICKLE_RATE_SECONDS` | `3.0` | Delay between artist lookups in seconds during background trickle push |
| `LIDARR_TRICKLE_BATCH_SIZE` | `25` | Number of missing tracks pushed per manual batch or scheduled drip |
| `LIDARR_AUTO_TRICKLE` | `0` | Enable scheduled automated drip trickle in the background (`1` or `0`) |
| `LIDARR_AUTO_TRICKLE_INTERVAL_MINUTES` | `30` | Interval between automated drip runs in minutes |
| `LIDARR_ROOT_FOLDER` | *Auto-detected* | Custom Lidarr root folder path (auto-detects first active root folder if omitted) |
| `LIDARR_QUALITY_PROFILE_ID` | *Auto-detected* | Custom Lidarr quality profile ID (auto-detects first active profile if omitted) |
| `LIDARR_METADATA_PROFILE_ID` | *Auto-detected* | Custom Lidarr metadata profile ID (auto-detects standard profile if omitted) |
| `FEED_TOKEN` | *None* | Secret token required to access RSS feeds and trigger webhooks |
