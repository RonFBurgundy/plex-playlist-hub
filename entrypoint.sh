#!/bin/sh
set -e

# Default PUID and PGID if not provided
PUID=${PUID:-1000}
PGID=${PGID:-1000}
UMASK=${UMASK:-022}

if [ "$PUID" = "0" ] || [ "$PGID" = "0" ]; then
    echo "ERROR: Running as root (PUID=0 or PGID=0) is strictly prohibited." >&2
    exit 1
fi

umask "$UMASK"

if [ "$(id -u)" = "0" ]; then
    # Ensure group exists with PGID
    if ! getent group "$PGID" >/dev/null 2>&1; then
        if getent group appgroup >/dev/null 2>&1; then
            groupmod -o -g "$PGID" appgroup 2>/dev/null || true
        else
            groupadd -o -g "$PGID" appgroup 2>/dev/null || true
        fi
    fi

    # Ensure user exists with PUID and PGID
    if id -u appuser >/dev/null 2>&1; then
        CURRENT_UID=$(id -u appuser 2>/dev/null || echo "")
        CURRENT_GID=$(id -g appuser 2>/dev/null || echo "")
        if [ "$CURRENT_UID" != "$PUID" ] || [ "$CURRENT_GID" != "$PGID" ]; then
            usermod -o -u "$PUID" -g "$PGID" appuser 2>/dev/null || true
        fi
    else
        useradd -o -u "$PUID" -g "$PGID" -d /home/appuser -m appuser 2>/dev/null || true
    fi

    # Ensure /config, /data, /music, and /downloads exist and adjust ownership
    mkdir -p /config /data /data/media/music /data/downloads /music /downloads
    chown "$PUID:$PGID" /config /data /data/media/music /data/downloads /music /downloads 2>/dev/null || true
    if [ -n "$(ls -A /config 2>/dev/null)" ]; then
        chown -R "$PUID:$PGID" /config 2>/dev/null || true
    fi
    if [ -n "$(ls -A /data 2>/dev/null)" ]; then
        chown -R "$PUID:$PGID" /data 2>/dev/null || true
    fi

    exec gosu "$PUID:$PGID" "$@"
fi

exec "$@"
