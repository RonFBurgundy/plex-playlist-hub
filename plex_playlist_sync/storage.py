"""SQLite persistence engine for plex-playlist-sync with WAL mode and migrations."""

import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from plex_playlist_sync.models import (
    ActiveDownload,
    DownloadClientConfig,
    DownloadDriverType,
    DownloadStatus,
    IndexerConfig,
    MusicRequest,
    Playlist,
    RequestStatus,
    Track,
)


class Database:
    """Thread-safe SQLite database wrapper with WAL mode, foreign keys, and migrations."""

    def __init__(self, db_path: Union[str, Path] = "/data/playlists.db") -> None:
        if str(db_path) == ":memory:":
            self.db_path: Union[str, Path] = ":memory:"
        else:
            self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_connection()
        self._migrate()

    def _ensure_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            if self.db_path != ":memory:":
                assert isinstance(self.db_path, Path)
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                parent_dir = self.db_path.parent
                if not os.access(parent_dir, os.W_OK):
                    uid = os.getuid() if hasattr(os, "getuid") else "N/A"
                    gid = os.getgid() if hasattr(os, "getgid") else "N/A"
                    raise PermissionError(
                        f"Database directory '{parent_dir}' is not writable (UID {uid}, GID {gid}). "
                        f"Please verify permissions on your appdata volume or configure PUID/PGID."
                    )
                if self.db_path.exists() and not os.access(self.db_path, os.W_OK):
                    uid = os.getuid() if hasattr(os, "getuid") else "N/A"
                    gid = os.getgid() if hasattr(os, "getgid") else "N/A"
                    raise PermissionError(
                        f"Database file '{self.db_path}' exists but is not writable (UID {uid}, GID {gid}). "
                        f"Please verify permissions on your appdata volume."
                    )
                try:
                    conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                except sqlite3.OperationalError as e:
                    uid = os.getuid() if hasattr(os, "getuid") else "N/A"
                    gid = os.getgid() if hasattr(os, "getgid") else "N/A"
                    raise sqlite3.OperationalError(
                        f"Failed to open SQLite database at '{self.db_path}': {e}. "
                        f"Ensure directory '{parent_dir}' is writable by user UID {uid} / GID {gid}."
                    ) from e
            else:
                conn = sqlite3.connect(":memory:", check_same_thread=False)

            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA busy_timeout = 5000;")
            self._conn = conn
        return self._conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._ensure_connection()

    def __enter__(self) -> "Database":
        self._ensure_connection()
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None

    # -------------------------------------------------------------------------
    # Migrations
    # -------------------------------------------------------------------------

    def _migrate(self) -> None:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
                )
                """
            )
            cur.execute("SELECT MAX(version) FROM schema_migrations")
            row = cur.fetchone()
            current_version = row[0] if (row and row[0] is not None) else 0

            migrations = [
                (1, self._migration_v1),
                (2, self._migration_v2),
                (3, self._migration_v3),
                (4, self._migration_v4),
                (5, self._migration_v5),
                (6, self._migration_v6),
                (7, self._migration_v7),
                (8, self._migration_v8),
            ]

            for version, migration_fn in migrations:
                if current_version < version:
                    migration_fn(cur)
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (?)",
                        (version,),
                    )
            self.conn.commit()

    def _migration_v1(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                email TEXT,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS playlists (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                service TEXT NOT NULL DEFAULT 'spotify',
                description TEXT NOT NULL DEFAULT '',
                poster_url TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_synced_at TEXT,
                sync_status TEXT NOT NULL DEFAULT 'never_synced',
                created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS playlist_targets (
                playlist_id TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                PRIMARY KEY (playlist_id, user_id)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_playlist_targets_user ON playlist_targets(user_id)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS missing_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_missing_tracks_playlist ON missing_tracks(playlist_id)"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
                data TEXT NOT NULL DEFAULT '{}',
                expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)"
        )

    def _migration_v2(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            ALTER TABLE playlists ADD COLUMN creator_id TEXT REFERENCES users(id)
            """
        )

    def _migration_v3(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            ALTER TABLE playlists ADD COLUMN tracks_json TEXT
            """
        )

    def _migration_v4(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS match_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_title TEXT NOT NULL,
                source_artist TEXT NOT NULL,
                plex_rating_key TEXT NOT NULL,
                plex_title TEXT NOT NULL,
                plex_artist TEXT NOT NULL,
                created_by TEXT REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                UNIQUE(source_title, source_artist)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_match_overrides_lookup ON match_overrides(source_title, source_artist)"
        )

    def _migration_v5(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            ALTER TABLE missing_tracks ADD COLUMN lidarr_status TEXT NOT NULL DEFAULT 'unmonitored'
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_missing_tracks_lidarr_status ON missing_tracks(lidarr_status)"
        )

    def _migration_v6(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS music_requests (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                item_type TEXT NOT NULL,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT,
                cover_url TEXT,
                preview_url TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                release_date TEXT,
                foreign_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_user ON music_requests(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_status ON music_requests(status)")

    def _migration_v7(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS media_management_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                artist_folder_format TEXT NOT NULL DEFAULT '{Artist Name}',
                album_folder_format TEXT NOT NULL DEFAULT '{Album Title} ({Release Year}){[ - Album Type]}',
                standard_track_format TEXT NOT NULL DEFAULT '{track:00} - {Track Title}{[ (Quality Full)]}',
                compilation_track_format TEXT NOT NULL DEFAULT '{track:00} - {Artist Name} - {Track Title}{[ (Quality Full)]}',
                multi_disc_folder_format TEXT NOT NULL DEFAULT '{Medium Format} {medium:00}',
                root_folder_path TEXT NOT NULL DEFAULT '/music',
                colon_replacement_format TEXT NOT NULL DEFAULT ' - ',
                clean_artist_names INTEGER NOT NULL DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            """
            INSERT OR IGNORE INTO media_management_settings (id) VALUES (1);
            """
        )

    def _migration_v8(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS download_clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                driver_type TEXT NOT NULL,
                host_url TEXT NOT NULL,
                api_key TEXT,
                username TEXT,
                password TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 1,
                extra_settings_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS indexers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                indexer_type TEXT NOT NULL,
                host_url TEXT NOT NULL,
                api_key TEXT,
                categories TEXT NOT NULL DEFAULT '3000,3010,3020,3030,3040',
                enabled INTEGER NOT NULL DEFAULT 1,
                priority INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS active_downloads (
                id TEXT PRIMARY KEY,
                request_id TEXT,
                client_id TEXT NOT NULL,
                download_hash TEXT,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                item_type TEXT NOT NULL DEFAULT 'track',
                status TEXT NOT NULL DEFAULT 'queued',
                progress REAL NOT NULL DEFAULT 0.0,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                source_path TEXT,
                target_path TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (client_id) REFERENCES download_clients(id) ON DELETE CASCADE,
                FOREIGN KEY (request_id) REFERENCES music_requests(id) ON DELETE SET NULL
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_downloads_status ON active_downloads(status);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_downloads_client ON active_downloads(client_id);"
        )

    # -------------------------------------------------------------------------
    # Users CRUD
    # -------------------------------------------------------------------------

    def upsert_user(
        self,
        user_id: str,
        username: str,
        email: Optional[str] = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        uid = str(user_id)
        uname = str(username)
        admin_val = 1 if is_admin else 0
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO users (id, username, email, is_admin, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    username = excluded.username,
                    email = excluded.email,
                    is_admin = excluded.is_admin,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (uid, uname, email, admin_val),
            )
            self.conn.commit()
        user = self.get_user(uid)
        if user is None:
            raise RuntimeError(f"Failed to upsert user {uid}")
        return user

    def get_user(self, user_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT id, username, email, is_admin, created_at, updated_at FROM users WHERE id = ?",
                (str(user_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["is_admin"] = bool(d["is_admin"])
            return d

    def list_users(self) -> list[dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT id, username, email, is_admin, created_at, updated_at FROM users ORDER BY username ASC"
            )
            results = []
            for row in cur.fetchall():
                d = dict(row)
                d["is_admin"] = bool(d["is_admin"])
                results.append(d)
            return results

    def delete_user(self, user_id: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM users WHERE id = ?",
                (str(user_id),),
            )
            self.conn.commit()
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Playlists CRUD
    # -------------------------------------------------------------------------

    def upsert_playlist(
        self,
        playlist_id: Union[str, Playlist],
        name: Optional[str] = None,
        service: str = "spotify",
        description: str = "",
        poster_url: str = "",
        enabled: bool = True,
        sync_status: str = "never_synced",
        creator_id: Optional[str] = None,
        tracks_json: Optional[str] = None,
    ) -> dict[str, Any]:
        if hasattr(playlist_id, "id") and hasattr(playlist_id, "name"):
            p_id = str(playlist_id.id)
            p_name = str(playlist_id.name)
            p_desc = str(getattr(playlist_id, "description", "") or "")
            p_poster = str(getattr(playlist_id, "poster", "") or "")
        else:
            p_id = str(playlist_id)
            p_name = str(name or "")
            p_desc = str(description or "")
            p_poster = str(poster_url or "")

        enabled_val = 1 if enabled else 0
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO playlists (id, name, service, description, poster_url, enabled, sync_status, creator_id, tracks_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    service = excluded.service,
                    description = excluded.description,
                    poster_url = excluded.poster_url,
                    enabled = excluded.enabled,
                    creator_id = COALESCE(excluded.creator_id, playlists.creator_id),
                    tracks_json = COALESCE(excluded.tracks_json, playlists.tracks_json),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (p_id, p_name, service, p_desc, p_poster, enabled_val, sync_status, creator_id, tracks_json),
            )
            self.conn.commit()
        playlist = self.get_playlist(p_id)
        if playlist is None:
            raise RuntimeError(f"Failed to upsert playlist {p_id}")
        return playlist

    def get_playlist(self, playlist_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT id, name, service, description, poster_url, enabled, creator_id, tracks_json,
                       last_synced_at, sync_status, created_at, updated_at
                FROM playlists
                WHERE id = ?
                """,
                (str(playlist_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["enabled"] = bool(d["enabled"])
            return d

    def list_playlists(
        self,
        user_id: Optional[str] = None,
        enabled_only: bool = False,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if user_id is not None:
                if enabled_only:
                    cur = self.conn.execute(
                        """
                        SELECT DISTINCT p.id, p.name, p.service, p.description, p.poster_url, p.enabled, p.creator_id, p.tracks_json,
                               p.last_synced_at, p.sync_status, p.created_at, p.updated_at
                        FROM playlists p
                        LEFT JOIN playlist_targets pt ON p.id = pt.playlist_id
                        WHERE (pt.user_id = ? OR p.creator_id = ?) AND p.enabled = 1
                        ORDER BY p.name ASC
                        """,
                        (str(user_id), str(user_id)),
                    )
                else:
                    cur = self.conn.execute(
                        """
                        SELECT DISTINCT p.id, p.name, p.service, p.description, p.poster_url, p.enabled, p.creator_id, p.tracks_json,
                               p.last_synced_at, p.sync_status, p.created_at, p.updated_at
                        FROM playlists p
                        LEFT JOIN playlist_targets pt ON p.id = pt.playlist_id
                        WHERE (pt.user_id = ? OR p.creator_id = ?)
                        ORDER BY p.name ASC
                        """,
                        (str(user_id), str(user_id)),
                    )
            else:
                if enabled_only:
                    cur = self.conn.execute(
                        """
                        SELECT id, name, service, description, poster_url, enabled, creator_id, tracks_json,
                               last_synced_at, sync_status, created_at, updated_at
                        FROM playlists
                        WHERE enabled = 1
                        ORDER BY name ASC
                        """
                    )
                else:
                    cur = self.conn.execute(
                        """
                        SELECT id, name, service, description, poster_url, enabled, creator_id, tracks_json,
                               last_synced_at, sync_status, created_at, updated_at
                        FROM playlists
                        ORDER BY name ASC
                        """
                    )

            results = []
            for row in cur.fetchall():
                d = dict(row)
                d["enabled"] = bool(d["enabled"])
                results.append(d)
            return results

    def delete_playlist(self, playlist_id: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM playlists WHERE id = ?",
                (str(playlist_id),),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def set_playlist_enabled(self, playlist_id: str, enabled: bool) -> bool:
        p_id = str(playlist_id)
        enabled_val = 1 if enabled else 0
        with self._lock:
            cur = self.conn.execute(
                "UPDATE playlists SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (enabled_val, p_id),
            )
            self.conn.commit()
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Playlist Targets
    # -------------------------------------------------------------------------

    def set_playlist_targets(self, playlist_id: str, user_ids: list[str]) -> None:
        p_id = str(playlist_id)
        unique_uids = list(dict.fromkeys(str(uid) for uid in user_ids))
        with self._lock:
            self.conn.execute(
                "DELETE FROM playlist_targets WHERE playlist_id = ?",
                (p_id,),
            )
            for u_id in unique_uids:
                self.conn.execute(
                    "INSERT INTO playlist_targets (playlist_id, user_id) VALUES (?, ?)",
                    (p_id, u_id),
                )
            self.conn.commit()

    def get_playlist_targets(self, playlist_id: str) -> list[str]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT user_id FROM playlist_targets WHERE playlist_id = ? ORDER BY user_id ASC",
                (str(playlist_id),),
            )
            return [row["user_id"] for row in cur.fetchall()]

    # -------------------------------------------------------------------------
    # Sync Results & Missing Tracks
    # -------------------------------------------------------------------------

    def record_sync_result(
        self,
        playlist_id: str,
        status: str,
        missing_tracks: Optional[list[Union[Track, dict[str, Any]]]] = None,
    ) -> None:
        p_id = str(playlist_id)
        with self._lock:
            self.conn.execute(
                """
                UPDATE playlists
                SET sync_status = ?, last_synced_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (str(status), p_id),
            )
            # Preserve existing lidarr_status across sync cycles
            existing_lidarr_status: dict[tuple[str, str], str] = {}
            try:
                cur = self.conn.execute(
                    "SELECT title, artist, lidarr_status FROM missing_tracks WHERE playlist_id = ?",
                    (p_id,),
                )
                for r in cur.fetchall():
                    key = (str(r["title"]).strip().lower(), str(r["artist"]).strip().lower())
                    existing_lidarr_status[key] = str(r["lidarr_status"] or "unmonitored")
            except Exception:
                pass

            self.conn.execute(
                "DELETE FROM missing_tracks WHERE playlist_id = ?",
                (p_id,),
            )
            if missing_tracks:
                for item in missing_tracks:
                    if hasattr(item, "title") and hasattr(item, "artist"):
                        title = getattr(item, "title", "")
                        artist = getattr(item, "artist", "")
                        album = getattr(item, "album", "") or ""
                        url = getattr(item, "url", "") or ""
                    elif isinstance(item, dict):
                        title = item.get("title", "")
                        artist = item.get("artist", "")
                        album = item.get("album", "") or ""
                        url = item.get("url", "") or ""
                    else:
                        continue
                    key = (str(title).strip().lower(), str(artist).strip().lower())
                    l_status = existing_lidarr_status.get(key, "unmonitored")
                    self.conn.execute(
                        """
                        INSERT INTO missing_tracks (playlist_id, title, artist, album, url, lidarr_status)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (p_id, str(title), str(artist), str(album), str(url), l_status),
                    )
            self.conn.commit()

    def get_missing_tracks(
        self, playlist_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            if playlist_id is not None:
                cur = self.conn.execute(
                    """
                    SELECT id, playlist_id, title, artist, album, url, lidarr_status, created_at
                    FROM missing_tracks
                    WHERE playlist_id = ?
                    ORDER BY id ASC
                    """,
                    (str(playlist_id),),
                )
            else:
                cur = self.conn.execute(
                    """
                    SELECT id, playlist_id, title, artist, album, url, lidarr_status, created_at
                    FROM missing_tracks
                    ORDER BY id ASC
                    """
                )
            return [dict(row) for row in cur.fetchall()]

    def update_missing_track_lidarr_status(self, track_id: int, status: str) -> bool:
        """Updates the Lidarr monitoring status for a specific missing track."""
        with self._lock:
            cur = self.conn.execute(
                "UPDATE missing_tracks SET lidarr_status = ? WHERE id = ?",
                (str(status), int(track_id)),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def update_missing_tracks_lidarr_status_bulk(self, track_ids: list[int], status: str) -> int:
        """Updates the Lidarr monitoring status for a list of track IDs."""
        if not track_ids:
            return 0
        with self._lock:
            placeholders = ",".join("?" for _ in track_ids)
            params = [str(status)] + [int(tid) for tid in track_ids]
            cur = self.conn.execute(
                f"UPDATE missing_tracks SET lidarr_status = ? WHERE id IN ({placeholders})",
                params,
            )
            self.conn.commit()
            return cur.rowcount

    # -------------------------------------------------------------------------
    # Sessions
    # -------------------------------------------------------------------------

    def create_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        data: Optional[dict[str, Any]] = None,
        expires_at: Optional[Union[str, datetime]] = None,
    ) -> dict[str, Any]:
        s_id = str(session_id)
        u_id = str(user_id) if user_id is not None else None
        data_str = json.dumps(data if data is not None else {})
        if isinstance(expires_at, datetime):
            exp_str = expires_at.isoformat()
        elif expires_at is not None:
            exp_str = str(expires_at)
        else:
            exp_str = None

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO sessions (session_id, user_id, data, expires_at, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    data = excluded.data,
                    expires_at = excluded.expires_at
                """,
                (s_id, u_id, data_str, exp_str),
            )
            self.conn.commit()
        session = self.get_session(s_id)
        if session is None:
            raise RuntimeError(f"Failed to create session {s_id}")
        return session

    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT session_id, user_id, data, expires_at, created_at
                FROM sessions
                WHERE session_id = ?
                """,
                (str(session_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            try:
                d["data"] = json.loads(d["data"])
            except (ValueError, TypeError):
                d["data"] = {}
            return d

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM sessions WHERE session_id = ?",
                (str(session_id),),
            )
            self.conn.commit()
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Match Overrides (Match Memory)
    # -------------------------------------------------------------------------

    def add_match_override(
        self,
        source_title: str,
        source_artist: str,
        plex_rating_key: str,
        plex_title: str,
        plex_artist: str,
        created_by: Optional[str] = None,
    ) -> dict[str, Any]:
        s_title = str(source_title).strip()
        s_artist = str(source_artist).strip()
        r_key = str(plex_rating_key).strip()
        p_title = str(plex_title).strip()
        p_artist = str(plex_artist).strip()
        c_by = str(created_by) if created_by else None

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO match_overrides (source_title, source_artist, plex_rating_key, plex_title, plex_artist, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(source_title, source_artist) DO UPDATE SET
                    plex_rating_key = excluded.plex_rating_key,
                    plex_title = excluded.plex_title,
                    plex_artist = excluded.plex_artist,
                    created_by = excluded.created_by,
                    created_at = CURRENT_TIMESTAMP
                """,
                (s_title, s_artist, r_key, p_title, p_artist, c_by),
            )
            self.conn.commit()
            cur = self.conn.execute(
                "SELECT id, source_title, source_artist, plex_rating_key, plex_title, plex_artist, created_by, created_at FROM match_overrides WHERE source_title = ? AND source_artist = ?",
                (s_title, s_artist),
            )
            row = cur.fetchone()
            return dict(row) if row else {}

    def get_match_override(
        self, source_title: str, source_artist: str
    ) -> Optional[dict[str, Any]]:
        s_title = str(source_title).strip()
        s_artist = str(source_artist).strip()
        with self._lock:
            cur = self.conn.execute(
                "SELECT id, source_title, source_artist, plex_rating_key, plex_title, plex_artist, created_by, created_at FROM match_overrides WHERE LOWER(source_title) = LOWER(?) AND LOWER(source_artist) = LOWER(?)",
                (s_title, s_artist),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_match_overrides(self) -> list[dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT id, source_title, source_artist, plex_rating_key, plex_title, plex_artist, created_by, created_at FROM match_overrides ORDER BY created_at DESC"
            )
            return [dict(r) for r in cur.fetchall()]

    def delete_match_override(self, override_id: int) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM match_overrides WHERE id = ?",
                (int(override_id),),
            )
            self.conn.commit()
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Music Requests CRUD
    # -------------------------------------------------------------------------

    def create_request(self, request: MusicRequest) -> dict[str, Any]:
        """Creates a new music request."""
        status_val = request.status.value if isinstance(request.status, RequestStatus) else str(request.status)
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO music_requests (
                    id, user_id, item_type, title, artist, album,
                    cover_url, preview_url, status, release_date, foreign_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    str(request.id),
                    str(request.user_id),
                    str(request.item_type),
                    str(request.title),
                    str(request.artist),
                    request.album,
                    request.cover_url,
                    request.preview_url,
                    status_val,
                    request.release_date,
                    request.foreign_id,
                ),
            )
            self.conn.commit()
        req = self.get_request(str(request.id))
        if req is None:
            raise RuntimeError(f"Failed to retrieve created request {request.id}")
        return req

    def get_request(self, request_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a single request by ID with user info joined."""
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT r.id, r.user_id, r.item_type, r.title, r.artist, r.album,
                       r.cover_url, r.preview_url, r.status, r.release_date, r.foreign_id,
                       r.created_at, r.updated_at, u.username
                FROM music_requests r
                LEFT JOIN users u ON r.user_id = u.id
                WHERE r.id = ?
                """,
                (str(request_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_requests(
        self, user_id: Optional[str] = None, status: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Lists requests filtered by user_id and/or status with username joined."""
        query = """
            SELECT r.id, r.user_id, r.item_type, r.title, r.artist, r.album,
                   r.cover_url, r.preview_url, r.status, r.release_date, r.foreign_id,
                   r.created_at, r.updated_at, u.username
            FROM music_requests r
            LEFT JOIN users u ON r.user_id = u.id
            WHERE 1=1
        """
        params: list[Any] = []
        if user_id:
            query += " AND r.user_id = ?"
            params.append(str(user_id))
        if status:
            status_val = status.value if hasattr(status, "value") else str(status)
            query += " AND r.status = ?"
            params.append(status_val)

        query += " ORDER BY r.created_at DESC"

        with self._lock:
            cur = self.conn.execute(query, params)
            return [dict(row) for row in cur.fetchall()]

    def update_request_status(
        self, request_id: str, status: Union[RequestStatus, str]
    ) -> bool:
        """Updates the status of a request."""
        status_val = status.value if isinstance(status, RequestStatus) else str(status)
        with self._lock:
            cur = self.conn.execute(
                """
                UPDATE music_requests
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status_val, str(request_id)),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def delete_request(self, request_id: str) -> bool:
        """Deletes a request by ID."""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM music_requests WHERE id = ?",
                (str(request_id),),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def find_matching_processing_requests(
        self, artist: str, album: Optional[str] = None, title: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Finds pending or processing requests matching an artist and optional album/title."""
        clean_artist = (artist or "").strip().lower()
        if not clean_artist:
            return []
        clean_album = (album or "").strip().lower() if album else None
        clean_title = (title or "").strip().lower() if title else None

        with self._lock:
            cur = self.conn.execute(
                """
                SELECT r.id, r.user_id, r.item_type, r.title, r.artist, r.album,
                       r.cover_url, r.preview_url, r.status, r.release_date, r.foreign_id,
                       r.created_at, r.updated_at, u.username
                FROM music_requests r
                LEFT JOIN users u ON r.user_id = u.id
                WHERE r.status IN ('processing', 'pending', 'approved')
                  AND LOWER(r.artist) = ?
                """,
                (clean_artist,),
            )
            rows = [dict(r) for r in cur.fetchall()]

        matches: list[dict[str, Any]] = []
        for r in rows:
            req_item_type = r.get("item_type", "")
            req_title = (r.get("title") or "").strip().lower()
            req_album = (r.get("album") or "").strip().lower()

            if clean_album and clean_title:
                if req_item_type == "album":
                    if req_title == clean_album or req_album == clean_album:
                        matches.append(r)
                elif req_item_type == "track":
                    if req_title == clean_title and (not req_album or req_album == clean_album):
                        matches.append(r)
            elif clean_album:
                if req_item_type == "album" and (req_title == clean_album or req_album == clean_album):
                    matches.append(r)
                elif req_item_type == "track" and req_album == clean_album:
                    matches.append(r)
            elif clean_title:
                if req_title == clean_title or req_album == clean_title:
                    matches.append(r)
            else:
                matches.append(r)
        return matches

    # -------------------------------------------------------------------------
    # Media Management Settings CRUD
    # -------------------------------------------------------------------------

    def get_media_management_settings(self) -> dict[str, Any]:
        """Retrieves media management settings (singleton row id=1)."""
        with self._lock:
            cur = self.conn.execute("SELECT * FROM media_management_settings WHERE id = 1")
            row = cur.fetchone()
            if not row:
                self.conn.execute("INSERT OR IGNORE INTO media_management_settings (id) VALUES (1)")
                self.conn.commit()
                cur = self.conn.execute("SELECT * FROM media_management_settings WHERE id = 1")
                row = cur.fetchone()
            res = dict(row)
            res["clean_artist_names"] = bool(res.get("clean_artist_names", 1))
            return res

    def update_media_management_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Updates media management settings (singleton row id=1)."""
        allowed_keys = {
            "artist_folder_format",
            "album_folder_format",
            "standard_track_format",
            "compilation_track_format",
            "multi_disc_folder_format",
            "root_folder_path",
            "colon_replacement_format",
            "clean_artist_names",
        }
        updates: dict[str, Any] = {}
        for k, v in settings.items():
            if k in allowed_keys and v is not None:
                if k == "clean_artist_names":
                    updates[k] = 1 if v else 0
                else:
                    updates[k] = str(v)

        if updates:
            set_clauses = [f"{k} = ?" for k in updates.keys()]
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            values = list(updates.values())
            query = f"UPDATE media_management_settings SET {', '.join(set_clauses)} WHERE id = 1"
            with self._lock:
                self.conn.execute(query, values)
                self.conn.commit()

        return self.get_media_management_settings()

    # -------------------------------------------------------------------------
    # Download Clients CRUD
    # -------------------------------------------------------------------------

    def create_download_client(
        self, client: Union[dict[str, Any], DownloadClientConfig]
    ) -> dict[str, Any]:
        """Creates or updates a download client in the database."""
        c = client.to_dict() if isinstance(client, DownloadClientConfig) else dict(client)
        cid = str(c.get("id") or "")
        name = str(c.get("name") or "")
        driver_type = str(c.get("driver_type") or "")
        host_url = str(c.get("host_url") or "")
        api_key = c.get("api_key")
        username = c.get("username")
        password = c.get("password")
        enabled = 1 if c.get("enabled", True) else 0
        priority = int(c.get("priority", 1))
        extra_settings_json = c.get("extra_settings_json")
        if isinstance(c.get("extra_settings"), dict):
            extra_settings_json = json.dumps(c["extra_settings"])

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO download_clients (
                    id, name, driver_type, host_url, api_key, username, password,
                    enabled, priority, extra_settings_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    driver_type = excluded.driver_type,
                    host_url = excluded.host_url,
                    api_key = excluded.api_key,
                    username = excluded.username,
                    password = excluded.password,
                    enabled = excluded.enabled,
                    priority = excluded.priority,
                    extra_settings_json = excluded.extra_settings_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    cid,
                    name,
                    driver_type,
                    host_url,
                    api_key,
                    username,
                    password,
                    enabled,
                    priority,
                    extra_settings_json,
                ),
            )
            self.conn.commit()
        return self.get_download_client(cid) or {}

    def get_download_client(self, client_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a single download client by ID."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM download_clients WHERE id = ?", (str(client_id),)
            )
            row = cur.fetchone()
            if not row:
                return None
            res = dict(row)
            res["enabled"] = bool(res.get("enabled", 1))
            res["priority"] = int(res.get("priority", 1))
            return res

    def list_download_clients(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        """Lists download clients, optionally filtering for enabled only."""
        with self._lock:
            if enabled_only:
                cur = self.conn.execute(
                    "SELECT * FROM download_clients WHERE enabled = 1 ORDER BY priority ASC, created_at ASC"
                )
            else:
                cur = self.conn.execute(
                    "SELECT * FROM download_clients ORDER BY priority ASC, created_at ASC"
                )
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["enabled"] = bool(r.get("enabled", 1))
            r["priority"] = int(r.get("priority", 1))
        return rows

    def update_download_client(
        self, client_id: str, updates: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Updates download client fields."""
        allowed = {
            "name",
            "driver_type",
            "host_url",
            "api_key",
            "username",
            "password",
            "enabled",
            "priority",
            "extra_settings_json",
        }
        filtered: dict[str, Any] = {}
        for k, v in updates.items():
            if k in allowed:
                if k == "enabled":
                    filtered[k] = 1 if v else 0
                elif k == "priority":
                    filtered[k] = int(v)
                else:
                    filtered[k] = v

        if not filtered:
            return self.get_download_client(client_id)

        set_clauses = [f"{k} = ?" for k in filtered.keys()]
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        values = list(filtered.values())
        values.append(str(client_id))

        with self._lock:
            cur = self.conn.execute(
                f"UPDATE download_clients SET {', '.join(set_clauses)} WHERE id = ?",
                values,
            )
            self.conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get_download_client(client_id)

    def delete_download_client(self, client_id: str) -> bool:
        """Deletes a download client by ID."""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM download_clients WHERE id = ?", (str(client_id),)
            )
            self.conn.commit()
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Indexers CRUD
    # -------------------------------------------------------------------------

    def create_indexer(
        self, indexer: Union[dict[str, Any], IndexerConfig]
    ) -> dict[str, Any]:
        """Creates or updates an indexer."""
        idx = indexer.to_dict() if isinstance(indexer, IndexerConfig) else dict(indexer)
        iid = str(idx.get("id") or "")
        name = str(idx.get("name") or "")
        indexer_type = str(idx.get("indexer_type") or "torznab")
        host_url = str(idx.get("host_url") or "")
        api_key = idx.get("api_key")
        categories = str(idx.get("categories") or "3000,3010,3020,3030,3040")
        enabled = 1 if idx.get("enabled", True) else 0
        priority = int(idx.get("priority", 1))

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO indexers (
                    id, name, indexer_type, host_url, api_key, categories,
                    enabled, priority, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    indexer_type = excluded.indexer_type,
                    host_url = excluded.host_url,
                    api_key = excluded.api_key,
                    categories = excluded.categories,
                    enabled = excluded.enabled,
                    priority = excluded.priority,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (iid, name, indexer_type, host_url, api_key, categories, enabled, priority),
            )
            self.conn.commit()
        return self.get_indexer(iid) or {}

    def get_indexer(self, indexer_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a single indexer by ID."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM indexers WHERE id = ?", (str(indexer_id),)
            )
            row = cur.fetchone()
            if not row:
                return None
            res = dict(row)
            res["enabled"] = bool(res.get("enabled", 1))
            res["priority"] = int(res.get("priority", 1))
            return res

    def list_indexers(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        """Lists indexers, optionally filtering for enabled only."""
        with self._lock:
            if enabled_only:
                cur = self.conn.execute(
                    "SELECT * FROM indexers WHERE enabled = 1 ORDER BY priority ASC, created_at ASC"
                )
            else:
                cur = self.conn.execute(
                    "SELECT * FROM indexers ORDER BY priority ASC, created_at ASC"
                )
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["enabled"] = bool(r.get("enabled", 1))
            r["priority"] = int(r.get("priority", 1))
        return rows

    def update_indexer(
        self, indexer_id: str, updates: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Updates indexer fields."""
        allowed = {"name", "indexer_type", "host_url", "api_key", "categories", "enabled", "priority"}
        filtered: dict[str, Any] = {}
        for k, v in updates.items():
            if k in allowed:
                if k == "enabled":
                    filtered[k] = 1 if v else 0
                elif k == "priority":
                    filtered[k] = int(v)
                else:
                    filtered[k] = v

        if not filtered:
            return self.get_indexer(indexer_id)

        set_clauses = [f"{k} = ?" for k in filtered.keys()]
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        values = list(filtered.values())
        values.append(str(indexer_id))

        with self._lock:
            cur = self.conn.execute(
                f"UPDATE indexers SET {', '.join(set_clauses)} WHERE id = ?",
                values,
            )
            self.conn.commit()
            if cur.rowcount == 0:
                return None
        return self.get_indexer(indexer_id)

    def delete_indexer(self, indexer_id: str) -> bool:
        """Deletes an indexer by ID."""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM indexers WHERE id = ?", (str(indexer_id),)
            )
            self.conn.commit()
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Active Downloads CRUD
    # -------------------------------------------------------------------------

    def create_active_download(
        self, download: Union[dict[str, Any], ActiveDownload]
    ) -> dict[str, Any]:
        """Creates or updates an active download record."""
        d = download.to_dict() if isinstance(download, ActiveDownload) else dict(download)
        did = str(d.get("id") or "")
        req_id = d.get("request_id")
        client_id = str(d.get("client_id") or "")
        download_hash = d.get("download_hash")
        title = str(d.get("title") or "")
        artist = str(d.get("artist") or "")
        item_type = str(d.get("item_type") or "track")
        status = str(d.get("status") or "queued")
        progress = float(d.get("progress") or 0.0)
        size_bytes = int(d.get("size_bytes") or 0)
        source_path = d.get("source_path")
        target_path = d.get("target_path")
        error_message = d.get("error_message")

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO active_downloads (
                    id, request_id, client_id, download_hash, title, artist,
                    item_type, status, progress, size_bytes, source_path,
                    target_path, error_message, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    request_id = excluded.request_id,
                    client_id = excluded.client_id,
                    download_hash = excluded.download_hash,
                    title = excluded.title,
                    artist = excluded.artist,
                    item_type = excluded.item_type,
                    status = excluded.status,
                    progress = excluded.progress,
                    size_bytes = excluded.size_bytes,
                    source_path = excluded.source_path,
                    target_path = excluded.target_path,
                    error_message = excluded.error_message,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    did,
                    req_id,
                    client_id,
                    download_hash,
                    title,
                    artist,
                    item_type,
                    status,
                    progress,
                    size_bytes,
                    source_path,
                    target_path,
                    error_message,
                ),
            )
            self.conn.commit()
        return self.get_active_download(did) or {}

    def get_active_download(self, download_id: str) -> Optional[dict[str, Any]]:
        """Retrieves active download by ID with client details joined."""
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT d.*, c.name AS client_name, c.driver_type AS client_driver_type
                FROM active_downloads d
                LEFT JOIN download_clients c ON d.client_id = c.id
                WHERE d.id = ?
                """,
                (str(download_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            res = dict(row)
            res["progress"] = float(res.get("progress") or 0.0)
            res["size_bytes"] = int(res.get("size_bytes") or 0)
            return res

    def list_active_downloads(
        self, statuses: Optional[list[str]] = None
    ) -> list[dict[str, Any]]:
        """Lists active downloads, optionally filtered by a list of statuses."""
        with self._lock:
            if statuses:
                placeholders = ", ".join(["?"] * len(statuses))
                cur = self.conn.execute(
                    f"""
                    SELECT d.*, c.name AS client_name, c.driver_type AS client_driver_type
                    FROM active_downloads d
                    LEFT JOIN download_clients c ON d.client_id = c.id
                    WHERE d.status IN ({placeholders})
                    ORDER BY d.created_at DESC
                    """,
                    [str(s).lower() for s in statuses],
                )
            else:
                cur = self.conn.execute(
                    """
                    SELECT d.*, c.name AS client_name, c.driver_type AS client_driver_type
                    FROM active_downloads d
                    LEFT JOIN download_clients c ON d.client_id = c.id
                    ORDER BY d.created_at DESC
                    """
                )
            rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["progress"] = float(r.get("progress") or 0.0)
            r["size_bytes"] = int(r.get("size_bytes") or 0)
        return rows

    def update_download_progress(
        self, download_id: str, progress: float, size_bytes: Optional[int] = None
    ) -> bool:
        """Updates download progress and optional size."""
        with self._lock:
            if size_bytes is not None:
                cur = self.conn.execute(
                    """
                    UPDATE active_downloads
                    SET progress = ?, size_bytes = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (float(progress), int(size_bytes), str(download_id)),
                )
            else:
                cur = self.conn.execute(
                    """
                    UPDATE active_downloads
                    SET progress = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (float(progress), str(download_id)),
                )
            self.conn.commit()
            return cur.rowcount > 0

    def update_download_status(
        self,
        download_id: str,
        status: str,
        error_message: Optional[str] = None,
        source_path: Optional[str] = None,
        target_path: Optional[str] = None,
    ) -> bool:
        """Updates status and paths / error for an active download."""
        updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        params: list[Any] = [str(status).lower()]
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        if source_path is not None:
            updates.append("source_path = ?")
            params.append(source_path)
        if target_path is not None:
            updates.append("target_path = ?")
            params.append(target_path)

        params.append(str(download_id))
        query = f"UPDATE active_downloads SET {', '.join(updates)} WHERE id = ?"
        with self._lock:
            cur = self.conn.execute(query, params)
            self.conn.commit()
            return cur.rowcount > 0

    def delete_active_download(self, download_id: str) -> bool:
        """Deletes an active download entry."""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM active_downloads WHERE id = ?", (str(download_id),)
            )
            self.conn.commit()
            return cur.rowcount > 0


