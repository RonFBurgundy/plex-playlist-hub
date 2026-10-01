#!/bin/sh
set -e

# Default PUID and PGID if not provided
PUID=${PUID:-1000}
PGID=${PGID:-1000}
UMASK=${UMASK:-022}

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

    # Ensure /data exists and adjust ownership
    mkdir -p /data
    chown "$PUID:$PGID" /data 2>/dev/null || true
    if [ -n "$(ls -A /data 2>/dev/null)" ]; then
        chown -R "$PUID:$PGID" /data 2>/dev/null || true
    fi

    exec gosu "$PUID:$PGID" "$@"
fi

exec "$@"
