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
    
    E -->|Direct API Push / Custom Import List| F["Lidarr"]
    F -->|Monitors & Downloads| G["Music Downloader (Usenet / Torrents)"]
    G -->|Imports New Files| C
    
    F -->|Webhook: On Download| H["POST /api/sync/webhook"]
    H --> B
    B -->|Self-Healing Sync Cycle| C
    C -->|Newly Discovered Tracks| D
    B -->|Clears Acquired Tracks| E
```

1. **Detection**: Tracks in synchronized or imported playlists that are not found in Plex are logged to the Hub's persistent SQLite database.
2. **Acquisition**: Missing tracks are exposed to Lidarr via **Direct API Push**, **Lidarr Custom Import Lists (JSON)**, or **RSS 2.0 Feeds**.
3. **Automatic Notification**: When Lidarr finishes importing a track and notifies Plex to scan its library, Lidarr fires a webhook back to the Hub.
4. **Self-Healing Sync**: The Hub re-matches the newly acquired tracks and injects them directly into the targeted users' Plexamp playlists, automatically removing them from the missing list.

---

## Integration Methods

### Option 1: Direct Lidarr API Push (Recommended)

With Direct API integration, you can monitor and trigger automatic searches in Lidarr directly from the Plex Playlist Hub Web Dashboard.

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
      # Optional Lidarr Profile Overrides
      # - LIDARR_ROOT_FOLDER=/music
      # - LIDARR_QUALITY_PROFILE_ID=1
      # - LIDARR_METADATA_PROFILE_ID=1
```

*Note: Your Lidarr API key can be found in Lidarr under **Settings** &rarr; **General** &rarr; **Security** &rarr; **API Key**.*

#### 2. Using the Web Dashboard

1. In Plex Playlist Hub, click the **Unmatched Tracks** button in the dashboard navigation.
2. A green badge **"Direct API Connected"** will appear in the **Lidarr & Feeds** section.
3. Click **"Push All to Lidarr"** to automatically queue and monitor all missing tracks, or click the **"+ Lidarr"** button next to individual tracks in the list.

---

### Option 2: Lidarr Custom Import List (Periodic Poll)

Lidarr can periodically poll Plex Playlist Hub for missing tracks using its built-in Custom List import feature.

#### Endpoint URL
```
http://<your-hub-ip>:5250/api/missing/lidarr
```

*To monitor tracks for only a specific playlist:*
```
http://<your-hub-ip>:5250/api/missing/lidarr?playlist_id=<playlist_id>
```

#### Step-by-Step Setup in Lidarr:
1. Open Lidarr and navigate to **Settings** &rarr; **Import Lists**.
2. Click the large **`+`** icon to add a new list.
3. Select **Advanced Lists** &rarr; **Custom List**.
4. Configure the settings:
   - **Name**: `Plex Playlist Hub Missing Tracks`
   - **Enable Auto Search**: Yes (Checked)
   - **Monitor**: All Albums or Only New Albums (based on preference)
   - **List URL**: `http://<your-hub-ip>:5250/api/missing/lidarr`
   - *If `FEED_TOKEN` is enabled*: append `?token=<your_feed_token>` to the URL, or add an HTTP header `X-Api-Key: <your_feed_token>`.
5. Click **Test** and then **Save**.
6. Lidarr will now periodically query the Hub and queue missing music.

---

### Option 3: RSS 2.0 & Plain Text Feeds

For universal compatibility with third-party RSS aggregators, Prowlarr, or command-line scripts, Plex Playlist Hub provides standard RSS and text feeds.

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

When `FEED_TOKEN` is configured, requests to `/api/missing/rss`, `/api/missing/lidarr`, `/api/missing/text`, and `/api/sync/webhook` must provide the token via:
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
| `LIDARR_ROOT_FOLDER` | *Auto-detected* | Custom Lidarr root folder path (auto-detects first active root folder if omitted) |
| `LIDARR_QUALITY_PROFILE_ID` | *Auto-detected* | Custom Lidarr quality profile ID (auto-detects first active profile if omitted) |
| `LIDARR_METADATA_PROFILE_ID` | *Auto-detected* | Custom Lidarr metadata profile ID (auto-detects standard profile if omitted) |
| `FEED_TOKEN` | *None* | Secret token required to access RSS feeds and trigger webhooks |
