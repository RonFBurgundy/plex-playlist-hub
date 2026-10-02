# TrackSeerr Architecture and Security Reference

TrackSeerr is a self-hosted music discovery, request, and library management application. It bridges the gap between streaming platforms (Spotify, Deezer, Apple Music) and personal media servers (Plex, Plexamp), combining an Overseerr-style discovery and request frontend with an Arr-style media management and acquisition backend.

This document details the system design, deployment topologies, media organization pipeline, naming engine tokens, and security controls.

---

## System Overview

TrackSeerr is built with a decoupled architecture that supports both monolithic homelab deployments and multi-tier DMZ-isolated production setups.

```
+-----------------------------------------------------------------------+
|                            User Interfaces                            |
|       Plexamp Playlists  |  Web UI (Desktop & Mobile)  |  Bookmarklet  |
+-----------------------------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|                           Discovery & Auth                            |
|  - Plex OAuth Authentication & Home User Quotas                       |
|  - Zero-Key Music Discovery (Deezer & Apple Music / iTunes APIs)       |
|  - 30-Second Audio Previews                                           |
|  - Spotify Web Scraper (Public Playlists & Keyless Sync)               |
+-----------------------------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|                            Request Engine                             |
|  - Multi-User Request Submission & Approval Queue                     |
|  - Status Lifecycle: Pending -> Approved -> Downloading -> Available  |
|  - Match Memory & Manual Link Overrides                               |
+-----------------------------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|                          Acquisition Layer                            |
|  Option A: Lidarr Adapter (Direct REST API Push & Paced Trickle)       |
|  Option B: Native Drivers (slskd / Soulseek, SABnzbd, qBittorrent)    |
|  - Torznab & Newznab Indexer Query Engine                             |
|  - Real-Time Activity Queue & Progress Tracker                        |
+-----------------------------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------+
|                    Media Management Pipeline                          |
|  - Mutagen Audio Inspection (FLAC, MP3 ID3, M4A/AAC, Ogg/Opus)        |
|  - Arr-Grade Token Template Naming Engine                             |
|  - Collision Resolution & Safe Cross-Mount Atomic Moves               |
|  - Automated Plex Media Server Library Refresh Ping                   |
+-----------------------------------------------------------------------+
```

---

## Deployment Topologies

TrackSeerr supports two primary deployment topologies depending on your network design and threat model.

### 1. Single-Container Mode (`ROLE=all-in-one`)

In single-container mode, the gateway, API, background playlist sync loop, and acquisition worker run together inside a single container.

- **Target Audience**: Standard home servers, Unraid installations, local LAN environments, or deployments accessed entirely behind private VPNs (Tailscale, WireGuard).
- **Network Footprint**: Exposes port `5250` on your local Docker network.
- **Storage Mounts**: Mounts `/data` for configuration and SQLite storage, plus optional `/music` and `/downloads` volumes when using native download clients.

```yaml
services:
  trackseerr:
    image: ghcr.io/ronfburgundy/trackseerr:latest
    container_name: trackseerr
    restart: unless-stopped
    ports:
      - "5250:5250"
    volumes:
      - ./data:/data
      - /path/to/music:/music
      - /path/to/downloads:/downloads
    environment:
      - ROLE=all-in-one
      - PORT=5250
      - PUID=1000
      - PGID=1000
      - UMASK=022
      - PLEX_URL=http://192.168.1.100:32400
      - PLEX_TOKEN=your_plex_token_here
      - PLEX_MUSIC_SECTION=Music
```

### 2. Hardened Two-Tier DMZ Mode

In two-tier mode, TrackSeerr splits into two distinct containers separated across Docker networks:

```
[ Public Internet / Clients ]
              |
              v
     [ Reverse Proxy ]
              |  (proxynet)
              v
+---------------------------+
|    trackseerr-gateway     |  <-- Ingress DMZ (ROLE=gateway)
|  - Web UI & Discovery     |      Zero volume mounts
|  - User Request Portal    |      Zero storage access
|  - Plex OAuth Validation  |      Zero downloader credentials
+---------------------------+
              |
              |  (internal-net: Docker internal bridge, no WAN ingress)
              v
+---------------------------+
|     trackseerr-core       |  <-- Isolated Core (ROLE=core)
|  - Acquisition Worker     |      Mounts /data, /music, /downloads
|  - Arr Naming & Tagging   |      Holds Plex Admin Token
|  - Downloader Drivers     |      Peered with slskd, SABnzbd, qBit
+---------------------------+
              |
              +---> [ Plex Media Server ]
              +---> [ slskd / Soulseek ]
              +---> [ SABnzbd / Usenet ]
              +---> [ qBittorrent ]
```

