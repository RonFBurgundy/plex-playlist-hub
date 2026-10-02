# Acquisition and Automation Guide

TrackSeerr provides two distinct methods for acquiring missing music and fulfilling requests:

1. **Native Acquisition Drivers**: TrackSeerr acts as its own acquisition manager, connecting directly to slskd (Soulseek P2P), SABnzbd (Usenet), qBittorrent (BitTorrent), and Torznab/Newznab indexers. TrackSeerr manages the transfer queue, inspects audio files with Mutagen, formats file paths using an Arr-grade token engine, and places files into `/music`.
2. **Lidarr Integration**: TrackSeerr connects to an existing Lidarr instance via its REST API, using a paced trickle worker to monitor specific missing albums without triggering full artist discography downloads or overwhelming MusicBrainz.

Both approaches support automated self-healing, where newly acquired tracks are matched in Plex and added directly to user playlists.

---

## Architecture Comparison

| Capability | Native Drivers (slskd, SABnzbd, qBittorrent) | Lidarr Integration |
|---|---|---|
| Single-track surgical matching | Yes (via slskd) | No (Lidarr operates at album level) |
| Usenet acquisition | Yes (via SABnzbd + Newznab) | Yes (via Lidarr download clients) |
| Torrent acquisition | Yes (via qBittorrent + Torznab) | Yes (via Lidarr download clients) |
| Tag inspection | Mutagen (FLAC, MP3, M4A, Opus) | Lidarr internal tagger |
| File renaming and moving | Built-in token template engine | Lidarr media management |
| External dependencies | Downloader daemon only | Full Lidarr container and database |
| Volume mounts required | `/music` and `/downloads` | None on TrackSeerr (handled by Lidarr) |

---

## Method 1: Native Acquisition Drivers

Native drivers allow you to fulfill requests and missing tracks without running Lidarr. TrackSeerr queries downloaders directly and handles post-processing.

### Supported Clients

- **slskd (Soulseek P2P)**: Ideal for rare tracks, b-sides, single-track missing items, and complete album transfers.
- **SABnzbd (Usenet)**: Connects to your SABnzbd instance to download NZBs sourced from Newznab indexers.
- **qBittorrent (BitTorrent)**: Connects to your qBittorrent WebUI to download torrents sourced from Torznab indexers.

### Volume Mount Requirements

When using native drivers, TrackSeerr needs access to both download staging and your media library:

```yaml
volumes:
  - ./data:/data
  - /path/to/music:/music
  - /path/to/downloads:/downloads
```

- `/downloads`: The folder where slskd, SABnzbd, or qBittorrent stores completed transfers.
- `/music`: The destination music library directory scanned by Plex Media Server.

### Configuring Download Clients in the Web UI

1. Open the TrackSeerr web dashboard at `http://<your-server-ip>:5250`.
2. Navigate to **Settings** -> **Download Clients**.
3. Click **Add Download Client**.
4. Select your driver type:
   - **slskd**: Set the Host URL (e.g. `http://192.168.1.50:5030` or `http://slskd:5030`), API key, and staging download path.
   - **SABnzbd**: Set the Host URL (e.g. `http://192.168.1.50:8080`) and API key.
   - **qBittorrent**: Set the Host URL (e.g. `http://192.168.1.50:8088`), username, and password.
5. Click **Test Connection** to verify reachability, then **Save Client**.

### Configuring Indexers (Torznab & Newznab)

For SABnzbd and qBittorrent, TrackSeerr searches releases through Torznab and Newznab compatible indexers (Prowlarr, Jackett, NZBHydra2, or private indexers):

1. Navigate to **Settings** -> **Indexers**.
2. Click **Add Indexer**.
3. Select the protocol (`Torznab` or `Newznab`).
4. Enter the indexer URL (e.g. `http://192.168.1.50:9696/1/api` for Prowlarr) and your API key.
5. Test connectivity and save.

### The Activity Queue and Organizer Lifecycle

When a track or album is queued for download:

