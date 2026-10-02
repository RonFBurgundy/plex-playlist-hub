# Spotify Import & Keyless Sync Guide

This guide covers how **Plex Playlist Hub** enables administrators and non-technical Plex Home users to import and synchronize Spotify playlists into **Plexamp**—**without requiring a Spotify Developer API key or developer account**.

---

## Table of Contents

1. [Why Keyless? (Commercial Services vs. Self-Hosted)](#why-keyless-commercial-services-vs-self-hosted)
2. [Import Methods Overview](#import-methods-overview)
3. [Method 1: Public Playlists via Keyless Scraper ("By Link")](#method-1-public-playlists-via-keyless-scraper-by-link)
4. [Method 2: Private Playlists & Liked Songs ("Paste Tracks")](#method-2-private-playlists--liked-songs-paste-tracks)
5. [Method 3: 1-Click Browser Bookmarklet Helper](#method-3-1-click-browser-bookmarklet-helper)
6. [Supported Text & Clipboard Formats](#supported-text--clipboard-formats)
7. [Bypassing Browser Mixed-Content & CSP Constraints](#bypassing-browser-mixed-content--csp-constraints)
8. [REST API Reference (`POST /api/playlists/import`)](#rest-api-reference)
9. [Frequently Asked Questions (FAQ)](#frequently-asked-questions-faq)

---

## Why Keyless? (Commercial Services vs. Self-Hosted)

Users often ask: *How do commercial services like Soundiiz or TuneMyMusic connect to Spotify without asking me to create a Spotify Developer app?*

### The Commercial Model
Commercial services register their own multi-tenant enterprise application with Spotify. Their centralized cloud backend stores their proprietary `CLIENT_ID` and `CLIENT_SECRET`, and prompts you to sign in with Spotify OAuth.

### The Self-Hosted Reality
In open-source, self-hosted applications:
- Hardcoding a shared `CLIENT_SECRET` in public code violates Spotify's Developer Terms of Service and triggers GitHub secret scanning blocks.
- Expecting non-technical household users (family, roommates, kids) to create a Spotify Developer Portal account, register an app, configure redirect URIs, and copy-paste API credentials is a significant usability barrier.

**Plex Playlist Hub solves this completely**:
1. **Public Playlists**: Uses a zero-credential server-side scraper that extracts metadata directly from Spotify's public SSR hydration data.
2. **Private Playlists & Liked Songs**: Uses client-side clipboard and browser-assisted bridges so users can transfer songs directly from their active Spotify session into their Plexamp profile.

---

## Import Methods Overview

| Method | Best For | Technical Skill Needed | Spotify Credentials Required? |
|---|---|---|---|
| **By Link** | Public playlists (Spotify editorial, charts, friends' public lists) | Low (paste URL) | **None** (Server-side keyless scraper) |
| **Paste Tracks** | Private playlists, desktop app copy, exported text | Low (`Ctrl+C` &rarr; `Ctrl+V`) | **None** |
| **1-Click Helper** | Spotify Web Player, Liked Songs, long user playlists | Very Low (1 click from bookmarks) | **None** |

---

## Method 1: Public Playlists via Keyless Scraper ("By Link")

For any publicly accessible Spotify playlist:

1. In TrackSeerr, click **Add Playlist** in the top navigation bar.
2. Ensure the **By Link** tab is selected. You will see the badge:  
   `No Spotify API Key Needed (Keyless Scraper Active)`.
3. Paste the Spotify playlist URL (e.g. `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M`), URI, or ID.
4. Select which **Plex Home Users** should receive this playlist in their Plexamp library.
5. Click **Add Playlist**.

### How It Works Behind the Scenes
- The backend [`SpotifyWebScraper`](../plex_playlist_sync/clients/spotify_scraper.py) fetches the playlist's server-rendered embed payload.
- It parses the structured `__NEXT_DATA__` JSON block containing the playlist title, cover art, track titles, artists, and albums.
- If the embed page format changes, it falls back to base64 `initialState` hydration parsing from the public web page.
- Track models are matched against your Plex Media Server library, and missing tracks are tracked.

---

## Method 2: Private Playlists & Liked Songs ("Paste Tracks")

Spotify's public web endpoints cannot access unlisted private playlists or your personal **Liked Songs** collection without user credentials. The **Paste Tracks** tab bridges this gap effortlessly:

### Using Spotify Desktop App
1. Open the Spotify desktop application on your computer.
2. Navigate to your playlist or **Liked Songs**.
3. Select tracks by clicking any track and pressing `Ctrl+A` (or `Cmd+A` on macOS) to select all.
4. Press `Ctrl+C` (or `Cmd+C`) to copy.
5. In TrackSeerr, click **Add Playlist** -> **Paste Tracks**.
6. Enter a playlist name (e.g., `My Liked Songs`).
7. Click **Read Clipboard** (or press `Ctrl+V` inside the text area).
8. The live counter will show `X tracks recognized`. Click **Preview tracks** to verify.
9. Select target Plex Home users and click **Import to Plexamp**.

---

## Method 3: 1-Click Browser Bookmarklet Helper

For users using the Spotify Web Player ([open.spotify.com](https://open.spotify.com)), the **1-Click Helper** provides a streamlined transfer experience.

### One-Time Setup (5 Seconds)
1. Open TrackSeerr and click **Add Playlist** -> **1-Click Helper**.
2. Click and drag the button **`[ Send to Plexamp ]`** up into your browser's **Bookmarks Bar**.

### Transferring Any Playlist
1. In another browser tab, open [open.spotify.com](https://open.spotify.com) and navigate to any playlist or your **Liked Songs**.
2. **Scroll through the playlist**: Spotify dynamically renders songs as you scroll. Scroll down until your songs have loaded.
3. Click **`Send to Plexamp`** in your browser Bookmarks Bar.
4. The helper automatically extracts the playlist name, track titles, and artists from the web page, copies them to your clipboard, and opens TrackSeerr in a new tab.
5. TrackSeerr automatically reads the clipboard data, pre-populates the name and tracks, and opens the confirmation modal.
6. Click **Import to Plexamp**—the tracks are immediately matched and added to your Plexamp account!

---

## Supported Text & Clipboard Formats

The built-in parser (`parseImportText`) automatically detects and parses multiple formats:

### 1. Spotify Web Player Table Copy (TSV)
When copying rows from Spotify Web Player:
```text
Title	Artist	Album	Duration
Bohemian Rhapsody	Queen	A Night at the Opera	5:54
Heroes	David Bowie	Heroes	6:11
```
*Also supports track number prefixes: `1\tTitle\tArtist\tAlbum`.*

### 2. Hyphen Delimited (`Artist - Title` or `Title - Artist`)
```text
Queen - Bohemian Rhapsody
David Bowie - "Heroes"
The Rolling Stones - Paint It, Black
```

### 3. "by" Notation
```text
Bohemian Rhapsody by Queen
Paint It Black by The Rolling Stones
```

### 4. Standard CSV
```text
"Bohemian Rhapsody","Queen","A Night at the Opera"
"Heroes","David Bowie","Heroes"
```

### 5. Structured JSON (Bookmarklet Payload)
```json
{
  "name": "Road Trip Mix",
  "tracks": [
    {"title": "Bohemian Rhapsody", "artist": "Queen", "album": "A Night at the Opera"},
    {"title": "Heroes", "artist": "David Bowie", "album": "Heroes"}
  ]
}
```

---

## Bypassing Browser Mixed-Content & CSP Constraints

### The Security Challenge
- Spotify Web Player runs exclusively over secure HTTPS: `https://open.spotify.com`.
- Most self-hosted local media servers and hubs run over standard HTTP on a local LAN IP (e.g. `http://192.168.1.100:5250`).
- Modern browsers enforce strict **Mixed Content** security rules: scripts running inside `open.spotify.com` are blocked from issuing direct background `fetch()` or `XMLHttpRequest` calls to an unencrypted `http://` LAN IP.
- Furthermore, Spotify's **Content-Security-Policy (CSP)** `connect-src` header blocks outbound API calls to unauthorized third-party domains.

### The Plex Playlist Hub Solution
Rather than making network requests from Spotify's origin:
1. The bookmarklet runs entirely client-side, reading the rendered DOM rows.
2. It serializes the tracks into a structured JSON string and writes it to the user's local clipboard using the native `navigator.clipboard.writeText()` API.
3. It opens the user's hub tab with a URL fragment: `window.open('http://<hub-ip>:5250/#import=clipboard', '_blank')`.
4. When the hub page loads, it detects the fragment, strips it from the browser address bar, and prompts the user or invokes `navigator.clipboard.readText()` to import the payload safely within the hub's own origin.

This architecture requires **no TLS certificates**, **no reverse proxies**, and **no browser extensions**.

---

## REST API Reference

For developers or custom integrations, you can directly import track collections via the REST API.

### Direct Import Endpoint
```http
POST /api/playlists/import
Content-Type: application/json
Authorization: Bearer <session_token>
```

#### Request Payload
```json
{
  "name": "Summer Road Trip 2024",
  "service": "spotify",
  "tracks": [
    {
      "title": "Bohemian Rhapsody",
      "artist": "Queen",
      "album": "A Night at the Opera"
    },
    {
      "title": "Heroes",
      "artist": "David Bowie",
      "album": "Heroes"
    }
  ],
  "targets": ["1", "2"],
  "description": "Imported via clipboard helper",
  "poster_url": ""
}
```

#### Field Specifications
| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | **Yes** | Name of the playlist to create in Plex |
| `service` | string | No | Source service identifier (`"spotify"` or `"deezer"`, defaults to `"spotify"`) |
| `tracks` | array | **Yes** | List of track objects (`title` is required; `artist` and `album` optional) |
| `targets` | array | No | User IDs to sync this playlist to. Standard users can only target themselves. Admins can target any Plex Home user. |
| `description` | string | No | Optional playlist summary |
| `poster_url` | string | No | Optional HTTP/HTTPS URL for playlist cover artwork |

#### Response (`200 OK`)
```json
{
  "id": "imp_a3f891b2c4e5",
  "name": "Summer Road Trip 2024",
  "service": "spotify",
  "track_count": 2,
  "matched_count": 2,
  "missing_count": 0,
  "targets": ["1", "2"],
  "status": "imported"
}
```

---

## Frequently Asked Questions (FAQ)

### Q: What if my playlist has hundreds of songs?
- **Web Player**: Spotify Web Player uses virtual scrolling (it only keeps tracks in the DOM that are near the current scroll position). Slowly scroll down the playlist page so Spotify fetches all items, then click the **Send to Plexamp** bookmarklet.
- **Desktop App**: Open the playlist in Spotify Desktop, press `Ctrl+A` (select all) and `Ctrl+C` (copy), then switch to the TrackSeerr **Paste Tracks** tab and paste.

### Q: Why didn't all tracks match in Plex?
TrackSeerr matches songs against your existing local Plex Music Library. If an album or song is not currently in your Plex media storage, it cannot be added to your Plexamp playlist.
- Click **View Missing** in the TrackSeerr dashboard to see the exact unmatched tracks.
- Click **Search** next to any missing track to find it online or verify its metadata tags.
- Click **Export Safe CSV** to generate a clean list of songs to add to your collection.

### Q: Can non-admin Plex Home members import their own playlists?
**Yes!** Managed users and Plex Home members can log in using their own Plex account via the **Sign In with Plex** PIN flow. Regular users can import playlists directly into their personal Plexamp account without granting them admin control over other users or server settings.