#### Tier 1: Public Gateway (`trackseerr-gateway`)
- **Role**: Sits on the reverse proxy network (`proxynet`) to handle incoming web traffic from Plex Home users.
- **Zero Storage Mounts**: Does not mount `/music`, `/downloads`, or `/data`.
- **Zero Downloader Credentials**: Has no direct network access or credentials for slskd, SABnzbd, qBittorrent, Lidarr, or Newznab indexers.
- **Function**: Serves static web assets, executes public discovery queries (Apple Music, Deezer), and passes authenticated user requests to the core backend.

#### Tier 2: Internal Core Engine (`trackseerr-core`)
- **Role**: Sits on an isolated internal network (`internal-net`) with no public port exposures.
- **Storage Mounts**: Mounts `/data` (SQLite database), `/music` (Plex music library), and `/downloads` (download client staging).
- **Service Peering**: Communicates directly with local download clients, indexers, and Plex Media Server.
- **Function**: Executes scheduled playlist sync loops, monitors the download queue, runs the Mutagen audio inspection pipeline, renames files via the token template engine, performs atomic file moves, and triggers Plex library refreshes.

#### Hardened Compose Example (`docker-compose.hardened.yml`)

```yaml
version: '3.8'

services:
  trackseerr-gateway:
    image: ghcr.io/ronfburgundy/trackseerr:latest
    container_name: trackseerr-gateway
    restart: unless-stopped
    ports:
      - "5250:5250"
    environment:
      - ROLE=gateway
      - TRACKSEERR_CORE_URL=http://trackseerr-core:5251
      - PORT=5250
      - PUID=1000
      - PGID=1000
      - UMASK=022
      - TZ=Etc/UTC
      - LOG_LEVEL=INFO
    networks:
      - proxynet
      - internal-net

  trackseerr-core:
    image: ghcr.io/ronfburgundy/trackseerr:latest
    container_name: trackseerr-core
    restart: unless-stopped
    expose:
      - "5251"
    volumes:
      - ./data:/data
      - /path/to/music:/music
      - /path/to/downloads:/downloads
    environment:
      - ROLE=core
      - PORT=5251
      - PUID=1000
      - PGID=1000
      - UMASK=022
      - TZ=Etc/UTC
      - PLEX_URL=http://192.168.1.100:32400
      - PLEX_TOKEN=your_plex_token_here
      - PLEX_MUSIC_SECTION=Music
      - PLEX_VERIFY_SSL=1
      - SECONDS_TO_WAIT=14400
      - SEARCH_SIMILARITY_THRESHOLD=0.9
      - LOG_LEVEL=INFO
    networks:
      - internal-net

networks:
  proxynet:
    name: proxynet
    driver: bridge
  internal-net:
    name: trackseerr-internal-net
    internal: true
```

---

## Media Management and File Organization Pipeline

When using native download clients (slskd, SABnzbd, qBittorrent), TrackSeerr handles media management directly without requiring Lidarr.

```
[ Active Download Client ]
           |
           | (File completed)
           v
[ /downloads Staging ]
           |
           v
[ Mutagen Tag Inspection ] ----> Extracts codec, bitrate, sample rate, bit depth,
           |                     artist, album, disc, track numbers
           v
[ Token Template Engine ] -----> Renders destination path with conditional blocks
           |
           v
[ Path Collision Check ] ------> Resolves conflicting files (e.g. Track (1).flac)
           |
           v
[ Safe Atomic File Move ] -----> Cross-device safe move (.tmp staging -> os.replace)
           |
           v
[ /music Target Folder ]
           |
           v
[ Plex Library Refresh Ping ] -> Triggers Plex section refresh via PlexAPI
```

### 1. Download Monitoring
The `AcquisitionWorker` polls active downloads every 5 seconds across configured download clients. It tracks download hashes, completion percentages, transfer rates, and terminal statuses (`downloading`, `completed`, `failed`).

### 2. Audio Inspection via Mutagen
Completed audio files are parsed using the Mutagen audio library. TrackSeerr extracts:
- Container & Codec: FLAC, MP3 (ID3v2), MP4/M4A/ALAC, Ogg Opus, Ogg Vorbis, WAV.
- Technical Stream Attributes: Sample rate (Hz/kHz), bit depth (16-bit, 24-bit), bitrate (kbps), duration.
- Tags: Track title, track number, total tracks, disc number, total discs, album title, artist, album artist, release year.