1. **Queueing**: The download appears in the **Activity** tab with real-time transfer progress, estimated file size, and client name.
2. **Monitoring**: The `AcquisitionWorker` polls the download client every 5 seconds.
3. **Completion**: Once the downloader marks the file complete, TrackSeerr moves it to the `Importing` state.
4. **Tag Inspection**: Mutagen inspects audio tags (artist, album, track number, disc number, audio codec, bit depth, sample rate).
5. **Path Formatting**: The destination path is generated according to your configured naming template (e.g., `{Artist Name}/{Album Title} ({Release Year})/{track:00} - {Track Title}`).
6. **Collision Check & Atomic Move**: If the file already exists, TrackSeerr appends a safe counter (`Title (1).flac`). The file is moved into `/music` using cross-filesystem safe atomic moves.
7. **Plex Scan**: TrackSeerr pings Plex Media Server to scan the updated artist folder.
8. **Request Fulfillment**: The request is marked `Available` in the web dashboard, and user playlists are updated.

---

## Method 2: Lidarr Integration and Paced Trickle Worker

If you already run Lidarr and prefer it to manage downloaders and file renaming, TrackSeerr integrates directly via Lidarr's REST API.

```
+-----------------------------------+
|  Spotify / Deezer Playlist / Web  |
+-----------------------------------+
                  |
                  v
+-----------------------------------+
|            TrackSeerr             |
+-----------------------------------+
         |                  ^
         | (Paced Trickle)  | (Webhook on download)
         v                  |
+-------------------+       |
|      Lidarr       |-------+
+-------------------+
         |
         v
+-------------------+
| Downloaders & NZB |
+-------------------+
         |
         v
+-------------------+
| Plex Media Server |
+-------------------+
```

### Why Direct REST API Instead of Lidarr Custom Lists?

Lidarr's built-in "Custom List" feature only imports artists by MusicBrainz Artist UUID (`musicBrainzId`). It does not support track-level or single-album scoping. Using Custom Lists often leads to empty list errors or causes Lidarr to monitor and download entire discographies for an artist when you only wanted a single song.

TrackSeerr's direct API integration searches Lidarr's metadata lookup for the exact artist, adds the artist with root monitoring set to `none`, monitors only the specific missing album, and triggers a targeted `AlbumSearch`.

### The Paced Trickle Worker

When importing playlists with hundreds or thousands of missing tracks, sending immediate batched requests to Lidarr can overload Lidarr's SQLite database, trigger rate limits on MusicBrainz (`api.lidarr.audio`), or overwhelm indexers.

TrackSeerr includes a background trickle worker that safely spaces requests:

- **Artist Deduplication**: Missing tracks are grouped by artist. The artist lookup is executed once per artist rather than once per track, cutting API calls significantly.
- **Targeted Monitoring**: Only missing albums are flagged for download; discographies are left unmonitored.
- **Configurable Drip Delay**: Requests are sent with a configurable delay (default: 3.0 seconds) plus random jitter.
- **Rate-Limit Backoff**: If Lidarr or MusicBrainz returns HTTP 429 or 503, the worker pauses for 60 seconds before retrying.
- **Queue Controls**: You can monitor progress live in the dashboard, pause, resume, or cancel active runs.
- **State Persistence**: Tracks submitted to Lidarr are marked as `Monitored` in SQLite so duplicate requests are avoided across future playlist syncs.

### Lidarr Environment Configuration

Add the following environment variables to your compose configuration:

```yaml
services:
  trackseerr:
    image: ghcr.io/ronfburgundy/trackseerr:latest
    environment:
      - LIDARR_URL=http://192.168.1.100:8686
      - LIDARR_API_KEY=your_lidarr_api_key_here
      - LIDARR_AUTO_SEARCH=1
      - LIDARR_TRICKLE_RATE_SECONDS=3.0
      - LIDARR_TRICKLE_BATCH_SIZE=25
      - LIDARR_AUTO_TRICKLE=0
      - LIDARR_AUTO_TRICKLE_INTERVAL_MINUTES=30
      # Optional Lidarr Profile Overrides:
      # - LIDARR_ROOT_FOLDER=/music
      # - LIDARR_QUALITY_PROFILE_ID=1
      # - LIDARR_METADATA_PROFILE_ID=1
```

