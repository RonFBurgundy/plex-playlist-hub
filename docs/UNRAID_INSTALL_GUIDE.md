# Installing TrackSeerr on Unraid

Deploying **TrackSeerr** on Unraid takes less than two minutes. This guide walks you through grabbing the pre-configured Unraid XML template, configuring storage paths and network options, and connecting your Plex server.

---

## Method 1: Instant XML Template (Recommended)

Recent versions of Unraid removed the manual Template Repositories field. The fastest way to install custom containers is to fetch the XML template directly into your Unraid user templates folder.

### Step 1: Open the Unraid Terminal

In your Unraid web interface, open the Unraid terminal from the top-right toolbar.

### Step 2: Download the XML Template

Run this command in the Unraid terminal:

```bash
curl -o /boot/config/plugins/dockerMan/templates-user/my-trackseerr.xml \
  https://raw.githubusercontent.com/RonFBurgundy/trackseerr/main/unraid/trackseerr.xml
```

This saves the official TrackSeerr template into your local templates directory.

### Step 3: Add the Container

1. In the Unraid web interface, go to the **Docker** tab.
2. Scroll to the bottom and click **Add Container**.
3. In the **Template** dropdown at the top, select **my-trackseerr**.
4. The template populates container ports, volume mappings, icons, and configuration variables.

---

## Storage Mounts & TRaSH Guides Volume Alignment

TrackSeerr aligns directly with **TRaSH Guides** standards to ensure instant atomic file moves (`os.replace`) and zero-copy hardlinks (`os.link`) for torrent seeding:

### Recommended TRaSH Guides Layout:
- **AppData Storage (`/config`)**: `/mnt/user/appdata/trackseerr` mapped to `/config` (stores SQLite database, secrets, and logs).
- **Unified Data Share (`/data`)**: `/mnt/user/data` mapped to `/data`.
  - **Music Library**: `/data/media/music` (organized tracks for Plex).
  - **Download Staging**: `/data/downloads` (transfers downloaded by slskd, SABnzbd, or qBittorrent).

Because both staging and library directories reside on the same `/data` container filesystem, TrackSeerr can link and move multi-gigabyte albums instantaneously without disk I/O bottlenecks or cross-device copy overhead.

---

## Configuration Fields

| Setting | Default Value | Description |
|---|---|---|
| **WebUI & API Port** | `5250` | Port used to access the web dashboard in your browser. |
| **AppData Storage** | `/mnt/user/appdata/trackseerr` | Mapped to `/config`. Persistent directory for SQLite database, settings, and sessions. |
| **Data Storage (TRaSH)** | `/mnt/user/data` | Mapped to `/data`. Unified share holding library (`/data/media/music`) and staging (`/data/downloads`). |
| **Plex Server URL** | `http://192.168.1.100:32400` | Local LAN IP address and port 32400 of your Plex Media Server. |
| **Plex Token** | *(blank)* | Plex admin token (`X-Plex-Token`). Found in any Plex item XML view. |
| **Plex Music Section** | `Music` | Exact name of your music library section in Plex. |
| **Plex SSL Verification** | `1` | Set to `0` if using self-signed certificates. |
| **Application URL** | *(blank)* | Public URL (e.g. `https://music.example.com`) for reverse proxy redirects and notification link-backs. |
| **Feed Token** | *(blank)* | Optional: Secret key to protect RSS feeds and webhooks. |
| **PUID / PGID** | `99` / `100` | Unraid nobody:users permissions for file compatibility. |
| **Umask** | `022` | File creation permissions. |

> [!TIP]
> **Lidarr & Acquisition Configuration in WebUI**:
> Lidarr connection URL, API key, auto-search triggers, paced trickle rate, batch sizes, automated trickle schedules, download clients, and indexers are configured dynamically directly within the **WebUI -> Settings** panel, eliminating the need to manage dozens of Docker template variables.