### 3. Path Calculation and Arr Token Engine
Destination file paths are generated dynamically by evaluating user-defined naming templates against the extracted metadata.

### 4. Collision Detection and Resolution
Before any file operation, `resolve_collision` checks if the calculated destination path already exists on disk. If a collision is found, TrackSeerr safely appends an incrementing numeric counter (`Title (1).flac`, `Title (2).flac`) rather than overwriting existing tracks.

### 5. Cross-Device Safe Atomic Move
Filesystems often separate `/downloads` (fast NVMe scratch disk) and `/music` (spinning disk storage array). Standard `os.rename` fails across different filesystem mount points.
TrackSeerr's `safe_atomic_move`:
- On the same filesystem: Uses `os.replace` for instant atomic relocation.
- Across different filesystems: Copies the file to a hidden temporary file in the destination folder (`.tmp_filename_pid_timestamp`), flushes data to disk, atomically replaces the temporary file onto the final path using `os.replace`, and unlinks the source file. This guarantees that Plex Media Server never scans half-copied, incomplete audio files.

### 6. Plex Library Notification
Once files are successfully imported, TrackSeerr signals Plex Media Server via its REST API to perform a partial or section-level scan on the configured music section.

---

## Token Template Naming Engine

TrackSeerr implements an Arr-grade token replacement engine with conditional block evaluation.

### Supported Tokens

| Token | Description | Example Output |
|---|---|---|
| `{Artist Name}` | Standard artist name | `Daft Punk` |
| `{Artist CleanName}` | Artist name with leading articles stripped | `Beatles` (from `The Beatles`) |
| `{Artist Disambiguation}` | Artist disambiguation tag | `UK electronic duo` |
| `{Album Title}` | Full album title | `Random Access Memories` |
| `{Album CleanTitle}` | Clean album title without punctuation issues | `Random Access Memories` |
| `{Album Disambiguation}` | Album disambiguation tag | `10th Anniversary Edition` |
| `{Release Year}` | Album release year | `2013` |
| `{Original Release Year}` | Original release year for remasters/reissues | `2013` |
| `{Album Type}` | Release format type | `Album`, `EP`, `Single` |
| `{track:00}` | Zero-padded 2-digit track number | `01`, `09`, `12` |
| `{track:0}` | Unpadded track number | `1`, `9`, `12` |
| `{Track Title}` | Song or track title | `Get Lucky` |
| `{Track CleanTitle}` | Clean track title | `Get Lucky` |
| `{Medium Format}` | Disc medium descriptor | `CD`, `Vinyl`, `Digital` |
| `{Medium Title}` | Multi-disc title | `Disc 1` |
| `{medium:00}` / `{disc:00}` | Zero-padded 2-digit disc number | `01`, `02` |
| `{medium:0}` / `{disc:0}` | Unpadded disc number | `1`, `2` |
| `{Quality Full}` | Full audio quality summary | `FLAC 24bit 96kHz`, `MP3 320kbps` |
| `{MediaInfo AudioCodec}` | Audio codec name | `FLAC`, `MP3`, `AAC`, `ALAC`, `Opus` |
| `{MediaInfo BitDepth}` | Bit depth | `16bit`, `24bit` |
| `{MediaInfo SampleRate}` | Audio sample rate | `44.1kHz`, `96kHz`, `192kHz` |
| `{MediaInfo Bitrate}` | Audio bitrate | `320kbps`, `256kbps` |

### Conditional Blocks Syntax

Conditional blocks are wrapped in brackets with curly braces: `{[ ... ]}`.
Text and tokens inside a conditional block are included only if **all** tokens inside the block resolve to non-empty values. If any token inside the block is missing or empty, the entire block (including surrounding spaces or punctuation inside the brackets) is omitted.

- Example Template: `{track:00} - {Track Title}{[ (Quality Full)]}`
  - If quality is known: `01 - Get Lucky (FLAC 24bit 96kHz).flac`
  - If quality is empty: `01 - Get Lucky.flac`
- Example Template: `{Album Title} ({Release Year}){[ - Album Type]}`
  - With album type: `Discovery (2001) - Album`
  - Without album type: `Discovery (2001)`

### Presets

TrackSeerr includes three pre-configured naming presets:

