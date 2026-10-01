"""SQLite persistence engine for plex-playlist-sync with WAL mode and migrations."""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from plex_playlist_sync.models import Playlist, Track


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
                conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
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
                    self.conn.execute(
                        """
                        INSERT INTO missing_tracks (playlist_id, title, artist, album, url)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (p_id, str(title), str(artist), str(album), str(url)),
                    )
            self.conn.commit()

    def get_missing_tracks(
        self, playlist_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            if playlist_id is not None:
                cur = self.conn.execute(
                    """
                    SELECT id, playlist_id, title, artist, album, url, created_at
                    FROM missing_tracks
                    WHERE playlist_id = ?
                    ORDER BY id ASC
                    """,
                    (str(playlist_id),),
                )
            else:
                cur = self.conn.execute(
                    """
                    SELECT id, playlist_id, title, artist, album, url, created_at
                    FROM missing_tracks
                    ORDER BY id ASC
                    """
                )
            return [dict(row) for row in cur.fetchall()]

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
