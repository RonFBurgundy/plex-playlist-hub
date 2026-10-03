"""SQLite persistence engine for plex-playlist-sync with WAL mode and migrations."""

import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from plex_playlist_sync.models import (
    ActiveDownload,
    BlocklistItem,
    DownloadClientConfig,
    DownloadDriverType,
    DownloadStatus,
    IndexerConfig,
    LibraryAlbum,
    LibraryArtist,
    LibraryCollection,
    LibraryFile,
    LibraryMode,
    LibraryTrack,
    MediaIssue,
    MusicRequest,
    NotificationChannel,
    NotificationChannelType,
    NotificationEvent,
    Playlist,
    QualityProfile,
    QualityProfileItem,
    RequestStatus,
    Track,
)


def clean_library_name(text: str) -> str:
    """Normalizes string for indexing and resilient comparison: lowercased, alphanumerics and single spaces."""
    if not text:
        return ""
    cleaned = re.sub(r"[^\w\s]", "", str(text).lower())
    return re.sub(r"\s+", " ", cleaned).strip()


class Database:
    """Thread-safe SQLite database wrapper with WAL mode, foreign keys, and migrations."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        if db_path is not None:
            if str(db_path) == ":memory:":
                self.db_path: Union[str, Path] = ":memory:"
            else:
                self.db_path = Path(db_path)
        else:
            if os.path.isdir("/config"):
                self.db_path = Path("/config/sync_db.sqlite")
            elif os.path.exists("/data/sync_db.sqlite"):
                self.db_path = Path("/data/sync_db.sqlite")
            else:
                self.db_path = (
                    Path("/config/sync_db.sqlite")
                    if os.path.isdir("/config")
                    else Path("/data/sync_db.sqlite")
                )
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
                (9, self._migration_v9),
                (10, self._migration_v10),
                (11, self._migration_v11),
                (12, self._migration_v12),
                (13, self._migration_v13),
                (14, self._migration_v14),
                (15, self._migration_v15),
                (16, self._migration_v16),
                (17, self._migration_v17),
                (18, self._migration_v18),
                (19, self._migration_v19),
                (20, self._migration_v20),
                (21, self._migration_v21),
                (22, self._migration_v22),
                (23, self._migration_v23),
                (24, self._migration_v24),
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
                root_folder_path TEXT NOT NULL DEFAULT '/data/media/music',
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

    def _migration_v9(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            ALTER TABLE media_management_settings ADD COLUMN staging_folder_path TEXT NOT NULL DEFAULT '/data/downloads'
            """
        )
        cur.execute(
            """
            ALTER TABLE media_management_settings ADD COLUMN import_mode TEXT NOT NULL DEFAULT 'move'
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS lidarr_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                url TEXT,
                api_key TEXT,
                auto_search INTEGER NOT NULL DEFAULT 1,
                root_folder TEXT,
                quality_profile_id INTEGER,
                metadata_profile_id INTEGER,
                trickle_rate_seconds REAL NOT NULL DEFAULT 3.0,
                trickle_batch_size INTEGER NOT NULL DEFAULT 25,
                auto_trickle INTEGER NOT NULL DEFAULT 0,
                auto_trickle_interval_minutes INTEGER NOT NULL DEFAULT 30,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            """
            INSERT OR IGNORE INTO lidarr_settings (id) VALUES (1);
            """
        )

    def _migration_v10(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS quality_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                cutoff TEXT NOT NULL,
                items_json TEXT NOT NULL,
                preferred_tags_json TEXT NOT NULL DEFAULT '[]',
                ignored_tags_json TEXT NOT NULL DEFAULT '[]',
                min_size_mb REAL,
                max_size_mb REAL,
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        cur.execute("SELECT COUNT(*) FROM quality_profiles")
        row = cur.fetchone()
        count = row[0] if (row and row[0] is not None) else 0
        if count == 0:
            # Seed Profile 1: Lossless (FLAC)
            p1_items = [
                {"quality": "FLAC 24bit", "allowed": True, "weight": 1000},
                {"quality": "FLAC 16bit", "allowed": True, "weight": 900},
                {"quality": "MP3 320", "allowed": False, "weight": 800},
                {"quality": "AAC 256", "allowed": False, "weight": 700},
                {"quality": "MP3 V0", "allowed": False, "weight": 600},
                {"quality": "MP3 192", "allowed": False, "weight": 500},
                {"quality": "MP3 V2", "allowed": False, "weight": 400},
                {"quality": "Unknown", "allowed": False, "weight": 100},
            ]
            cur.execute(
                """
                INSERT INTO quality_profiles (
                    id, name, cutoff, items_json, preferred_tags_json, ignored_tags_json,
                    min_size_mb, max_size_mb, is_default
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "profile-lossless",
                    "Lossless (FLAC)",
                    "FLAC 16bit",
                    json.dumps(p1_items),
                    json.dumps(["cd", "web", "vinyl", "remaster"]),
                    json.dumps(["live", "bootleg", "tribute", "karaoke"]),
                    None,
                    None,
                    1,
                ),
            )

            # Seed Profile 2: High Quality (Any)
            p2_items = [
                {"quality": "FLAC 24bit", "allowed": True, "weight": 1000},
                {"quality": "FLAC 16bit", "allowed": True, "weight": 900},
                {"quality": "MP3 320", "allowed": True, "weight": 800},
                {"quality": "AAC 256", "allowed": True, "weight": 700},
                {"quality": "MP3 V0", "allowed": True, "weight": 600},
                {"quality": "MP3 192", "allowed": False, "weight": 500},
                {"quality": "MP3 V2", "allowed": False, "weight": 400},
                {"quality": "Unknown", "allowed": False, "weight": 100},
            ]
            cur.execute(
                """
                INSERT INTO quality_profiles (
                    id, name, cutoff, items_json, preferred_tags_json, ignored_tags_json,
                    min_size_mb, max_size_mb, is_default
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "profile-high-quality",
                    "High Quality (Any)",
                    "FLAC 16bit",
                    json.dumps(p2_items),
                    json.dumps(["cd", "web"]),
                    json.dumps(["live", "bootleg"]),
                    None,
                    None,
                    0,
                ),
            )

            # Seed Profile 3: Standard MP3
            p3_items = [
                {"quality": "FLAC 24bit", "allowed": False, "weight": 1000},
                {"quality": "FLAC 16bit", "allowed": False, "weight": 900},
                {"quality": "MP3 320", "allowed": True, "weight": 800},
                {"quality": "MP3 V0", "allowed": True, "weight": 700},
                {"quality": "AAC 256", "allowed": True, "weight": 600},
                {"quality": "MP3 192", "allowed": True, "weight": 500},
                {"quality": "MP3 V2", "allowed": False, "weight": 400},
                {"quality": "Unknown", "allowed": False, "weight": 100},
            ]
            cur.execute(
                """
                INSERT INTO quality_profiles (
                    id, name, cutoff, items_json, preferred_tags_json, ignored_tags_json,
                    min_size_mb, max_size_mb, is_default
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "profile-standard-mp3",
                    "Standard MP3",
                    "MP3 320",
                    json.dumps(p3_items),
                    json.dumps([]),
                    json.dumps(["live", "bootleg"]),
                    None,
                    None,
                    0,
                ),
            )

    def _migration_v11(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            ALTER TABLE media_management_settings ADD COLUMN write_audio_tags INTEGER NOT NULL DEFAULT 1
            """
        )
        cur.execute(
            """
            ALTER TABLE media_management_settings ADD COLUMN embed_artwork INTEGER NOT NULL DEFAULT 1
            """
        )
        cur.execute(
            """
            ALTER TABLE media_management_settings ADD COLUMN save_cover_art_file INTEGER NOT NULL DEFAULT 1
            """
        )

    def _migration_v12(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_channels (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                channel_type TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                config_json TEXT NOT NULL DEFAULT '{}',
                events_json TEXT NOT NULL DEFAULT '["request_created","request_approved","request_rejected","download_started","item_available","download_failed"]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notification_channels_enabled ON notification_channels(enabled);
            """
        )

    def _migration_v13(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            "ALTER TABLE users ADD COLUMN permissions INTEGER NOT NULL DEFAULT 34"
        )
        cur.execute(
            "ALTER TABLE users ADD COLUMN request_limit_quota INTEGER"
        )
        cur.execute(
            "ALTER TABLE users ADD COLUMN request_limit_days INTEGER DEFAULT 7"
        )
        cur.execute(
            "UPDATE users SET permissions = permissions | 1 WHERE is_admin = 1"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS media_issues (
                id TEXT PRIMARY KEY,
                request_id TEXT REFERENCES music_requests(id) ON DELETE SET NULL,
                media_title TEXT NOT NULL,
                artist TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                problem_details TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_issues_status ON media_issues(status);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_issues_user ON media_issues(user_id);"
        )

    def _migration_v14(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            "ALTER TABLE music_requests ADD COLUMN quality_profile_id TEXT REFERENCES quality_profiles(id);"
        )
        cur.execute(
            "ALTER TABLE music_requests ADD COLUMN current_quality TEXT;"
        )
        cur.execute(
            "ALTER TABLE music_requests ADD COLUMN cutoff_met INTEGER NOT NULL DEFAULT 1;"
        )
        cur.execute(
            "ALTER TABLE media_management_settings ADD COLUMN delete_completed_transfers INTEGER NOT NULL DEFAULT 0;"
        )
        cur.execute(
            "ALTER TABLE media_management_settings ADD COLUMN enable_quality_upgrades INTEGER NOT NULL DEFAULT 1;"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_music_requests_cutoff ON music_requests(status, cutoff_met);"
        )

    def _migration_v15(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            "ALTER TABLE media_management_settings ADD COLUMN library_mode TEXT NOT NULL DEFAULT 'native';"
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS library_artists (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                clean_name TEXT NOT NULL,
                foreign_artist_id TEXT,
                path TEXT,
                monitored INTEGER NOT NULL DEFAULT 1,
                quality_profile_id TEXT REFERENCES quality_profiles(id),
                metadata_json TEXT,
                created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lib_artists_clean_name ON library_artists(clean_name);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lib_artists_foreign ON library_artists(foreign_artist_id);"
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS library_albums (
                id TEXT PRIMARY KEY,
                artist_id TEXT NOT NULL REFERENCES library_artists(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                clean_title TEXT NOT NULL,
                foreign_album_id TEXT,
                release_date TEXT,
                year INTEGER,
                album_type TEXT NOT NULL DEFAULT 'album',
                monitored INTEGER NOT NULL DEFAULT 1,
                path TEXT,
                cover_url TEXT,
                total_tracks INTEGER,
                created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lib_albums_artist ON library_albums(artist_id);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lib_albums_clean_title ON library_albums(clean_title);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lib_albums_foreign ON library_albums(foreign_album_id);"
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS library_tracks (
                id TEXT PRIMARY KEY,
                album_id TEXT NOT NULL REFERENCES library_albums(id) ON DELETE CASCADE,
                artist_id TEXT NOT NULL REFERENCES library_artists(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                clean_title TEXT NOT NULL,
                track_number INTEGER NOT NULL DEFAULT 1,
                disc_number INTEGER NOT NULL DEFAULT 1,
                duration_seconds REAL,
                monitored INTEGER NOT NULL DEFAULT 1,
                foreign_track_id TEXT,
                created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lib_tracks_album ON library_tracks(album_id);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lib_tracks_artist ON library_tracks(artist_id);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lib_tracks_clean_title ON library_tracks(clean_title);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lib_tracks_foreign ON library_tracks(foreign_track_id);"
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS library_files (
                id TEXT PRIMARY KEY,
                track_id TEXT NOT NULL REFERENCES library_tracks(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL UNIQUE,
                relative_path TEXT NOT NULL,
                codec TEXT NOT NULL,
                bitrate INTEGER,
                sample_rate INTEGER,
                bits_per_sample INTEGER,
                quality_name TEXT NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                cutoff_met INTEGER NOT NULL DEFAULT 1,
                date_added TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lib_files_track ON library_files(track_id);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lib_files_path ON library_files(file_path);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_lib_files_cutoff ON library_files(cutoff_met);"
        )

    def _migration_v16(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS general_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                application_url TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        cur.execute(
            "INSERT OR IGNORE INTO general_settings (id, application_url) VALUES (1, '');"
        )

    def _migration_v17(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS download_blocklist (
                id TEXT PRIMARY KEY,
                source_title TEXT NOT NULL,
                artist TEXT,
                album TEXT,
                release_guid TEXT,
                info_hash TEXT,
                protocol TEXT,
                indexer TEXT,
                reason TEXT,
                created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_blocklist_hash ON download_blocklist(info_hash);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_blocklist_title ON download_blocklist(source_title);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_blocklist_guid ON download_blocklist(release_guid);"
        )

        cur.execute("PRAGMA table_info(active_downloads);")
        columns = [row[1] for row in cur.fetchall()]
        if "track_id" not in columns:
            cur.execute(
                "ALTER TABLE active_downloads ADD COLUMN track_id TEXT REFERENCES library_tracks(id);"
            )
        if "album_id" not in columns:
            cur.execute(
                "ALTER TABLE active_downloads ADD COLUMN album_id TEXT REFERENCES library_albums(id);"
            )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_downloads_track ON active_downloads(track_id);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_active_downloads_album ON active_downloads(album_id);"
        )

    def _migration_v18(self, cur: sqlite3.Cursor) -> None:
        cur.execute("PRAGMA table_info(general_settings);")
        columns = [row[1] for row in cur.fetchall()]
        if "api_key" not in columns:
            cur.execute(
                "ALTER TABLE general_settings ADD COLUMN api_key TEXT NOT NULL DEFAULT '';"
            )

        cur.execute("SELECT api_key FROM general_settings WHERE id = 1")
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT OR IGNORE INTO general_settings (id, application_url, api_key) VALUES (1, '', ?)",
                (secrets.token_hex(16),),
            )
        elif not row[0]:
            cur.execute(
                "UPDATE general_settings SET api_key = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (secrets.token_hex(16),),
            )

    def _migration_v19(self, cur: sqlite3.Cursor) -> None:
        cur.execute("PRAGMA table_info(quality_profiles);")
        qp_cols = [row[1] for row in cur.fetchall()]
        if "custom_formats_json" not in qp_cols:
            cur.execute(
                "ALTER TABLE quality_profiles ADD COLUMN custom_formats_json TEXT;"
            )
        if "min_score" not in qp_cols:
            cur.execute(
                "ALTER TABLE quality_profiles ADD COLUMN min_score INTEGER;"
            )

        cur.execute("PRAGMA table_info(media_management_settings);")
        mm_cols = [row[1] for row in cur.fetchall()]
        if "seed_ratio_limit" not in mm_cols:
            cur.execute(
                "ALTER TABLE media_management_settings ADD COLUMN seed_ratio_limit REAL;"
            )
        if "seed_time_limit_minutes" not in mm_cols:
            cur.execute(
                "ALTER TABLE media_management_settings ADD COLUMN seed_time_limit_minutes INTEGER;"
            )

    def _migration_v20(self, cur: sqlite3.Cursor) -> None:
        cur.execute("PRAGMA table_info(media_management_settings);")
        mm_cols = [row[1] for row in cur.fetchall()]
        if "enrich_mbids" not in mm_cols:
            cur.execute(
                "ALTER TABLE media_management_settings ADD COLUMN enrich_mbids INTEGER NOT NULL DEFAULT 1;"
            )
        if "acoustid_api_key" not in mm_cols:
            cur.execute(
                "ALTER TABLE media_management_settings ADD COLUMN acoustid_api_key TEXT;"
            )
        if "mb_mirror_url" not in mm_cols:
            cur.execute(
                "ALTER TABLE media_management_settings ADD COLUMN mb_mirror_url TEXT NOT NULL DEFAULT 'https://api.brainzmash.org';"
            )

        cur.execute("PRAGMA table_info(library_artists);")
        art_cols = [row[1] for row in cur.fetchall()]
        if "mbid" not in art_cols:
            cur.execute("ALTER TABLE library_artists ADD COLUMN mbid TEXT;")
        if "image_url" not in art_cols:
            cur.execute("ALTER TABLE library_artists ADD COLUMN image_url TEXT;")
        if "banner_url" not in art_cols:
            cur.execute("ALTER TABLE library_artists ADD COLUMN banner_url TEXT;")
        if "bio" not in art_cols:
            cur.execute("ALTER TABLE library_artists ADD COLUMN bio TEXT;")
        if "genres" not in art_cols:
            cur.execute("ALTER TABLE library_artists ADD COLUMN genres TEXT;")
        if "country" not in art_cols:
            cur.execute("ALTER TABLE library_artists ADD COLUMN country TEXT;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lib_artists_mbid ON library_artists(mbid);")

        cur.execute("PRAGMA table_info(library_albums);")
        alb_cols = [row[1] for row in cur.fetchall()]
        if "mb_release_group_id" not in alb_cols:
            cur.execute("ALTER TABLE library_albums ADD COLUMN mb_release_group_id TEXT;")
        if "mb_release_id" not in alb_cols:
            cur.execute("ALTER TABLE library_albums ADD COLUMN mb_release_id TEXT;")
        if "genres" not in alb_cols:
            cur.execute("ALTER TABLE library_albums ADD COLUMN genres TEXT;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lib_albums_mb_rg ON library_albums(mb_release_group_id);")

        cur.execute("PRAGMA table_info(library_tracks);")
        trk_cols = [row[1] for row in cur.fetchall()]
        if "mb_recording_id" not in trk_cols:
            cur.execute("ALTER TABLE library_tracks ADD COLUMN mb_recording_id TEXT;")
        if "isrc" not in trk_cols:
            cur.execute("ALTER TABLE library_tracks ADD COLUMN isrc TEXT;")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lib_tracks_mb_rec ON library_tracks(mb_recording_id);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS library_collections (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                clean_name TEXT NOT NULL,
                summary TEXT,
                poster_url TEXT,
                monitored INTEGER NOT NULL DEFAULT 1,
                foreign_id TEXT,
                created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lib_collections_clean_name ON library_collections(clean_name);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS library_collection_albums (
                collection_id TEXT NOT NULL REFERENCES library_collections(id) ON DELETE CASCADE,
                album_id TEXT NOT NULL REFERENCES library_albums(id) ON DELETE CASCADE,
                order_index INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (collection_id, album_id)
            );
            """
        )

    def _migration_v21(self, cur: sqlite3.Cursor) -> None:
        cur.execute("PRAGMA table_info(media_management_settings);")
        mm_cols = [row[1] for row in cur.fetchall()]
        if "prefer_local_artwork" not in mm_cols:
            cur.execute(
                "ALTER TABLE media_management_settings ADD COLUMN prefer_local_artwork INTEGER NOT NULL DEFAULT 1;"
            )
        cur.execute(
            "UPDATE media_management_settings SET mb_mirror_url = 'https://api.brainzmash.cc' WHERE mb_mirror_url IN ('https://api.brainzmash.org', 'https://musicbrainz.org');"
        )

    def _migration_v22(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                source TEXT NOT NULL,
                message TEXT NOT NULL,
                details_json TEXT,
                created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            );
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_system_events_created_at ON system_events (created_at DESC);"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_system_events_type ON system_events (event_type);"
        )

    def _migration_v23(self, cur: sqlite3.Cursor) -> None:
        cur.execute("PRAGMA table_info(library_artists);")
        art_cols = [row[1] for row in cur.fetchall()]
        if "monitor_option" not in art_cols:
            cur.execute("ALTER TABLE library_artists ADD COLUMN monitor_option TEXT NOT NULL DEFAULT 'all';")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_lib_artists_monitored ON library_artists(monitored);")

    def _migration_v24(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS plex_playlist_registry (
                plex_user TEXT NOT NULL,
                rating_key TEXT NOT NULL,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                owner TEXT NOT NULL,
                ignored INTEGER NOT NULL DEFAULT 0,
                trackseerr_playlist_id TEXT REFERENCES playlists(id) ON DELETE SET NULL,
                last_seen_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
                PRIMARY KEY (plex_user, rating_key)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS plex_mix_snapshots (
                id TEXT PRIMARY KEY,
                plex_user TEXT NOT NULL,
                mix_key TEXT NOT NULL,
                mix_title TEXT NOT NULL,
                playlist_title TEXT NOT NULL,
                rating_key TEXT,
                auto_refresh INTEGER NOT NULL DEFAULT 0,
                last_refreshed_at TEXT,
                created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
                UNIQUE (plex_user, mix_key)
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_plex_registry_adopted ON plex_playlist_registry(trackseerr_playlist_id);"
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
        default_perms = 35 if is_admin else 34
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO users (id, username, email, is_admin, permissions, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    username = excluded.username,
                    email = excluded.email,
                    is_admin = excluded.is_admin,
                    permissions = CASE WHEN excluded.is_admin = 1 THEN users.permissions | 1 ELSE users.permissions END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (uid, uname, email, admin_val, default_perms),
            )
            self.conn.commit()
        user = self.get_user(uid)
        if user is None:
            raise RuntimeError(f"Failed to upsert user {uid}")
        return user

    def get_user(self, user_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT id, username, email, is_admin, permissions,
                       request_limit_quota, request_limit_days, created_at, updated_at
                FROM users WHERE id = ?
                """,
                (str(user_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            d = dict(row)
            d["is_admin"] = bool(d["is_admin"])
            d["permissions"] = int(d["permissions"]) if d.get("permissions") is not None else 34
            d["request_limit_quota"] = int(d["request_limit_quota"]) if d.get("request_limit_quota") is not None else None
            d["request_limit_days"] = int(d["request_limit_days"]) if d.get("request_limit_days") is not None else 7
            return d

    def list_users(self) -> list[dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT id, username, email, is_admin, permissions,
                       request_limit_quota, request_limit_days, created_at, updated_at
                FROM users ORDER BY username ASC
                """
            )
            results = []
            for row in cur.fetchall():
                d = dict(row)
                d["is_admin"] = bool(d["is_admin"])
                d["permissions"] = int(d["permissions"]) if d.get("permissions") is not None else 34
                d["request_limit_quota"] = int(d["request_limit_quota"]) if d.get("request_limit_quota") is not None else None
                d["request_limit_days"] = int(d["request_limit_days"]) if d.get("request_limit_days") is not None else 7
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

    def update_user_governance(
        self,
        user_id: str,
        permissions: Optional[int] = None,
        request_limit_quota: Optional[int] = None,
        request_limit_days: Optional[int] = None,
        is_admin: Optional[bool] = None,
        *,
        clear_quota: bool = False,
    ) -> dict[str, Any]:
        """Updates governance permissions, quota limits, and role flags for a user."""
        user = self.get_user(user_id)
        if not user:
            raise KeyError(f"User {user_id} not found")

        updates: list[str] = []
        params: list[Any] = []

        if permissions is not None:
            updates.append("permissions = ?")
            params.append(int(permissions))

        if request_limit_quota is not None:
            updates.append("request_limit_quota = ?")
            params.append(int(request_limit_quota))
        elif clear_quota:
            updates.append("request_limit_quota = NULL")

        if request_limit_days is not None:
            updates.append("request_limit_days = ?")
            params.append(int(request_limit_days))

        if is_admin is not None:
            updates.append("is_admin = ?")
            params.append(1 if is_admin else 0)

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            sql = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
            params.append(str(user_id))
            with self._lock:
                self.conn.execute(sql, params)
                self.conn.commit()

        updated_user = self.get_user(user_id)
        if updated_user is None:
            raise RuntimeError(f"User {user_id} not found after update")
        return updated_user

    def get_user_active_request_count(
        self, user_id: str, days: Optional[int] = None
    ) -> int:
        """Counts active/recent requests for a user within a rolling day window or all time."""
        with self._lock:
            if days is not None and int(days) > 0:
                cur = self.conn.execute(
                    """
                    SELECT COUNT(*) FROM music_requests
                    WHERE user_id = ?
                      AND status IN ('pending', 'processing', 'approved')
                      AND datetime(created_at) >= datetime('now', '-' || ? || ' days')
                    """,
                    (str(user_id), int(days)),
                )
            else:
                cur = self.conn.execute(
                    """
                    SELECT COUNT(*) FROM music_requests
                    WHERE user_id = ?
                      AND status IN ('pending', 'processing', 'approved')
                    """,
                    (str(user_id),),
                )
            row = cur.fetchone()
            return int(row[0]) if (row and row[0] is not None) else 0

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
    # Plex Playlist Control: registry + mix snapshots
    # -------------------------------------------------------------------------

    def get_plex_registry_row(self, plex_user: str, rating_key: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM plex_playlist_registry WHERE plex_user = ? AND rating_key = ?",
                (str(plex_user).lower(), str(rating_key)),
            ).fetchone()
        return self._registry_to_dict(row) if row else None

    def list_plex_registry(self, plex_user: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM plex_playlist_registry WHERE plex_user = ? ORDER BY title COLLATE NOCASE ASC",
                (str(plex_user).lower(),),
            ).fetchall()
        return [self._registry_to_dict(r) for r in rows]

    def get_plex_registry_by_adopted(self, playlist_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM plex_playlist_registry WHERE trackseerr_playlist_id = ? LIMIT 1",
                (str(playlist_id),),
            ).fetchone()
        return self._registry_to_dict(row) if row else None

    @staticmethod
    def _registry_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["ignored"] = bool(d["ignored"])
        return d

    def upsert_plex_registry(
        self,
        plex_user: str,
        rating_key: str,
        title: str,
        kind: str,
        owner: str,
        ignored: Optional[bool] = None,
        trackseerr_playlist_id: Optional[str] = None,
        update_owner: bool = True,
    ) -> dict[str, Any]:
        """Insert or update a registry row.

        On conflict the title, kind and last_seen_at are refreshed. ``owner`` is only overwritten when
        ``update_owner`` is True; ``ignored`` and ``trackseerr_playlist_id`` only when provided.
        """
        user = str(plex_user).lower()
        key = str(rating_key)
        ignored_val = None if ignored is None else (1 if ignored else 0)
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO plex_playlist_registry
                    (plex_user, rating_key, title, kind, owner, ignored, trackseerr_playlist_id, last_seen_at)
                VALUES (?, ?, ?, ?, ?, COALESCE(?, 0), ?, CURRENT_TIMESTAMP)
                ON CONFLICT(plex_user, rating_key) DO UPDATE SET
                    title = excluded.title,
                    kind = excluded.kind,
                    owner = CASE WHEN ? = 1 THEN excluded.owner ELSE plex_playlist_registry.owner END,
                    ignored = COALESCE(?, plex_playlist_registry.ignored),
                    trackseerr_playlist_id = COALESCE(?, plex_playlist_registry.trackseerr_playlist_id),
                    last_seen_at = CURRENT_TIMESTAMP
                """,
                (
                    user,
                    key,
                    title,
                    kind,
                    owner,
                    ignored_val,
                    trackseerr_playlist_id,
                    1 if update_owner else 0,
                    ignored_val,
                    trackseerr_playlist_id,
                ),
            )
            self.conn.commit()
        row = self.get_plex_registry_row(user, key)
        if row is None:
            raise RuntimeError(f"Failed to upsert plex registry row {user}/{key}")
        return row

    def delete_plex_registry(self, plex_user: str, rating_key: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM plex_playlist_registry WHERE plex_user = ? AND rating_key = ?",
                (str(plex_user).lower(), str(rating_key)),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def prune_plex_registry(self, plex_user: str, keep_rating_keys: list[str]) -> int:
        """Delete registry rows for playlists that no longer exist on Plex for this user."""
        keep = {str(k) for k in keep_rating_keys}
        removed = 0
        for row in self.list_plex_registry(plex_user):
            if row["rating_key"] not in keep:
                if self.delete_plex_registry(plex_user, row["rating_key"]):
                    removed += 1
        return removed

    def find_playlist_by_name_for_username(self, name: str, username: str) -> Optional[dict[str, Any]]:
        """Find a TrackSeerr playlist with this exact name that targets the given Plex username."""
        with self._lock:
            row = self.conn.execute(
                """
                SELECT p.id, p.name, p.service, p.last_synced_at, p.created_at
                FROM playlists p
                JOIN playlist_targets pt ON pt.playlist_id = p.id
                JOIN users u ON u.id = pt.user_id
                WHERE p.name = ? AND LOWER(u.username) = LOWER(?)
                LIMIT 1
                """,
                (name, username),
            ).fetchone()
        return dict(row) if row else None

    def set_playlist_tracks_json(self, playlist_id: str, tracks_json: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "UPDATE playlists SET tracks_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (tracks_json, str(playlist_id)),
            )
            self.conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _snapshot_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["auto_refresh"] = bool(d["auto_refresh"])
        return d

    def upsert_mix_snapshot(
        self,
        plex_user: str,
        mix_key: str,
        mix_title: str,
        playlist_title: str,
        rating_key: Optional[str],
        auto_refresh: bool,
        created_by: Optional[str] = None,
    ) -> dict[str, Any]:
        user = str(plex_user).lower()
        with self._lock:
            existing = self.conn.execute(
                "SELECT id FROM plex_mix_snapshots WHERE plex_user = ? AND mix_key = ?",
                (user, mix_key),
            ).fetchone()
            if existing:
                snap_id = existing["id"]
                self.conn.execute(
                    """
                    UPDATE plex_mix_snapshots
                    SET mix_title = ?, playlist_title = ?, rating_key = ?, auto_refresh = ?,
                        last_refreshed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (mix_title, playlist_title, rating_key, 1 if auto_refresh else 0, snap_id),
                )
            else:
                snap_id = uuid.uuid4().hex
                self.conn.execute(
                    """
                    INSERT INTO plex_mix_snapshots
                        (id, plex_user, mix_key, mix_title, playlist_title, rating_key, auto_refresh,
                         last_refreshed_at, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                    """,
                    (snap_id, user, mix_key, mix_title, playlist_title, rating_key,
                     1 if auto_refresh else 0, created_by),
                )
            self.conn.commit()
        snap = self.get_mix_snapshot(snap_id)
        if snap is None:
            raise RuntimeError("Failed to upsert mix snapshot")
        return snap

    def get_mix_snapshot(self, snapshot_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM plex_mix_snapshots WHERE id = ?", (str(snapshot_id),)
            ).fetchone()
        return self._snapshot_to_dict(row) if row else None

    def list_mix_snapshots(
        self, plex_user: Optional[str] = None, auto_refresh_only: bool = False
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM plex_mix_snapshots"
        clauses: list[str] = []
        params: list[Any] = []
        if plex_user is not None:
            clauses.append("plex_user = ?")
            params.append(str(plex_user).lower())
        if auto_refresh_only:
            clauses.append("auto_refresh = 1")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY mix_title COLLATE NOCASE ASC"
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        return [self._snapshot_to_dict(r) for r in rows]

    def set_mix_snapshot_auto_refresh(self, snapshot_id: str, auto_refresh: bool) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "UPDATE plex_mix_snapshots SET auto_refresh = ? WHERE id = ?",
                (1 if auto_refresh else 0, str(snapshot_id)),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def mark_mix_snapshot_refreshed(self, snapshot_id: str, rating_key: Optional[str] = None) -> None:
        with self._lock:
            self.conn.execute(
                """
                UPDATE plex_mix_snapshots
                SET last_refreshed_at = CURRENT_TIMESTAMP, rating_key = COALESCE(?, rating_key)
                WHERE id = ?
                """,
                (rating_key, str(snapshot_id)),
            )
            self.conn.commit()

    def delete_mix_snapshot(self, snapshot_id: str) -> bool:
        with self._lock:
            cur = self.conn.execute("DELETE FROM plex_mix_snapshots WHERE id = ?", (str(snapshot_id),))
            self.conn.commit()
            return cur.rowcount > 0

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

    def get_missing_track(self, track_id: int) -> Optional[dict[str, Any]]:
        """Retrieves a single missing track by ID."""
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT id, playlist_id, title, artist, album, url, lidarr_status, created_at
                FROM missing_tracks
                WHERE id = ?
                """,
                (int(track_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else None

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
        qp_id = getattr(request, "quality_profile_id", None)
        curr_q = getattr(request, "current_quality", None)
        cutoff_m = getattr(request, "cutoff_met", 1)
        cutoff_val = 1 if (cutoff_m is None or cutoff_m) else 0

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO music_requests (
                    id, user_id, item_type, title, artist, album,
                    cover_url, preview_url, status, release_date, foreign_id,
                    quality_profile_id, current_quality, cutoff_met,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
                    qp_id,
                    curr_q,
                    cutoff_val,
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
                       r.quality_profile_id, r.current_quality, r.cutoff_met,
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
                   r.quality_profile_id, r.current_quality, r.cutoff_met,
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

    def get_cutoff_unmet_requests(self) -> list[dict[str, Any]]:
        """Returns requests where status = 'available' AND cutoff_met = 0."""
        query = """
            SELECT r.id, r.user_id, r.item_type, r.title, r.artist, r.album,
                   r.cover_url, r.preview_url, r.status, r.release_date, r.foreign_id,
                   r.quality_profile_id, r.current_quality, r.cutoff_met,
                   r.created_at, r.updated_at, u.username
            FROM music_requests r
            LEFT JOIN users u ON r.user_id = u.id
            WHERE r.status = 'available' AND r.cutoff_met = 0
            ORDER BY r.created_at ASC
        """
        with self._lock:
            cur = self.conn.execute(query)
            return [dict(row) for row in cur.fetchall()]

    def update_request_quality(
        self, request_id: str, current_quality: Optional[str], cutoff_met: int = 1
    ) -> bool:
        """Updates the current quality and cutoff_met status of a request."""
        with self._lock:
            cur = self.conn.execute(
                """
                UPDATE music_requests
                SET current_quality = ?, cutoff_met = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (current_quality, int(cutoff_met), str(request_id)),
            )
            self.conn.commit()
            return cur.rowcount > 0

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
                       r.quality_profile_id, r.current_quality, r.cutoff_met,
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
            res["write_audio_tags"] = bool(res.get("write_audio_tags", 1))
            res["embed_artwork"] = bool(res.get("embed_artwork", 1))
            res["save_cover_art_file"] = bool(res.get("save_cover_art_file", 1))
            res["staging_folder_path"] = str(res.get("staging_folder_path") or "/data/downloads")
            res["import_mode"] = str(res.get("import_mode") or "move")
            res["delete_completed_transfers"] = bool(res.get("delete_completed_transfers", 0))
            res["enable_quality_upgrades"] = bool(res.get("enable_quality_upgrades", 1))
            res["library_mode"] = str(res.get("library_mode") or "native")
            res["seed_ratio_limit"] = (
                float(res["seed_ratio_limit"]) if res.get("seed_ratio_limit") is not None else None
            )
            res["seed_time_limit_minutes"] = (
                int(res["seed_time_limit_minutes"]) if res.get("seed_time_limit_minutes") is not None else None
            )
            res["enrich_mbids"] = bool(res.get("enrich_mbids", 1))
            res["acoustid_api_key"] = (
                str(res["acoustid_api_key"]) if res.get("acoustid_api_key") is not None else None
            )
            res["mb_mirror_url"] = str(res.get("mb_mirror_url") or "https://api.brainzmash.cc")
            res["prefer_local_artwork"] = bool(res.get("prefer_local_artwork", 1))
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
            "staging_folder_path",
            "import_mode",
            "write_audio_tags",
            "embed_artwork",
            "save_cover_art_file",
            "delete_completed_transfers",
            "enable_quality_upgrades",
            "library_mode",
            "seed_ratio_limit",
            "seed_time_limit_minutes",
            "enrich_mbids",
            "acoustid_api_key",
            "mb_mirror_url",
            "prefer_local_artwork",
        }
        updates: dict[str, Any] = {}
        for k, v in settings.items():
            if k in allowed_keys:
                if k in (
                    "clean_artist_names",
                    "write_audio_tags",
                    "embed_artwork",
                    "save_cover_art_file",
                    "delete_completed_transfers",
                    "enable_quality_upgrades",
                    "enrich_mbids",
                    "prefer_local_artwork",
                ):
                    if v is not None:
                        updates[k] = 1 if bool(v) else 0
                elif k == "seed_ratio_limit":
                    updates[k] = float(v) if v is not None else None
                elif k == "seed_time_limit_minutes":
                    updates[k] = int(v) if v is not None else None
                elif k == "acoustid_api_key":
                    updates[k] = str(v) if v is not None else None
                elif v is not None:
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
    # General Settings CRUD
    # -------------------------------------------------------------------------

    def get_general_settings(self) -> dict[str, Any]:
        """Retrieves general system settings (singleton row id=1), falling back to env."""
        with self._lock:
            cur = self.conn.execute("SELECT * FROM general_settings WHERE id = 1")
            row = cur.fetchone()
            if not row:
                self.conn.execute("INSERT OR IGNORE INTO general_settings (id, application_url) VALUES (1, '')")
                self.conn.commit()
                cur = self.conn.execute("SELECT * FROM general_settings WHERE id = 1")
                row = cur.fetchone()
            res = dict(row) if row else {"id": 1, "application_url": "", "updated_at": None}
            res["application_url"] = str(res.get("application_url") or "").strip().rstrip("/")
            if not res["application_url"]:
                env_url = (os.getenv("APPLICATION_URL") or os.getenv("APP_URL") or "").strip().rstrip("/")
                res["application_url"] = env_url
            return res

    def update_general_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Updates general system settings (singleton row id=1)."""
        allowed_keys = {"application_url"}
        updates: dict[str, Any] = {}
        for k, v in settings.items():
            if k in allowed_keys and v is not None:
                updates[k] = str(v).strip().rstrip("/")

        if updates:
            set_clauses = [f"{k} = ?" for k in updates.keys()]
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            values = list(updates.values())
            query = f"UPDATE general_settings SET {', '.join(set_clauses)} WHERE id = 1"
            with self._lock:
                self.conn.execute(query, values)
                self.conn.commit()

        return self.get_general_settings()

    def get_api_key(self) -> str:
        """Fetches api_key from general_settings. If empty, generates secrets.token_hex(16), saves it, and returns it."""
        with self._lock:
            cur = self.conn.execute("SELECT api_key FROM general_settings WHERE id = 1")
            row = cur.fetchone()
            key = str(row["api_key"] or "").strip() if row and "api_key" in row.keys() else ""
            if not key:
                key = secrets.token_hex(16)
                check = self.conn.execute("SELECT 1 FROM general_settings WHERE id = 1").fetchone()
                if check:
                    self.conn.execute(
                        "UPDATE general_settings SET api_key = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                        (key,),
                    )
                else:
                    self.conn.execute(
                        "INSERT INTO general_settings (id, application_url, api_key) VALUES (1, '', ?)",
                        (key,),
                    )
                self.conn.commit()
            return key

    def regenerate_api_key(self) -> str:
        """Generates new 32-character hexadecimal API key, saves it to general_settings, and returns it."""
        new_key = secrets.token_hex(16)
        with self._lock:
            check = self.conn.execute("SELECT 1 FROM general_settings WHERE id = 1").fetchone()
            if check:
                self.conn.execute(
                    "UPDATE general_settings SET api_key = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                    (new_key,),
                )
            else:
                self.conn.execute(
                    "INSERT INTO general_settings (id, application_url, api_key) VALUES (1, '', ?)",
                    (new_key,),
                )
            self.conn.commit()
        return new_key

    def validate_api_key(self, candidate_key: Optional[str]) -> bool:
        """Returns False if candidate_key is empty/None; compares candidate_key against stored api_key with secrets.compare_digest."""
        if not candidate_key or not isinstance(candidate_key, str) or not candidate_key.strip():
            return False
        stored_key = self.get_api_key()
        if not stored_key:
            return False
        return secrets.compare_digest(candidate_key.strip(), stored_key)

    # -------------------------------------------------------------------------
    # Lidarr Settings CRUD
    # -------------------------------------------------------------------------

    def get_lidarr_settings(self) -> dict[str, Any]:
        """Retrieves Lidarr automation settings (singleton row id=1)."""
        with self._lock:
            cur = self.conn.execute("SELECT * FROM lidarr_settings WHERE id = 1")
            row = cur.fetchone()
            if not row:
                self.conn.execute("INSERT OR IGNORE INTO lidarr_settings (id) VALUES (1)")
                self.conn.commit()
                cur = self.conn.execute("SELECT * FROM lidarr_settings WHERE id = 1")
                row = cur.fetchone()
            res = dict(row)
            res["auto_search"] = bool(res.get("auto_search", 1))
            res["auto_trickle"] = bool(res.get("auto_trickle", 0))
            res["trickle_rate_seconds"] = float(res.get("trickle_rate_seconds") or 3.0)
            res["trickle_batch_size"] = int(res.get("trickle_batch_size") or 25)
            res["auto_trickle_interval_minutes"] = int(
                res.get("auto_trickle_interval_minutes") or 30
            )
            if res.get("quality_profile_id") is not None:
                res["quality_profile_id"] = int(res["quality_profile_id"])
            if res.get("metadata_profile_id") is not None:
                res["metadata_profile_id"] = int(res["metadata_profile_id"])
            return res

    def update_lidarr_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Updates Lidarr automation settings (singleton row id=1)."""
        allowed_keys = {
            "url",
            "api_key",
            "auto_search",
            "root_folder",
            "quality_profile_id",
            "metadata_profile_id",
            "trickle_rate_seconds",
            "trickle_batch_size",
            "auto_trickle",
            "auto_trickle_interval_minutes",
        }
        updates: dict[str, Any] = {}
        for k, v in settings.items():
            if k in allowed_keys:
                if k in ("auto_search", "auto_trickle"):
                    if v is not None:
                        updates[k] = 1 if v else 0
                elif k in (
                    "quality_profile_id",
                    "metadata_profile_id",
                    "trickle_batch_size",
                    "auto_trickle_interval_minutes",
                ):
                    updates[k] = int(v) if v is not None else None
                elif k == "trickle_rate_seconds":
                    updates[k] = float(v) if v is not None else 3.0
                else:
                    updates[k] = str(v) if v is not None else None

        if updates:
            set_clauses = [f"{k} = ?" for k in updates.keys()]
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            values = list(updates.values())
            query = f"UPDATE lidarr_settings SET {', '.join(set_clauses)} WHERE id = 1"
            with self._lock:
                self.conn.execute(query, values)
                self.conn.commit()

        return self.get_lidarr_settings()

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

    def _map_active_download(self, row: sqlite3.Row) -> dict[str, Any]:
        res = dict(row)
        res["progress"] = float(res.get("progress") or 0.0)
        res["size_bytes"] = int(res.get("size_bytes") or 0)
        res["track_id"] = res.get("track_id")
        res["album_id"] = res.get("album_id")
        return res

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
        track_id = d.get("track_id")
        album_id = d.get("album_id")

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO active_downloads (
                    id, request_id, client_id, download_hash, title, artist,
                    item_type, status, progress, size_bytes, source_path,
                    target_path, error_message, track_id, album_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
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
                    track_id = excluded.track_id,
                    album_id = excluded.album_id,
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
                    track_id,
                    album_id,
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
            return self._map_active_download(row)

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
            return [self._map_active_download(r) for r in cur.fetchall()]

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

    # -------------------------------------------------------------------------
    # Quality Profiles CRUD
    # -------------------------------------------------------------------------

    def _format_quality_profile_row(self, row: sqlite3.Row) -> dict[str, Any]:
        res = dict(row)
        res["is_default"] = bool(res.get("is_default", 0))
        res["min_size_mb"] = (
            float(res["min_size_mb"]) if res.get("min_size_mb") is not None else None
        )
        res["max_size_mb"] = (
            float(res["max_size_mb"]) if res.get("max_size_mb") is not None else None
        )

        try:
            res["items"] = json.loads(res.get("items_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            res["items"] = []

        try:
            res["preferred_tags"] = json.loads(res.get("preferred_tags_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            res["preferred_tags"] = []

        try:
            res["ignored_tags"] = json.loads(res.get("ignored_tags_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            res["ignored_tags"] = []

        try:
            res["custom_formats"] = json.loads(res.get("custom_formats_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            res["custom_formats"] = []

        res["min_score"] = (
            int(res["min_score"]) if res.get("min_score") is not None else None
        )

        return res

    def list_quality_profiles(self) -> list[dict[str, Any]]:
        """Lists all quality profiles ordered by default first, then name."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM quality_profiles ORDER BY is_default DESC, name ASC"
            )
            rows = cur.fetchall()
            return [self._format_quality_profile_row(r) for r in rows]

    def get_quality_profile(self, profile_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a single quality profile by ID."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM quality_profiles WHERE id = ?", (str(profile_id),)
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._format_quality_profile_row(row)

    def get_default_quality_profile(self) -> dict[str, Any]:
        """Retrieves the default quality profile."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM quality_profiles WHERE is_default = 1 LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                cur = self.conn.execute(
                    "SELECT * FROM quality_profiles ORDER BY name ASC LIMIT 1"
                )
                row = cur.fetchone()
            if not row:
                raise ValueError("No quality profiles configured in the database")
            return self._format_quality_profile_row(row)

    def create_quality_profile(
        self, profile: Union[QualityProfile, dict[str, Any]]
    ) -> dict[str, Any]:
        """Creates a quality profile (alias to upsert_quality_profile)."""
        return self.upsert_quality_profile(profile)

    def update_quality_profile(
        self, profile_id: str, updates: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Updates an existing quality profile by ID."""
        existing = self.get_quality_profile(profile_id)
        if not existing:
            return None
        existing.update(updates)
        return self.upsert_quality_profile(existing)

    def upsert_quality_profile(
        self, profile: Union[QualityProfile, dict[str, Any]]
    ) -> dict[str, Any]:
        """Creates or updates a quality profile. If is_default=True, clears is_default on all others."""
        if isinstance(profile, QualityProfile):
            p_id = profile.id
            name = profile.name
            cutoff = profile.cutoff
            items = [
                i.to_dict() if hasattr(i, "to_dict") else i for i in profile.items
            ]
            preferred_tags = profile.preferred_tags
            ignored_tags = profile.ignored_tags
            min_size_mb = profile.min_size_mb
            max_size_mb = profile.max_size_mb
            is_default = bool(profile.is_default)
            custom_formats = profile.custom_formats
            min_score = profile.min_score
        else:
            p_id = str(profile.get("id"))
            name = str(profile.get("name"))
            cutoff = str(profile.get("cutoff"))
            items = profile.get("items", [])
            items = [
                i.to_dict() if hasattr(i, "to_dict") else i for i in items
            ]
            preferred_tags = profile.get("preferred_tags", [])
            ignored_tags = profile.get("ignored_tags", [])
            min_size_mb = profile.get("min_size_mb")
            max_size_mb = profile.get("max_size_mb")
            is_default = bool(profile.get("is_default", False))
            custom_formats = profile.get("custom_formats", [])
            min_score = profile.get("min_score")

        with self._lock:
            if is_default:
                self.conn.execute(
                    "UPDATE quality_profiles SET is_default = 0 WHERE id != ?", (p_id,)
                )

            self.conn.execute(
                """
                INSERT INTO quality_profiles (
                    id, name, cutoff, items_json, preferred_tags_json, ignored_tags_json,
                    min_size_mb, max_size_mb, is_default, custom_formats_json, min_score, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    cutoff = excluded.cutoff,
                    items_json = excluded.items_json,
                    preferred_tags_json = excluded.preferred_tags_json,
                    ignored_tags_json = excluded.ignored_tags_json,
                    min_size_mb = excluded.min_size_mb,
                    max_size_mb = excluded.max_size_mb,
                    is_default = excluded.is_default,
                    custom_formats_json = excluded.custom_formats_json,
                    min_score = excluded.min_score,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    p_id,
                    name,
                    cutoff,
                    json.dumps(items),
                    json.dumps(preferred_tags),
                    json.dumps(ignored_tags),
                    min_size_mb,
                    max_size_mb,
                    1 if is_default else 0,
                    json.dumps(custom_formats if isinstance(custom_formats, list) else []),
                    int(min_score) if min_score is not None else None,
                ),
            )

            # Ensure at least one profile is marked default
            cur = self.conn.execute(
                "SELECT COUNT(*) FROM quality_profiles WHERE is_default = 1"
            )
            count = cur.fetchone()[0]
            if count == 0:
                self.conn.execute(
                    "UPDATE quality_profiles SET is_default = 1 WHERE id = ?", (p_id,)
                )

            self.conn.commit()

        result = self.get_quality_profile(p_id)
        if not result:
            raise sqlite3.OperationalError(f"Failed to retrieve upserted profile {p_id}")
        return result

    def delete_quality_profile(self, profile_id: str) -> bool:
        """Deletes a quality profile. Raises ValueError if the profile is default."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT is_default FROM quality_profiles WHERE id = ?",
                (str(profile_id),),
            )
            row = cur.fetchone()
            if not row:
                return False
            if bool(row[0]):
                raise ValueError("Cannot delete the default quality profile")

            cur = self.conn.execute(
                "DELETE FROM quality_profiles WHERE id = ?", (str(profile_id),)
            )
            self.conn.commit()
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Notification Channels CRUD
    # -------------------------------------------------------------------------

    def create_notification_channel(
        self, channel: Union[dict[str, Any], NotificationChannel]
    ) -> dict[str, Any]:
        """Creates or updates a notification channel."""
        if isinstance(channel, NotificationChannel):
            c_id = channel.id
            name = channel.name
            channel_type = (
                channel.channel_type.value
                if isinstance(channel.channel_type, NotificationChannelType)
                else str(channel.channel_type)
            )
            enabled = 1 if channel.enabled else 0
            config_json = json.dumps(channel.config if isinstance(channel.config, dict) else {})
            events_list = [
                e.value if isinstance(e, NotificationEvent) else str(e)
                for e in (channel.events or [])
            ]
            events_json = json.dumps(events_list)
        else:
            c = dict(channel)
            c_id = str(c.get("id") or "")
            name = str(c.get("name") or "")
            ctype_raw = c.get("channel_type", "")
            channel_type = (
                ctype_raw.value
                if isinstance(ctype_raw, NotificationChannelType)
                else str(ctype_raw)
            )
            enabled = 1 if c.get("enabled", True) else 0
            cfg = c.get("config")
            config_json = json.dumps(cfg if isinstance(cfg, dict) else {})
            raw_events = c.get("events") or []
            events_list = [
                e.value if isinstance(e, NotificationEvent) else str(e)
                for e in raw_events
            ]
            events_json = json.dumps(events_list)

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO notification_channels (
                    id, name, channel_type, enabled, config_json, events_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    channel_type = excluded.channel_type,
                    enabled = excluded.enabled,
                    config_json = excluded.config_json,
                    events_json = excluded.events_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (c_id, name, channel_type, enabled, config_json, events_json),
            )
            self.conn.commit()

        ret = self.get_notification_channel(c_id)
        if not ret:
            raise sqlite3.OperationalError(f"Failed to fetch saved notification channel '{c_id}'")
        return ret

    def get_notification_channel(self, channel_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a notification channel by ID."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM notification_channels WHERE id = ?", (str(channel_id),)
            )
            row = cur.fetchone()
        if not row:
            return None
        return self._row_to_channel_dict(row)

    def list_notification_channels(
        self, enabled_only: bool = False
    ) -> list[dict[str, Any]]:
        """Lists notification channels, optionally filtering by enabled status."""
        query = (
            "SELECT * FROM notification_channels WHERE enabled = 1 ORDER BY created_at ASC"
            if enabled_only
            else "SELECT * FROM notification_channels ORDER BY created_at ASC"
        )
        with self._lock:
            cur = self.conn.execute(query)
            rows = cur.fetchall()
        return [self._row_to_channel_dict(r) for r in rows]

    def update_notification_channel(
        self, channel_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Updates fields of an existing notification channel."""
        allowed = {"name", "channel_type", "enabled", "config", "events"}
        filtered: dict[str, Any] = {}
        for k, v in updates.items():
            if k in allowed:
                if k == "enabled":
                    filtered["enabled"] = 1 if v else 0
                elif k == "config":
                    filtered["config_json"] = json.dumps(v if isinstance(v, dict) else {})
                elif k == "events":
                    ev_list = [
                        e.value if isinstance(e, NotificationEvent) else str(e)
                        for e in (v or [])
                    ]
                    filtered["events_json"] = json.dumps(ev_list)
                elif k == "channel_type":
                    filtered["channel_type"] = (
                        v.value if isinstance(v, NotificationChannelType) else str(v)
                    )
                else:
                    filtered[k] = v

        if filtered:
            set_clauses = [f"{k} = ?" for k in filtered.keys()]
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            values = list(filtered.values())
            values.append(str(channel_id))

            with self._lock:
                self.conn.execute(
                    f"UPDATE notification_channels SET {', '.join(set_clauses)} WHERE id = ?",
                    values,
                )
                self.conn.commit()

        ret = self.get_notification_channel(channel_id)
        if not ret:
            raise KeyError(f"Notification channel '{channel_id}' not found")
        return ret

    def delete_notification_channel(self, channel_id: str) -> bool:
        """Deletes a notification channel by ID."""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM notification_channels WHERE id = ?", (str(channel_id),)
            )
            self.conn.commit()
            return cur.rowcount > 0

    def _row_to_channel_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["enabled"] = bool(d.get("enabled", 1))
        config_raw = d.pop("config_json", "{}")
        try:
            d["config"] = json.loads(config_raw) if config_raw else {}
        except (json.JSONDecodeError, TypeError):
            d["config"] = {}
        events_raw = d.pop("events_json", "[]")
        try:
            d["events"] = json.loads(events_raw) if events_raw else []
        except (json.JSONDecodeError, TypeError):
            d["events"] = []
        return d

    # -------------------------------------------------------------------------
    # Media Issues CRUD
    # -------------------------------------------------------------------------

    def create_issue(self, issue: Union[MediaIssue, dict[str, Any]]) -> dict[str, Any]:
        """Creates a new media issue report."""
        d = issue.to_dict() if isinstance(issue, MediaIssue) else dict(issue)
        issue_id = str(d.get("id"))
        req_id = d.get("request_id")
        media_title = str(d.get("media_title") or "")
        artist = str(d.get("artist") or "")
        issue_type = d.get("issue_type")
        if hasattr(issue_type, "value"):
            issue_type = issue_type.value
        issue_type = str(issue_type or "other")
        problem_details = str(d.get("problem_details") or "")
        status_val = d.get("status")
        if hasattr(status_val, "value"):
            status_val = status_val.value
        status_val = str(status_val or "open")
        user_id = str(d.get("user_id"))

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO media_issues (
                    id, request_id, media_title, artist, issue_type,
                    problem_details, status, user_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    issue_id,
                    req_id,
                    media_title,
                    artist,
                    issue_type,
                    problem_details,
                    status_val,
                    user_id,
                ),
            )
            self.conn.commit()

        created = self.get_issue(issue_id)
        if created is None:
            raise RuntimeError(f"Failed to retrieve created issue {issue_id}")
        return created

    def get_issue(self, issue_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a single media issue by ID with reporter username joined."""
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT i.id, i.request_id, i.media_title, i.artist, i.issue_type,
                       i.problem_details, i.status, i.user_id, i.created_at, i.updated_at,
                       u.username
                FROM media_issues i
                LEFT JOIN users u ON i.user_id = u.id
                WHERE i.id = ?
                """,
                (str(issue_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_issues(
        self, status: Optional[str] = None, user_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Lists media issues filtered by status and/or user_id with username joined."""
        query = """
            SELECT i.id, i.request_id, i.media_title, i.artist, i.issue_type,
                   i.problem_details, i.status, i.user_id, i.created_at, i.updated_at,
                   u.username
            FROM media_issues i
            LEFT JOIN users u ON i.user_id = u.id
            WHERE 1=1
        """
        params: list[Any] = []
        if status:
            query += " AND i.status = ?"
            params.append(str(status))
        if user_id:
            query += " AND i.user_id = ?"
            params.append(str(user_id))
        query += " ORDER BY i.created_at DESC"

        with self._lock:
            cur = self.conn.execute(query, params)
            return [dict(r) for r in cur.fetchall()]

    def update_issue(
        self, issue_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Updates media issue status and problem details."""
        existing = self.get_issue(issue_id)
        if not existing:
            raise KeyError(f"Media issue {issue_id} not found")

        allowed = {"status", "problem_details", "media_title", "artist", "issue_type", "request_id"}
        filtered: dict[str, Any] = {}
        for k, v in updates.items():
            if k in allowed and v is not None:
                if hasattr(v, "value"):
                    filtered[k] = v.value
                else:
                    filtered[k] = str(v)

        if filtered:
            set_clauses = [f"{k} = ?" for k in filtered.keys()]
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            params = list(filtered.values())
            params.append(str(issue_id))

            with self._lock:
                self.conn.execute(
                    f"UPDATE media_issues SET {', '.join(set_clauses)} WHERE id = ?",
                    params,
                )
                self.conn.commit()

        updated = self.get_issue(issue_id)
        if updated is None:
            raise RuntimeError(f"Media issue {issue_id} disappeared after update")
        return updated

    def delete_issue(self, issue_id: str) -> bool:
        """Deletes a media issue by ID."""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM media_issues WHERE id = ?",
                (str(issue_id),),
            )
            self.conn.commit()
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Native Library CRUD
    # -------------------------------------------------------------------------

    def _map_library_artist(self, row: sqlite3.Row) -> dict[str, Any]:
        res = dict(row)
        res["monitored"] = bool(res.get("monitored", 1))
        res["monitor_option"] = str(res.get("monitor_option") or "all")
        return res

    def _map_library_album(self, row: sqlite3.Row) -> dict[str, Any]:
        res = dict(row)
        res["monitored"] = bool(res.get("monitored", 1))
        if res.get("year") is not None:
            res["year"] = int(res["year"])
        if res.get("total_tracks") is not None:
            res["total_tracks"] = int(res["total_tracks"])
        return res

    def _map_library_track(self, row: sqlite3.Row) -> dict[str, Any]:
        res = dict(row)
        res["monitored"] = bool(res.get("monitored", 1))
        res["track_number"] = int(res.get("track_number", 1))
        res["disc_number"] = int(res.get("disc_number", 1))
        if res.get("duration_seconds") is not None:
            res["duration_seconds"] = float(res["duration_seconds"])
        return res

    def _map_library_file(self, row: sqlite3.Row) -> dict[str, Any]:
        res = dict(row)
        res["cutoff_met"] = bool(res.get("cutoff_met", 1))
        res["size_bytes"] = int(res.get("size_bytes", 0))
        if res.get("bitrate") is not None:
            res["bitrate"] = int(res["bitrate"])
        if res.get("sample_rate") is not None:
            res["sample_rate"] = int(res["sample_rate"])
        if res.get("bits_per_sample") is not None:
            res["bits_per_sample"] = int(res["bits_per_sample"])
        return res

    def upsert_library_artist(
        self, artist_data: Union[LibraryArtist, dict[str, Any]]
    ) -> dict[str, Any]:
        """Creates or updates a native library artist."""
        d = artist_data.to_dict() if hasattr(artist_data, "to_dict") else dict(artist_data)
        artist_id = str(d.get("id") or uuid.uuid4())
        name = str(d.get("name") or "")
        clean_name = clean_library_name(d.get("clean_name") or name)
        foreign_artist_id = str(d["foreign_artist_id"]) if d.get("foreign_artist_id") is not None else None
        path = str(d["path"]) if d.get("path") is not None else None
        monitored = 1 if d.get("monitored", True) else 0
        monitor_option = str(d.get("monitor_option") or "all")
        quality_profile_id = str(d["quality_profile_id"]) if d.get("quality_profile_id") is not None else None
        metadata_json = d.get("metadata_json")
        if isinstance(metadata_json, dict):
            metadata_json = json.dumps(metadata_json)
        elif metadata_json is not None:
            metadata_json = str(metadata_json)
        mbid = str(d["mbid"]) if d.get("mbid") is not None else None
        image_url = str(d["image_url"]) if d.get("image_url") is not None else None
        banner_url = str(d["banner_url"]) if d.get("banner_url") is not None else None
        bio = str(d["bio"]) if d.get("bio") is not None else None
        genres = str(d["genres"]) if d.get("genres") is not None else None
        country = str(d["country"]) if d.get("country") is not None else None
        created_at = d.get("created_at")

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO library_artists (
                    id, name, clean_name, foreign_artist_id, path, monitored,
                    monitor_option, quality_profile_id, metadata_json, mbid,
                    image_url, banner_url, bio, genres, country, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    clean_name = excluded.clean_name,
                    foreign_artist_id = COALESCE(excluded.foreign_artist_id, library_artists.foreign_artist_id),
                    path = COALESCE(excluded.path, library_artists.path),
                    monitored = excluded.monitored,
                    monitor_option = excluded.monitor_option,
                    quality_profile_id = COALESCE(excluded.quality_profile_id, library_artists.quality_profile_id),
                    metadata_json = COALESCE(excluded.metadata_json, library_artists.metadata_json),
                    mbid = COALESCE(excluded.mbid, library_artists.mbid),
                    image_url = COALESCE(excluded.image_url, library_artists.image_url),
                    banner_url = COALESCE(excluded.banner_url, library_artists.banner_url),
                    bio = COALESCE(excluded.bio, library_artists.bio),
                    genres = COALESCE(excluded.genres, library_artists.genres),
                    country = COALESCE(excluded.country, library_artists.country),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    artist_id,
                    name,
                    clean_name,
                    foreign_artist_id,
                    path,
                    monitored,
                    monitor_option,
                    quality_profile_id,
                    metadata_json,
                    mbid,
                    image_url,
                    banner_url,
                    bio,
                    genres,
                    country,
                    created_at,
                ),
            )
            self.conn.commit()

        artist = self.get_library_artist(artist_id)
        if artist is None:
            raise RuntimeError(f"Failed to upsert library artist {artist_id}")
        return artist

    def get_library_artist(self, artist_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a single library artist by ID."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM library_artists WHERE id = ?",
                (str(artist_id),),
            )
            row = cur.fetchone()
            return self._map_library_artist(row) if row else None

    def get_library_artist_by_name(self, name: str) -> Optional[dict[str, Any]]:
        """Retrieves an artist by exact name or cleaned normalized name."""
        clean = clean_library_name(name)
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM library_artists WHERE clean_name = ? OR LOWER(name) = LOWER(?) LIMIT 1",
                (clean, str(name).strip()),
            )
            row = cur.fetchone()
            return self._map_library_artist(row) if row else None

    def get_library_artist_by_foreign_id(
        self, foreign_id: str
    ) -> Optional[dict[str, Any]]:
        """Retrieves a library artist by foreign_artist_id."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM library_artists WHERE foreign_artist_id = ? LIMIT 1",
                (str(foreign_id),),
            )
            row = cur.fetchone()
            return self._map_library_artist(row) if row else None

    def list_library_artists(
        self,
        monitored_only: bool = False,
        query: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Lists library artists with optional filtering, search query, and pagination."""
        sql = "SELECT * FROM library_artists WHERE 1=1"
        params: list[Any] = []
        if monitored_only:
            sql += " AND monitored = 1"
        if query:
            clean_q = clean_library_name(query)
            sql += " AND (clean_name LIKE ? OR name LIKE ?)"
            params.extend([f"%{clean_q}%", f"%{query}%"])
        sql += " ORDER BY name COLLATE NOCASE ASC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])

        with self._lock:
            cur = self.conn.execute(sql, params)
            return [self._map_library_artist(row) for row in cur.fetchall()]

    def delete_library_artist(self, artist_id: str) -> bool:
        """Deletes a library artist and cascades to child albums, tracks, and files."""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM library_artists WHERE id = ?",
                (str(artist_id),),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def set_artist_monitored(
        self, artist_id: str, monitored: bool, cascade_children: bool = True
    ) -> bool:
        """Sets monitoring status for an artist and optionally cascades to child albums and tracks."""
        val = 1 if monitored else 0
        with self._lock:
            cur = self.conn.execute(
                "UPDATE library_artists SET monitored = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (val, str(artist_id)),
            )
            if cur.rowcount == 0:
                return False
            if cascade_children:
                self.conn.execute(
                    "UPDATE library_albums SET monitored = ?, updated_at = CURRENT_TIMESTAMP WHERE artist_id = ?",
                    (val, str(artist_id)),
                )
                self.conn.execute(
                    "UPDATE library_tracks SET monitored = ?, updated_at = CURRENT_TIMESTAMP WHERE artist_id = ?",
                    (val, str(artist_id)),
                )
            self.conn.commit()
            return True

    def upsert_library_album(
        self, album_data: Union[LibraryAlbum, dict[str, Any]]
    ) -> dict[str, Any]:
        """Creates or updates a native library album."""
        d = album_data.to_dict() if hasattr(album_data, "to_dict") else dict(album_data)
        album_id = str(d.get("id") or uuid.uuid4())
        artist_id = str(d.get("artist_id") or "")
        title = str(d.get("title") or "")
        clean_title = clean_library_name(d.get("clean_title") or title)
        foreign_album_id = str(d["foreign_album_id"]) if d.get("foreign_album_id") is not None else None
        release_date = str(d["release_date"]) if d.get("release_date") is not None else None
        year = int(d["year"]) if d.get("year") is not None else None
        album_type = str(d.get("album_type") or "album")
        monitored = 1 if d.get("monitored", True) else 0
        path = str(d["path"]) if d.get("path") is not None else None
        cover_url = str(d["cover_url"]) if d.get("cover_url") is not None else None
        total_tracks = int(d["total_tracks"]) if d.get("total_tracks") is not None else None
        mb_release_group_id = str(d["mb_release_group_id"]) if d.get("mb_release_group_id") is not None else None
        mb_release_id = str(d["mb_release_id"]) if d.get("mb_release_id") is not None else None
        genres = str(d["genres"]) if d.get("genres") is not None else None
        created_at = d.get("created_at")

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO library_albums (
                    id, artist_id, title, clean_title, foreign_album_id, release_date,
                    year, album_type, monitored, path, cover_url, total_tracks,
                    mb_release_group_id, mb_release_id, genres,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    artist_id = excluded.artist_id,
                    title = excluded.title,
                    clean_title = excluded.clean_title,
                    foreign_album_id = COALESCE(excluded.foreign_album_id, library_albums.foreign_album_id),
                    release_date = COALESCE(excluded.release_date, library_albums.release_date),
                    year = COALESCE(excluded.year, library_albums.year),
                    album_type = excluded.album_type,
                    monitored = excluded.monitored,
                    path = COALESCE(excluded.path, library_albums.path),
                    cover_url = COALESCE(excluded.cover_url, library_albums.cover_url),
                    total_tracks = COALESCE(excluded.total_tracks, library_albums.total_tracks),
                    mb_release_group_id = COALESCE(excluded.mb_release_group_id, library_albums.mb_release_group_id),
                    mb_release_id = COALESCE(excluded.mb_release_id, library_albums.mb_release_id),
                    genres = COALESCE(excluded.genres, library_albums.genres),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    album_id,
                    artist_id,
                    title,
                    clean_title,
                    foreign_album_id,
                    release_date,
                    year,
                    album_type,
                    monitored,
                    path,
                    cover_url,
                    total_tracks,
                    mb_release_group_id,
                    mb_release_id,
                    genres,
                    created_at,
                ),
            )
            self.conn.commit()

        album = self.get_library_album(album_id)
        if album is None:
            raise RuntimeError(f"Failed to upsert library album {album_id}")
        return album

    def get_library_album(self, album_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a single library album by ID."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM library_albums WHERE id = ?",
                (str(album_id),),
            )
            row = cur.fetchone()
            return self._map_library_album(row) if row else None

    def get_library_album_by_title(
        self, artist_id: str, title: str
    ) -> Optional[dict[str, Any]]:
        """Retrieves a library album by artist ID and title using clean_library_name."""
        clean = clean_library_name(title)
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM library_albums WHERE artist_id = ? AND clean_title = ? LIMIT 1",
                (str(artist_id), clean),
            )
            row = cur.fetchone()
            return self._map_library_album(row) if row else None

    def get_library_album_by_foreign_id(
        self, foreign_id: str
    ) -> Optional[dict[str, Any]]:
        """Retrieves a library album by foreign_album_id."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM library_albums WHERE foreign_album_id = ? LIMIT 1",
                (str(foreign_id),),
            )
            row = cur.fetchone()
            return self._map_library_album(row) if row else None

    def get_library_album_by_release_group_id(
        self, mb_release_group_id: str
    ) -> Optional[dict[str, Any]]:
        """Retrieves a library album by MusicBrainz release group ID."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM library_albums WHERE mb_release_group_id = ? LIMIT 1",
                (str(mb_release_group_id),),
            )
            row = cur.fetchone()
            return self._map_library_album(row) if row else None


    def list_library_albums(
        self,
        artist_id: Optional[str] = None,
        monitored_only: bool = False,
        query: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Lists library albums with optional artist filtering and pagination."""
        sql = "SELECT * FROM library_albums WHERE 1=1"
        params: list[Any] = []
        if artist_id:
            sql += " AND artist_id = ?"
            params.append(str(artist_id))
        if monitored_only:
            sql += " AND monitored = 1"
        if query:
            clean_q = clean_library_name(query)
            sql += " AND (clean_title LIKE ? OR title LIKE ?)"
            params.extend([f"%{clean_q}%", f"%{query}%"])
        sql += " ORDER BY year DESC, title COLLATE NOCASE ASC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])

        with self._lock:
            cur = self.conn.execute(sql, params)
            return [self._map_library_album(row) for row in cur.fetchall()]

    def delete_library_album(self, album_id: str) -> bool:
        """Deletes a library album and cascades to child tracks and files."""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM library_albums WHERE id = ?",
                (str(album_id),),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def set_album_monitored(
        self, album_id: str, monitored: bool, cascade_tracks: bool = True
    ) -> bool:
        """Sets monitoring status for an album and optionally cascades to child tracks."""
        val = 1 if monitored else 0
        with self._lock:
            cur = self.conn.execute(
                "UPDATE library_albums SET monitored = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (val, str(album_id)),
            )
            if cur.rowcount == 0:
                return False
            if cascade_tracks:
                self.conn.execute(
                    "UPDATE library_tracks SET monitored = ?, updated_at = CURRENT_TIMESTAMP WHERE album_id = ?",
                    (val, str(album_id)),
                )
            self.conn.commit()
            return True

    def upsert_library_track(
        self, track_data: Union[LibraryTrack, dict[str, Any]]
    ) -> dict[str, Any]:
        """Creates or updates a native library track."""
        d = track_data.to_dict() if hasattr(track_data, "to_dict") else dict(track_data)
        track_id = str(d.get("id") or uuid.uuid4())
        album_id = str(d.get("album_id") or "")
        artist_id = str(d.get("artist_id") or "")
        title = str(d.get("title") or "")
        clean_title = clean_library_name(d.get("clean_title") or title)
        track_number = int(d.get("track_number", 1))
        disc_number = int(d.get("disc_number", 1))
        duration_seconds = float(d["duration_seconds"]) if d.get("duration_seconds") is not None else None
        monitored = 1 if d.get("monitored", True) else 0
        foreign_track_id = str(d["foreign_track_id"]) if d.get("foreign_track_id") is not None else None
        mb_recording_id = str(d["mb_recording_id"]) if d.get("mb_recording_id") is not None else None
        isrc = str(d["isrc"]) if d.get("isrc") is not None else None
        created_at = d.get("created_at")

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO library_tracks (
                    id, album_id, artist_id, title, clean_title, track_number,
                    disc_number, duration_seconds, monitored, foreign_track_id,
                    mb_recording_id, isrc,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    album_id = excluded.album_id,
                    artist_id = excluded.artist_id,
                    title = excluded.title,
                    clean_title = excluded.clean_title,
                    track_number = excluded.track_number,
                    disc_number = excluded.disc_number,
                    duration_seconds = COALESCE(excluded.duration_seconds, library_tracks.duration_seconds),
                    monitored = excluded.monitored,
                    foreign_track_id = COALESCE(excluded.foreign_track_id, library_tracks.foreign_track_id),
                    mb_recording_id = COALESCE(excluded.mb_recording_id, library_tracks.mb_recording_id),
                    isrc = COALESCE(excluded.isrc, library_tracks.isrc),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    track_id,
                    album_id,
                    artist_id,
                    title,
                    clean_title,
                    track_number,
                    disc_number,
                    duration_seconds,
                    monitored,
                    foreign_track_id,
                    mb_recording_id,
                    isrc,
                    created_at,
                ),
            )
            self.conn.commit()

        track = self.get_library_track(track_id)
        if track is None:
            raise RuntimeError(f"Failed to upsert library track {track_id}")
        return track

    def get_library_track(self, track_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a single library track by ID."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM library_tracks WHERE id = ?",
                (str(track_id),),
            )
            row = cur.fetchone()
            return self._map_library_track(row) if row else None

    def get_library_track_by_foreign_id(
        self, foreign_id: str, album_id: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """Retrieves a library track by foreign_track_id and optional album_id."""
        with self._lock:
            if album_id:
                cur = self.conn.execute(
                    "SELECT * FROM library_tracks WHERE foreign_track_id = ? AND album_id = ? LIMIT 1",
                    (str(foreign_id), str(album_id)),
                )
            else:
                cur = self.conn.execute(
                    "SELECT * FROM library_tracks WHERE foreign_track_id = ? LIMIT 1",
                    (str(foreign_id),),
                )
            row = cur.fetchone()
            return self._map_library_track(row) if row else None

    def get_library_track_by_title(
        self, album_id: str, title: str, track_number: Optional[int] = None
    ) -> Optional[dict[str, Any]]:
        """Retrieves a library track by album ID, clean title, and optional track number."""
        clean = clean_library_name(title)
        with self._lock:
            if track_number is not None:
                cur = self.conn.execute(
                    "SELECT * FROM library_tracks WHERE album_id = ? AND (clean_title = ? OR track_number = ?) LIMIT 1",
                    (str(album_id), clean, int(track_number)),
                )
            else:
                cur = self.conn.execute(
                    "SELECT * FROM library_tracks WHERE album_id = ? AND clean_title = ? LIMIT 1",
                    (str(album_id), clean),
                )
            row = cur.fetchone()
            return self._map_library_track(row) if row else None

    def list_library_tracks(
        self,
        album_id: Optional[str] = None,
        artist_id: Optional[str] = None,
        monitored_only: bool = False,
        query: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Lists library tracks filtered by album and/or artist with pagination."""
        sql = "SELECT * FROM library_tracks WHERE 1=1"
        params: list[Any] = []
        if album_id:
            sql += " AND album_id = ?"
            params.append(str(album_id))
        if artist_id:
            sql += " AND artist_id = ?"
            params.append(str(artist_id))
        if monitored_only:
            sql += " AND monitored = 1"
        if query:
            clean_q = clean_library_name(query)
            sql += " AND (clean_title LIKE ? OR title LIKE ?)"
            params.extend([f"%{clean_q}%", f"%{query}%"])
        sql += " ORDER BY disc_number ASC, track_number ASC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])

        with self._lock:
            cur = self.conn.execute(sql, params)
            return [self._map_library_track(row) for row in cur.fetchall()]

    def delete_library_track(self, track_id: str) -> bool:
        """Deletes a library track and cascades to child files."""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM library_tracks WHERE id = ?",
                (str(track_id),),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def set_track_monitored(self, track_id: str, monitored: bool) -> bool:
        """Sets monitoring status for a single library track."""
        val = 1 if monitored else 0
        with self._lock:
            cur = self.conn.execute(
                "UPDATE library_tracks SET monitored = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (val, str(track_id)),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def upsert_library_file(
        self, file_data: Union[LibraryFile, dict[str, Any]]
    ) -> dict[str, Any]:
        """Creates or updates a native library file."""
        d = file_data.to_dict() if hasattr(file_data, "to_dict") else dict(file_data)
        file_path = str(d.get("file_path") or "")

        with self._lock:
            if not d.get("id"):
                cur = self.conn.execute(
                    "SELECT id FROM library_files WHERE file_path = ?", (file_path,)
                )
                row = cur.fetchone()
                file_id = str(row[0]) if row else str(uuid.uuid4())
            else:
                file_id = str(d["id"])

            track_id = str(d.get("track_id") or "")
            relative_path = str(d.get("relative_path") or "")
            codec = str(d.get("codec") or "")
            bitrate = int(d["bitrate"]) if d.get("bitrate") is not None else None
            sample_rate = int(d["sample_rate"]) if d.get("sample_rate") is not None else None
            bits_per_sample = int(d["bits_per_sample"]) if d.get("bits_per_sample") is not None else None
            quality_name = str(d.get("quality_name") or "Unknown")
            size_bytes = int(d.get("size_bytes", 0))
            cutoff_met = 1 if d.get("cutoff_met", True) else 0
            date_added = d.get("date_added")

            self.conn.execute(
                """
                INSERT INTO library_files (
                    id, track_id, file_path, relative_path, codec, bitrate,
                    sample_rate, bits_per_sample, quality_name, size_bytes,
                    cutoff_met, date_added, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    track_id = excluded.track_id,
                    file_path = excluded.file_path,
                    relative_path = excluded.relative_path,
                    codec = excluded.codec,
                    bitrate = excluded.bitrate,
                    sample_rate = excluded.sample_rate,
                    bits_per_sample = excluded.bits_per_sample,
                    quality_name = excluded.quality_name,
                    size_bytes = excluded.size_bytes,
                    cutoff_met = excluded.cutoff_met,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    file_id,
                    track_id,
                    file_path,
                    relative_path,
                    codec,
                    bitrate,
                    sample_rate,
                    bits_per_sample,
                    quality_name,
                    size_bytes,
                    cutoff_met,
                    date_added,
                ),
            )
            self.conn.commit()

        fl = self.get_library_file(file_id)
        if fl is None:
            raise RuntimeError(f"Failed to upsert library file {file_id}")
        return fl

    def upsert_library_files_batch(
        self, files: list[Union[LibraryFile, dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        """Batched upsert for library files within a single transaction commit."""
        if not files:
            return []
        with self._lock:
            for file_data in files:
                d = file_data.to_dict() if hasattr(file_data, "to_dict") else dict(file_data)
                file_path = str(d.get("file_path") or "")

                if not d.get("id"):
                    cur = self.conn.execute(
                        "SELECT id FROM library_files WHERE file_path = ?", (file_path,)
                    )
                    row = cur.fetchone()
                    file_id = str(row[0]) if row else str(uuid.uuid4())
                else:
                    file_id = str(d["id"])

                track_id = str(d.get("track_id") or "")
                relative_path = str(d.get("relative_path") or "")
                codec = str(d.get("codec") or "")
                bitrate = int(d["bitrate"]) if d.get("bitrate") is not None else None
                sample_rate = int(d["sample_rate"]) if d.get("sample_rate") is not None else None
                bits_per_sample = int(d["bits_per_sample"]) if d.get("bits_per_sample") is not None else None
                quality_name = str(d.get("quality_name") or "Unknown")
                size_bytes = int(d.get("size_bytes", 0))
                cutoff_met = 1 if d.get("cutoff_met", True) else 0
                date_added = d.get("date_added")

                self.conn.execute(
                    """
                    INSERT INTO library_files (
                        id, track_id, file_path, relative_path, codec, bitrate,
                        sample_rate, bits_per_sample, quality_name, size_bytes,
                        cutoff_met, date_added, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET
                        track_id = excluded.track_id,
                        file_path = excluded.file_path,
                        relative_path = excluded.relative_path,
                        codec = excluded.codec,
                        bitrate = excluded.bitrate,
                        sample_rate = excluded.sample_rate,
                        bits_per_sample = excluded.bits_per_sample,
                        quality_name = excluded.quality_name,
                        size_bytes = excluded.size_bytes,
                        cutoff_met = excluded.cutoff_met,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        file_id,
                        track_id,
                        file_path,
                        relative_path,
                        codec,
                        bitrate,
                        sample_rate,
                        bits_per_sample,
                        quality_name,
                        size_bytes,
                        cutoff_met,
                        date_added,
                    ),
                )
            self.conn.commit()
            return [f.to_dict() if hasattr(f, "to_dict") else dict(f) for f in files]

    def get_library_file(self, file_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a library file by ID."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM library_files WHERE id = ?",
                (str(file_id),),
            )
            row = cur.fetchone()
            return self._map_library_file(row) if row else None

    def get_library_file_by_path(self, file_path: str) -> Optional[dict[str, Any]]:
        """Retrieves a library file by full file path."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM library_files WHERE file_path = ? LIMIT 1",
                (str(file_path),),
            )
            row = cur.fetchone()
            return self._map_library_file(row) if row else None

    def get_library_file_for_track(self, track_id: str) -> Optional[dict[str, Any]]:
        """Retrieves the file associated with a specific track ID."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM library_files WHERE track_id = ? LIMIT 1",
                (str(track_id),),
            )
            row = cur.fetchone()
            return self._map_library_file(row) if row else None

    def delete_library_file(self, file_id: str) -> bool:
        """Deletes a library file record."""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM library_files WHERE id = ?",
                (str(file_id),),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def list_library_files(
        self, limit: int = 500, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Lists library files ordered by date added with pagination."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM library_files ORDER BY date_added DESC LIMIT ? OFFSET ?",
                (int(limit), int(offset)),
            )
            return [self._map_library_file(row) for row in cur.fetchall()]

    def get_library_stats(self) -> dict[str, Any]:
        """Calculates aggregate statistics for the native library catalog."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM library_artists")
            artist_count = int(cur.fetchone()[0] or 0)

            cur.execute("SELECT COUNT(*) FROM library_albums")
            album_count = int(cur.fetchone()[0] or 0)

            cur.execute("SELECT COUNT(*) FROM library_tracks")
            track_count = int(cur.fetchone()[0] or 0)

            cur.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM library_files")
            row = cur.fetchone()
            file_count = int(row[0] or 0) if row else 0
            total_size_bytes = int(row[1] or 0) if row else 0

            cur.execute("SELECT COUNT(*) FROM library_artists WHERE monitored = 1")
            monitored_artist_count = int(cur.fetchone()[0] or 0)

            cur.execute("SELECT COUNT(*) FROM library_tracks WHERE monitored = 1")
            monitored_track_count = int(cur.fetchone()[0] or 0)

            cur.execute("SELECT COUNT(DISTINCT track_id) FROM library_files WHERE cutoff_met = 0")
            cutoff_unmet_track_count = int(cur.fetchone()[0] or 0)

            return {
                "artist_count": artist_count,
                "album_count": album_count,
                "track_count": track_count,
                "file_count": file_count,
                "total_size_bytes": total_size_bytes,
                "monitored_artist_count": monitored_artist_count,
                "monitored_track_count": monitored_track_count,
                "cutoff_unmet_track_count": cutoff_unmet_track_count,
            }

    # -------------------------------------------------------------------------
    # Download Blocklist CRUD
    # -------------------------------------------------------------------------

    def add_to_blocklist(
        self,
        source_title: str,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        release_guid: Optional[str] = None,
        info_hash: Optional[str] = None,
        protocol: Optional[str] = None,
        indexer: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Adds a release to the persistent download blocklist."""
        item_id = f"bl-{uuid.uuid4().hex[:12]}"
        clean_hash = info_hash.strip().lower() if info_hash else None
        clean_guid = release_guid.strip() if release_guid else None
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO download_blocklist (
                    id, source_title, artist, album, release_guid, info_hash,
                    protocol, indexer, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    item_id,
                    str(source_title).strip(),
                    str(artist).strip() if artist else None,
                    str(album).strip() if album else None,
                    clean_guid,
                    clean_hash,
                    str(protocol).strip().lower() if protocol else None,
                    str(indexer).strip() if indexer else None,
                    str(reason).strip() if reason else None,
                ),
            )
            self.conn.commit()
        item = self.get_blocklist_item(item_id)
        if item is None:
            raise RuntimeError(f"Failed to retrieve blocklist item {item_id}")
        return item

    def get_blocklist_item(self, blocklist_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a single blocklist entry by ID."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM download_blocklist WHERE id = ?",
                (str(blocklist_id),),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def is_blocklisted(
        self,
        release_title: Optional[str] = None,
        release_guid: Optional[str] = None,
        info_hash: Optional[str] = None,
    ) -> bool:
        """Checks if a release matches blocklist by info_hash (case-insensitive), guid, or title."""
        with self._lock:
            if info_hash:
                clean_hash = str(info_hash).strip()
                cur = self.conn.execute(
                    "SELECT 1 FROM download_blocklist WHERE LOWER(info_hash) = LOWER(?) LIMIT 1",
                    (clean_hash,),
                )
                if cur.fetchone():
                    return True

            if release_guid:
                clean_guid = str(release_guid).strip()
                cur = self.conn.execute(
                    "SELECT 1 FROM download_blocklist WHERE release_guid = ? LIMIT 1",
                    (clean_guid,),
                )
                if cur.fetchone():
                    return True

            if release_title:
                clean_rt = str(release_title).strip()
                cur = self.conn.execute(
                    "SELECT 1 FROM download_blocklist WHERE LOWER(source_title) = LOWER(?) LIMIT 1",
                    (clean_rt,),
                )
                if cur.fetchone():
                    return True

                target_clean = clean_library_name(clean_rt)
                if target_clean:
                    cur = self.conn.execute(
                        "SELECT source_title FROM download_blocklist WHERE source_title IS NOT NULL"
                    )
                    for row in cur.fetchall():
                        st = row["source_title"] or ""
                        if clean_library_name(st) == target_clean:
                            return True

        return False

    def list_blocklist(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Returns paginated download blocklist items ordered by created_at DESC."""
        with self._lock:
            cur = self.conn.execute(
                "SELECT * FROM download_blocklist ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (int(limit), int(offset)),
            )
            return [dict(r) for r in cur.fetchall()]

    def remove_from_blocklist(self, blocklist_id: str) -> bool:
        """Removes a download blocklist entry by ID."""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM download_blocklist WHERE id = ?",
                (str(blocklist_id),),
            )
            self.conn.commit()
            return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Catalog Wanted Queries
    # -------------------------------------------------------------------------

    def get_monitored_missing_catalog_tracks(
        self, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Queries tracks where artist, album, and track are monitored, but no file exists."""
        sql = """
            SELECT
                t.id AS track_id,
                t.title AS track_title,
                t.track_number AS track_number,
                t.disc_number AS disc_number,
                al.id AS album_id,
                al.title AS album_title,
                al.year AS year,
                ar.id AS artist_id,
                ar.name AS artist_name,
                ar.quality_profile_id AS quality_profile_id
            FROM library_tracks t
            JOIN library_albums al ON t.album_id = al.id
            JOIN library_artists ar ON t.artist_id = ar.id
            LEFT JOIN library_files f ON t.id = f.track_id
            WHERE t.monitored = 1
              AND al.monitored = 1
              AND ar.monitored = 1
              AND f.id IS NULL
            ORDER BY ar.name ASC, al.year ASC, t.disc_number ASC, t.track_number ASC
            LIMIT ?
        """
        with self._lock:
            cur = self.conn.execute(sql, (int(limit),))
            rows = []
            for r in cur.fetchall():
                d = dict(r)
                d["track_number"] = int(d.get("track_number") or 1)
                d["disc_number"] = int(d.get("disc_number") or 1)
                if d.get("year") is not None:
                    d["year"] = int(d["year"])
                rows.append(d)
            return rows

    def get_cutoff_unmet_catalog_tracks(
        self, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Queries tracks where artist, album, and track are monitored, but file cutoff_met is 0."""
        sql = """
            SELECT
                t.id AS track_id,
                t.title AS track_title,
                al.id AS album_id,
                al.title AS album_title,
                ar.id AS artist_id,
                ar.name AS artist_name,
                ar.quality_profile_id AS quality_profile_id,
                f.id AS file_id,
                f.quality_name AS quality_name,
                f.file_path AS file_path
            FROM library_tracks t
            JOIN library_albums al ON t.album_id = al.id
            JOIN library_artists ar ON t.artist_id = ar.id
            JOIN library_files f ON t.id = f.track_id
            WHERE t.monitored = 1
              AND al.monitored = 1
              AND ar.monitored = 1
              AND f.cutoff_met = 0
            ORDER BY ar.name ASC, al.year ASC, t.disc_number ASC, t.track_number ASC
            LIMIT ?
        """
        with self._lock:
            cur = self.conn.execute(sql, (int(limit),))
            return [dict(r) for r in cur.fetchall()]

    # -------------------------------------------------------------------------
    # Library Collections CRUD
    # -------------------------------------------------------------------------

    def _map_library_collection(self, row: sqlite3.Row) -> dict[str, Any]:
        res = dict(row)
        res["monitored"] = bool(res.get("monitored", 1))
        if "album_count" in res and res["album_count"] is not None:
            res["album_count"] = int(res["album_count"])
        else:
            res["album_count"] = 0
        if "preview_covers" not in res:
            res["preview_covers"] = []
        return res

    def upsert_library_collection(
        self, collection_data: Union[LibraryCollection, dict[str, Any]]
    ) -> dict[str, Any]:
        """Creates or updates a native library collection."""
        d = collection_data.to_dict() if hasattr(collection_data, "to_dict") else dict(collection_data)
        col_id = str(d.get("id") or uuid.uuid4())
        name = str(d.get("name") or "")
        clean_name = clean_library_name(d.get("clean_name") or name)
        summary = str(d["summary"]) if d.get("summary") is not None else None
        poster_url = str(d["poster_url"]) if d.get("poster_url") is not None else None
        monitored = 1 if d.get("monitored", True) else 0
        foreign_id = str(d["foreign_id"]) if d.get("foreign_id") is not None else None
        created_at = d.get("created_at")

        with self._lock:
            self.conn.execute(
                """
                INSERT INTO library_collections (
                    id, name, clean_name, summary, poster_url, monitored, foreign_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    clean_name = excluded.clean_name,
                    summary = COALESCE(excluded.summary, library_collections.summary),
                    poster_url = COALESCE(excluded.poster_url, library_collections.poster_url),
                    monitored = excluded.monitored,
                    foreign_id = COALESCE(excluded.foreign_id, library_collections.foreign_id),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (col_id, name, clean_name, summary, poster_url, monitored, foreign_id, created_at),
            )
            self.conn.commit()

        col = self.get_library_collection(col_id)
        if col is None:
            raise RuntimeError(f"Failed to upsert library collection {col_id}")
        return col

    def get_library_collection(self, collection_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a single library collection by ID with album count and preview covers."""
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT c.*, (
                    SELECT COUNT(*) FROM library_collection_albums ca WHERE ca.collection_id = c.id
                ) AS album_count
                FROM library_collections c
                WHERE c.id = ?
                """,
                (str(collection_id),),
            )
            row = cur.fetchone()
            if not row:
                return None
            col = self._map_library_collection(row)
            p_cur = self.conn.execute(
                """
                SELECT a.cover_url
                FROM library_albums a
                JOIN library_collection_albums ca ON a.id = ca.album_id
                WHERE ca.collection_id = ? AND a.cover_url IS NOT NULL AND a.cover_url != ''
                ORDER BY ca.order_index ASC
                LIMIT 4
                """,
                (str(collection_id),),
            )
            col["preview_covers"] = [r[0] for r in p_cur.fetchall() if r[0]]
            return col

    def list_library_collections(
        self, limit: int = 100, offset: int = 0, query: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Lists library collections with optional search query, album counts, preview covers, and pagination."""
        sql = """
            SELECT c.*, (
                SELECT COUNT(*) FROM library_collection_albums ca WHERE ca.collection_id = c.id
            ) AS album_count
            FROM library_collections c
            WHERE 1=1
        """
        params: list[Any] = []
        if query:
            clean_q = clean_library_name(query)
            sql += " AND (c.clean_name LIKE ? OR c.name LIKE ?)"
            params.extend([f"%{clean_q}%", f"%{query}%"])
        sql += " ORDER BY c.name COLLATE NOCASE ASC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])

        with self._lock:
            cur = self.conn.execute(sql, params)
            collections = [self._map_library_collection(row) for row in cur.fetchall()]
            for col in collections:
                col_id = col["id"]
                p_cur = self.conn.execute(
                    """
                    SELECT a.cover_url
                    FROM library_albums a
                    JOIN library_collection_albums ca ON a.id = ca.album_id
                    WHERE ca.collection_id = ? AND a.cover_url IS NOT NULL AND a.cover_url != ''
                    ORDER BY ca.order_index ASC
                    LIMIT 4
                    """,
                    (col_id,),
                )
                col["preview_covers"] = [r[0] for r in p_cur.fetchall() if r[0]]
            return collections

    def delete_library_collection(self, collection_id: str) -> bool:
        """Deletes a library collection and cascades to collection albums."""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM library_collections WHERE id = ?",
                (str(collection_id),),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def add_album_to_collection(
        self, collection_id: str, album_id: str, order_index: int = 0
    ) -> bool:
        """Associates an album with a collection."""
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO library_collection_albums (collection_id, album_id, order_index)
                VALUES (?, ?, ?)
                ON CONFLICT(collection_id, album_id) DO UPDATE SET
                    order_index = excluded.order_index
                """,
                (str(collection_id), str(album_id), int(order_index)),
            )
            self.conn.commit()
            return True

    def remove_album_from_collection(self, collection_id: str, album_id: str) -> bool:
        """Removes an album association from a collection."""
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM library_collection_albums WHERE collection_id = ? AND album_id = ?",
                (str(collection_id), str(album_id)),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def get_collection_albums(self, collection_id: str) -> list[dict[str, Any]]:
        """Retrieves all albums associated with a collection, ordered by order_index, year, title."""
        with self._lock:
            cur = self.conn.execute(
                """
                SELECT a.*, ca.order_index
                FROM library_collection_albums ca
                JOIN library_albums a ON a.id = ca.album_id
                WHERE ca.collection_id = ?
                ORDER BY ca.order_index ASC, a.year DESC, a.title COLLATE NOCASE ASC
                """,
                (str(collection_id),),
            )
            rows = cur.fetchall()
            results = []
            for r in rows:
                d = self._map_library_album(r)
                d["order_index"] = int(r["order_index"])
                results.append(d)
            return results

    # -------------------------------------------------------------------------
    # System Events CRUD
    # -------------------------------------------------------------------------

    def record_event(
        self,
        event_type: str,
        message: str,
        source: str = "system",
        severity: str = "info",
        details: Optional[dict[str, Any]] = None,
    ) -> int:
        """Records a system lifecycle event and enforces 5,000-row ring-buffer capping."""
        details_json = json.dumps(details) if details is not None else None
        sev = (severity or "info").lower().strip()
        with self._lock:
            cur = self.conn.execute(
                """
                INSERT INTO system_events (event_type, severity, source, message, details_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(event_type), sev, str(source), str(message), details_json),
            )
            event_id = int(cur.lastrowid)
            cur.execute(
                """
                DELETE FROM system_events
                WHERE id NOT IN (
                    SELECT id FROM system_events ORDER BY id DESC LIMIT 5000
                )
                """
            )
            self.conn.commit()
            return event_id

    def list_events(
        self,
        limit: int = 50,
        offset: int = 0,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        search: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Queries system events with dynamic filtering and returns (items, total_count)."""
        where_clauses: list[str] = []
        params: list[Any] = []

        if event_type:
            where_clauses.append("event_type = ?")
            params.append(event_type)

        if severity and severity.lower() != "all":
            where_clauses.append("LOWER(severity) = ?")
            params.append(severity.lower().strip())

        if search:
            where_clauses.append("(message LIKE ? OR source LIKE ?)")
            s_param = f"%{search}%"
            params.extend([s_param, s_param])

        where_sql = f" WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        with self._lock:
            count_cur = self.conn.execute(
                f"SELECT COUNT(*) FROM system_events{where_sql}",
                tuple(params),
            )
            total = int(count_cur.fetchone()[0])

            item_params = list(params) + [limit, offset]
            cur = self.conn.execute(
                f"""
                SELECT id, event_type, severity, source, message, details_json, created_at
                FROM system_events{where_sql}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(item_params),
            )
            rows = cur.fetchall()

        items: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d_json = d.get("details_json")
            if d_json:
                try:
                    d["details"] = json.loads(d_json)
                except Exception:
                    d["details"] = None
            else:
                d["details"] = None
            items.append(d)

        return items, total

    def clear_events(self) -> None:
        """Deletes all system events from the database."""
        with self._lock:
            self.conn.execute("DELETE FROM system_events")
            self.conn.commit()





