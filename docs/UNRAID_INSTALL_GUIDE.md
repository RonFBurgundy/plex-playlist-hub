# Installing Plex Playlist Hub on Unraid

Deploying **Plex Playlist Hub** on Unraid takes less than 2 minutes. This guide walks you through grabbing the pre-configured Unraid XML template, setting up your Plex connection, and launching your web dashboard.

---

## Method 1: Instant XML Template (Recommended)

Recent versions of Unraid removed the manual *Template Repositories* URL field, so the fastest and easiest way to install custom containers is to fetch the XML template directly onto your Unraid flash drive.

### Step 1: Open the Unraid Terminal

In your Unraid web interface, click the **Terminal (`>_`)** icon in the upper-right corner of the top menu bar.

### Step 2: Grab the XML Template

Paste and run this single command in your Unraid terminal:

```bash
curl -o /boot/config/plugins/dockerMan/templates-user/my-plex-playlist-hub.xml \
  https://raw.githubusercontent.com/RonFBurgundy/plex-playlist-hub/main/unraid/plex-playlist-hub.xml
```

*(This saves our official template directly into your Unraid user templates folder.)*

### Step 3: Add the Container

1. In Unraid, navigate to the **Docker** tab.
2. Scroll to the bottom and click **Add Container**.
3. In the **Template** dropdown at the top, select **my-plex-playlist-hub**.
4. The template will automatically populate all ports, appdata volume paths, container icon, and configuration variables!

---

## Configuration Fields (Plain English)

| Setting | Default Value | What to Put Here |
| :--- | :--- | :--- |
| **Plex Server URL** | `http://192.168.1.100:32400` | **Required.** Your Plex server's local LAN IP address and port 32400. *(See warning below!)* |
| **Plex Token** | *(blank)* | **Recommended.** Your Plex admin `X-Plex-Token`. You can find this in any media item's XML view in Plex Web. |
| **Plex Music Section** | `Music` | The exact name of your music library in Plex. |
| **WebUI & API Port** | `5250` | Port used to access the web dashboard in your browser. Leave as `5250` unless you already use this port. |
| **AppData Storage** | `/mnt/user/appdata/plex-playlist-hub` | Where your database, sessions, and missing track exports are stored on your cache/array. |
| **Spotify Client ID / Secret** | *(blank)* | **Optional.** Leave completely blank to use the built-in **Keyless Web Scraper**! Only fill this in if you already have a Spotify developer app. |
| **Lidarr Server URL & API Key** | *(blank)* | **Optional.** Fill in if you want missing tracks monitored and downloaded automatically by Lidarr. |
| **Lidarr Feed Token** | *(blank)* | **Optional.** Any random password/token to secure your missing track RSS feeds. |

> [!WARNING]
> ### The #1 Mistake Everyone Makes
> Because Docker containers run in bridge networking mode, **`localhost` inside a container means the container itself, NOT your Unraid server**.
> 
> * ❌ **Incorrect**: `http://localhost:32400` or `http://127.0.0.1:32400`
> * ✅ **Correct**: `http://192.168.1.100:32400` (Use your Unraid server's actual LAN IP!)

---

### Step 4: Click Apply & Open WebUI

1. Click **Apply** at the bottom of the page. Unraid will download the container image and start it up.
2. Once complete, click the container icon on your **Docker** tab and select **WebUI** (or visit `http://YOUR-UNRAID-IP:5250` in your browser).
3. Click **Sign in with Plex** to link your Plex Home account!

---

## Method 2: Docker Compose on Unraid (Compose Manager)

If you prefer using the **Docker Compose Manager** community plugin on Unraid:

1. In Unraid, go to **Docker** &rarr; **Compose Manager** &rarr; **Add New Stack**.
2. Name the stack `plex-playlist-hub`.
3. Click **Edit Stack** and paste the following compose definition:

```yaml
services:
  plex-playlist-hub:
    image: ghcr.io/ronfburgundy/plex-playlist-hub:latest
    container_name: plex-playlist-hub
    restart: unless-stopped
    ports:
      - "5250:5250"
    volumes:
      - /mnt/user/appdata/plex-playlist-hub:/data
    environment:
      - PUID=99
      - PGID=100
      - UMASK=022
      - PORT=5250
      - PLEX_URL=http://192.168.1.100:32400 # Replace with your Unraid LAN IP
      - PLEX_TOKEN=your_plex_token_here
      - PLEX_MUSIC_SECTION=Music
      - PLEX_VERIFY_SSL=1
      - SECONDS_TO_WAIT=14400 # Sync every 4 hours
      - LOG_LEVEL=INFO
```

4. Click **Save Changes**, then click **Compose Up**.

---

## How to Find Your Plex Token

If you don't know your `X-Plex-Token`:

1. Open Plex Web in your browser (`http://YOUR-UNRAID-IP:32400/web`).
2. Navigate into your **Music** library and click any track or album.
3. Click the three dots menu (**...**) &rarr; **Get Info**.
4. In the bottom-left corner of the popup window, click **View XML**.
5. Look at the browser URL bar at the very end of the line: `&X-Plex-Token=XXXXXXXXXXXXXXXXXXXX`.
6. Copy that code and paste it into the **Plex Token** field in Unraid!

---

## Troubleshooting & FAQ

#### The WebUI is unreachable or logs show "unable to open database file"
This occurs if the host `/mnt/user/appdata/plex-playlist-hub` folder permissions do not match the container user. Plex Playlist Hub includes dynamic `PUID`/`PGID` permission mapping:
1. Ensure the template settings for `PUID` and `PGID` are set to `99` and `100` (standard Unraid `nobody:users`).
2. If the folder was previously created with root or different ownership, open the Unraid terminal and run:
   ```bash
   chown -R 99:100 /mnt/user/appdata/plex-playlist-hub
   chmod -R 775 /mnt/user/appdata/plex-playlist-hub
   ```
3. Restart the container. The database will initialize and the WebUI will be reachable at port 5250.

#### Can my family members use this too?
Yes! Anyone in your Plex Home can browse to `http://YOUR-UNRAID-IP:5250`, sign in with their own Plex account, and transfer their personal Spotify mixes or Liked Songs directly to their personal Plex profile.

#### How do I update to newer versions?
On your Unraid **Docker** tab, click **Check for Updates**, or turn on automatic updates via the Community Applications Auto-Update plugin. When a new release or weekly base security rebuild is published, Unraid will update it with 1 click.