*Note: Your Lidarr API key is located in Lidarr under **Settings** -> **General** -> **Security** -> **API Key**.*

### Triggering Pushes from the Dashboard

1. Navigate to the **Unmatched Tracks** section in the web interface.
2. Confirm the **Direct API Connected** status indicator.
3. Select your push action:
   - **Push Next 25**: Queues the next batch of 25 unmonitored tracks into the trickle worker.
   - **Push All (Paced)**: Queues all unmonitored tracks into the background worker for paced delivery.
   - **+ Lidarr (Row-level)**: Queues a single track or album immediately.

---

## Automated Self-Healing Webhook Loop

To update user playlists immediately when Lidarr completes a download, configure a webhook in Lidarr pointing to TrackSeerr.

### Setting Up the Webhook in Lidarr

1. In Lidarr, go to **Settings** -> **Connect**.
2. Click the **+** button and select **Webhook**.
3. Configure the fields:
   - **Name**: `TrackSeerr Re-Sync`
   - **Notification Triggers**: Check **On Download** and **On Upgrade**
   - **URL**: `http://<your-trackseerr-ip>:5250/api/sync/webhook`
   - **Method**: `POST`
4. Click **Test**, then **Save**.

### How Self-Healing Works

When Lidarr finishes downloading and organizing a track:
1. Lidarr notifies Plex to scan the updated directory.
2. Lidarr sends a POST request to TrackSeerr at `/api/sync/webhook`.
3. TrackSeerr triggers a targeted re-sync of all playlists containing missing tracks.
4. Newly discovered tracks in Plex are matched and inserted directly into users' Plexamp playlists.
5. Resolved tracks are removed from the missing tracks list.

---

## Universal Feeds for External Downloaders

TrackSeerr also provides standard RSS and text feeds for users who prefer custom download scripts, Prowlarr sync, or external download managers.

### RSS 2.0 Feed
- **URL**: `http://<your-server-ip>:5250/api/missing/rss`
- **Format**: Standard RSS 2.0 XML containing track title, artist, album, and timestamp.
- **Filter by Playlist**: Append `?playlist_id=<id>` to scope the feed to a specific playlist.

### Plain Text Feed
- **URL**: `http://<your-server-ip>:5250/api/missing/text`
- **Format**: One track per line formatted as `Artist - Title` or `Artist - Title (Album: ...)`.

### Securing Feeds with a Token

If TrackSeerr is exposed outside a protected local network, define `FEED_TOKEN` in your environment:

```yaml
environment:
  - FEED_TOKEN=your_secure_feed_token_here
```

When set, feed and webhook endpoints require authentication via:
- URL query parameter: `?token=your_secure_feed_token_here`
- Header: `X-Api-Key: your_secure_feed_token_here`
- Header: `Authorization: Bearer your_secure_feed_token_here`

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `LIDARR_URL` | *None* | Base URL to your Lidarr server (e.g. `http://192.168.1.100:8686`) |
| `LIDARR_API_KEY` | *None* | Lidarr API Key |
| `LIDARR_AUTO_SEARCH` | `1` | Automatically trigger interactive searches when pushing to Lidarr (`1` or `0`) |
| `LIDARR_TRICKLE_RATE_SECONDS` | `3.0` | Delay between artist queries during background trickle |
| `LIDARR_TRICKLE_BATCH_SIZE` | `25` | Number of missing tracks pushed per manual batch or scheduled drip |
| `LIDARR_AUTO_TRICKLE` | `0` | Enable scheduled background trickle runs (`1` or `0`) |
| `LIDARR_AUTO_TRICKLE_INTERVAL_MINUTES` | `30` | Interval in minutes between automated drip runs |
| `LIDARR_ROOT_FOLDER` | *Auto* | Custom Lidarr root folder path |
| `LIDARR_QUALITY_PROFILE_ID` | *Auto* | Custom Lidarr quality profile ID |
| `LIDARR_METADATA_PROFILE_ID` | *Auto* | Custom Lidarr metadata profile ID |
| `FEED_TOKEN` | *None* | Secret token protecting RSS feeds, plain text lists, and webhooks |