### Remote Access and Reverse Proxies
When exposing TrackSeerr to the internet through Cloudflare Tunnels, Nginx, Traefik, or Caddy:
1. Configure **Application URL** (`APPLICATION_URL`) with your full public domain (e.g., `https://music.example.com`). This ensures Plex OAuth sign-in redirects and notification links resolve to your public endpoint.
2. For internet exposure, using the hardened Two-Tier DMZ topology (`ROLE=gateway` in DMZ, `ROLE=core` on internal LAN) is strongly recommended over exposing a single `all-in-one` container. See [Architecture and Security](file:///home/ron/workspaces/trackseerr/docs/ARCHITECTURE_AND_SECURITY.md) for architecture details.

Important note regarding container networking:
Because Docker containers run in bridge networking mode, `localhost` refers to the container itself, not the Unraid host. Always use your Unraid server's actual LAN IP address (for example, `http://192.168.1.100:32400`) rather than `http://localhost:32400`.

---

## Token Naming Templates

When using TrackSeerr's native acquisition engine, you can customize directory structures and audio file names in **Settings** -> **Media Management**.

TrackSeerr uses an Arr-style token template engine:

- **Artist Folder Format**: `{Artist Name}` or `{Artist CleanName}`
- **Album Folder Format**: `{Album Title} ({Release Year}){[ - Album Type]}`
- **Track Format**: `{track:00} - {Track Title}{[ (Quality Full)]}`
- **Multi-Disc Folder Format**: `{Medium Format} {medium:00}`

### Available Presets
- **Lidarr Standard**: Matches default Lidarr folder and file formatting with optional quality suffixes.
- **Clean Minimal**: Omits leading English articles (e.g. "Beatles" instead of "The Beatles") and strips format tags.
- **Audiophile / Detailed**: Includes codec, bit depth, and sample rate tags (e.g. `[FLAC 24bit 96kHz]`).

### Conditional Blocks
Brackets with curly braces `{[ ... ]}` are conditional blocks. Text inside the block is included only if all tokens within it are present. For example, `{[ (Quality Full)]}` appends ` (FLAC 24bit 96kHz)` when audio stream info is detected, and leaves no trailing spaces when empty.

---

## Step 4: Launch and Initial Login

1. Click **Apply** at the bottom of the container settings page. Unraid will pull the image and start the container.
2. In the Docker tab, click the TrackSeerr icon and choose **WebUI**, or browse to `http://<unraid-ip>:5250`.
3. Click **Sign in with Plex** to link your Plex account.

---

## Method 2: Docker Compose on Unraid

If you use the Docker Compose Manager plugin on Unraid:

1. Go to **Docker** -> **Compose Manager** -> **Add New Stack**.
2. Name the stack `trackseerr`.
3. Click **Edit Stack** and paste the following configuration:

```yaml
services:
  trackseerr:
    image: ghcr.io/ronfburgundy/trackseerr:latest
    container_name: trackseerr
    restart: unless-stopped
    ports:
      - "5250:5250"
    volumes:
      - /mnt/user/appdata/trackseerr:/data
      # Optional: uncomment if using native acquisition drivers instead of Lidarr
      # - /mnt/user/data/media/music:/music
      # - /mnt/user/data/downloads:/downloads
    environment:
      - PUID=99
      - PGID=100
      - UMASK=022
      - ROLE=all-in-one
      - PORT=5250
      - APPLICATION_URL=https://music.example.com  # Optional: public reverse proxy URL
      - PLEX_URL=http://192.168.1.100:32400
      - PLEX_TOKEN=your_plex_token_here
      - PLEX_MUSIC_SECTION=Music
      - PLEX_VERIFY_SSL=1
      - SECONDS_TO_WAIT=14400
      - LOG_LEVEL=INFO
```

4. Click **Save Changes**, then click **Compose Up**.

---

## Finding Your Plex Token

To locate your `X-Plex-Token`:

1. Open Plex Web in your browser (`http://<unraid-ip>:32400/web`).
2. Go to your **Music** library and select any track or album.
3. Click the menu button (three dots) and select **Get Info**.
4. In the lower-left corner of the dialog, click **View XML**.
5. In the browser URL bar, locate the token at the end of the query string: `&X-Plex-Token=XXXXXXXXXXXXXXXXXXXX`.
6. Copy this string into the **Plex Token** field in your TrackSeerr configuration.

---

## Troubleshooting

### WebUI unreachable or permission errors on database
If logs report an inability to write to the SQLite database:
1. Confirm that `PUID` is set to `99` and `PGID` is set to `100` (the standard Unraid `nobody:users` IDs).
2. If the appdata directory was created by root, fix ownership from the Unraid terminal:
   ```bash
   chown -R 99:100 /mnt/user/appdata/trackseerr
   chmod -R 775 /mnt/user/appdata/trackseerr
   ```
3. Restart the container.

### Family user access
Plex Home users can navigate to `http://<unraid-ip>:5250`, sign in with their Plex credentials, submit music requests, and sync playlists directly into their Plexamp profiles. Administrators can manage quotas and approve requests in the Admin panel.

### Container updates
On the Unraid Docker tab, click **Check for Updates**, or enable automated updates through Community Applications Auto-Update. When new images are released, Unraid updates the container with a single click.