#### 1. Lidarr Standard
- Artist Folder: `{Artist Name}`
- Album Folder: `{Album Title} ({Release Year}){[ - Album Type]}`
- Track Format: `{track:00} - {Track Title}{[ (Quality Full)]}`
- Compilation Track: `{track:00} - {Artist Name} - {Track Title}{[ (Quality Full)]}`
- Multi-Disc Folder: `{Medium Format} {medium:00}`

#### 2. Clean Minimal
- Artist Folder: `{Artist CleanName}`
- Album Folder: `{Album CleanTitle} ({Release Year})`
- Track Format: `{track:00} - {Track CleanTitle}`
- Compilation Track: `{track:00} - {Artist CleanName} - {Track CleanTitle}`
- Multi-Disc Folder: `Disc {medium:0}`

#### 3. Audiophile / Detailed
- Artist Folder: `{Artist Name}`
- Album Folder: `{Album Title} ({Release Year}){[ - Album Type]}`
- Track Format: `{track:00} - {Track Title} [{MediaInfo AudioCodec} {MediaInfo BitDepth} {MediaInfo SampleRate}]`
- Compilation Track: `{track:00} - {Artist Name} - {Track Title} [{MediaInfo AudioCodec} {MediaInfo BitDepth} {MediaInfo SampleRate}]`
- Multi-Disc Folder: `{Medium Format} {medium:00}`

---

## Security Model and Defenses

TrackSeerr implements strict defenses to prevent common container and homelab vulnerabilities.

### 1. Server-Side Request Forgery (SSRF) Defense

TrackSeerr strictly validates all outbound network targets:

- **Third-Party Playlist URLs**:
  - Spotify input URLs are validated using regex patterns that restrict hostnames to `open.spotify.com`, forbid custom ports or embedded user credentials, and extract only the 22-character alphanumeric playlist identifier.
  - Deezer input URLs are validated using regex patterns that restrict hostnames to `deezer.com` and `www.deezer.com` and extract only numeric playlist IDs.
- **Image Proxy & Poster Fetching**:
  - Image URLs must use HTTPS and originate from trusted CDN domains (`.scdn.co`, `.spotifycdn.com`, `.dzcdn.net`).
  - Outbound image requests explicitly reject loopback addresses (`127.0.0.1`, `::1`), private LAN IP ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), and internal DNS domains (`.local`, `.internal`, `.lan`, `.home`).
- **Download Client and Indexer URLs**:
  - Validated by `is_safe_service_url`.
  - While private RFC 1918 addresses are permitted for local services (e.g. connecting to slskd or SABnzbd on your LAN), cloud metadata endpoints are strictly blocked (`169.254.169.254`, `metadata.google.internal`, `instance-data`).
  - Dangerous URL schemes (`file://`, `ftp://`, `gopher://`) and credentials embedded in authority blocks are rejected.

### 2. Path Traversal Containment

All file export, playlist save, and library file operations pass through `safe_data_path`:
- Resolves relative path segments (`../`) and normalizes paths.
- Asserts that the final destination path resides strictly within the designated target directory (`/data`, `/music`, or `/downloads`).
- Any attempt to escape the designated base directory raises a `ValueError` and terminates the request immediately.

### 3. Zero Subprocess Execution

TrackSeerr executes zero shell scripts, subprocesses, or CLI binaries from web routes. All operations are handled natively in Python using HTTP clients (Requests, HTTPX), SQLite drivers, and Mutagen. There are no command injection surfaces.

### 4. Least-Privilege Execution

The Docker container runs as a non-root user (`uid 1000`, `gid 1000` by default, or `PUID=99`, `PGID=100` on Unraid) and is based on `python:3.12-slim`. The container drops root privileges during entrypoint execution.

### 5. Feed and Webhook Protection

When TrackSeerr is exposed to broader networks, the `FEED_TOKEN` environment variable secures missing track feeds and webhook endpoints. Requests must supply this token via query parameter or authorization header.

---

## Acknowledgments and Open Source Foundations

TrackSeerr builds upon foundational work from the open source community:

- **rnagabhyrava/plex-playlist-sync**: Foundational playlist matching concepts and Plex library synchronization logic.
- **Overseerr**: Architectural inspiration for the discovery UI, user request workflow, quota limits, and approval lifecycle.
- **Lidarr and Sonarr (*arr Stack)**: Design patterns for token template naming, quality profiles, multi-client acquisition queues, and indexer integration.
- **Mutagen**: Fast, robust audio metadata and stream tag inspection across diverse media formats.
- **slskd**: Clean REST API daemon for Soulseek P2P, enabling surgical single-track and album discovery.
