"""Integration and unit tests for AcquisitionWorker and safe atomic library placement."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from plex_playlist_sync.acquisition_worker import AcquisitionWorker, safe_atomic_move
from plex_playlist_sync.models import (
    ActiveDownload,
    DownloadClientConfig,
    DownloadDriverType,
    DownloadStatus,
    MusicRequest,
    RequestStatus,
)
from plex_playlist_sync.storage import Database


@pytest.fixture
def test_db():
    db = Database(":memory:")
    yield db
    db.close()


@pytest.fixture
def workspace_dirs(tmp_path):
    downloads_dir = tmp_path / "downloads"
    music_dir = tmp_path / "music"
    downloads_dir.mkdir()
    music_dir.mkdir()
    return downloads_dir, music_dir


# ---------------------------------------------------------------------------
# safe_atomic_move Tests
# ---------------------------------------------------------------------------
def test_safe_atomic_move_success(tmp_path):
    src = tmp_path / "temp_download.flac"
    src.write_text("audio sample binary content")

    dst = tmp_path / "library" / "Artist" / "Album" / "track.flac"

    result_path = safe_atomic_move(src, dst)
    assert result_path == dst
    assert dst.exists()
    assert not src.exists()
    assert dst.read_text() == "audio sample binary content"


def test_safe_atomic_move_missing_src(tmp_path):
    src = tmp_path / "nonexistent.mp3"
    dst = tmp_path / "library" / "track.mp3"
    with pytest.raises(FileNotFoundError):
        safe_atomic_move(src, dst)


# ---------------------------------------------------------------------------
# AcquisitionWorker Tests
# ---------------------------------------------------------------------------
def test_worker_poll_once_downloading(test_db, workspace_dirs):
    downloads_dir, music_dir = workspace_dirs

    # Seed client
    client = test_db.create_download_client(
        DownloadClientConfig(
            id="client-slskd-1",
            name="Test Slskd",
            driver_type=DownloadDriverType.SLSKD,
            host_url="http://slskd:5030",
        )
    )

    # Seed active download
    download = test_db.create_active_download(
        ActiveDownload(
            id="dl-active-1",
            title="Daft Punk - One More Time",
            artist="Daft Punk",
            client_id="client-slskd-1",
            download_hash="dl-hash-123",
            status=DownloadStatus.DOWNLOADING.value,
        )
    )

    worker = AcquisitionWorker()

    mock_driver = MagicMock()
    mock_driver.get_status.return_value = {
        "status": DownloadStatus.DOWNLOADING.value,
        "progress": 55.0,
        "size_bytes": 10000000,
        "speed_bps": 250000,
        "eta_seconds": 30,
        "source_path": None,
        "error_message": None,
    }

    with patch("plex_playlist_sync.acquisition_worker.get_acquisition_driver", return_value=mock_driver):
        stats = worker.poll_once(db=test_db, staging_dir=str(downloads_dir))
        assert stats["polled"] == 1

    updated = test_db.get_active_download("dl-active-1")
    assert updated is not None
    assert updated["progress"] == 55.0


def test_worker_poll_once_completed_and_organizes(test_db, workspace_dirs):
    downloads_dir, music_dir = workspace_dirs

    # Seed client
    client = test_db.create_download_client(
        DownloadClientConfig(
            id="client-sab-1",
            name="Test SABnzbd",
            driver_type=DownloadDriverType.SABNZBD,
            host_url="http://sabnzbd:8080",
            api_key="secret",
        )
    )

    # Seed user and request
    user = test_db.upsert_user("user-1", "dj_bob", "bob@example.com")
    req = test_db.create_request(
        MusicRequest(
            id="req-101",
            user_id="user-1",
            item_type="track",
            title="Get Lucky",
            artist="Daft Punk",
            album="Random Access Memories",
            status=RequestStatus.PROCESSING,
        )
    )

    # Seed active download linked to request
    download = test_db.create_active_download(
        ActiveDownload(
            id="dl-sab-101",
            title="Get Lucky",
            artist="Daft Punk",
            client_id="client-sab-1",
            download_hash="nzo-999",
            status=DownloadStatus.DOWNLOADING.value,
            request_id="req-101",
        )
    )

    # Create dummy downloaded audio file in downloads directory
    dl_file = downloads_dir / "03 - Get Lucky.mp3"
    dl_file.write_text("dummy mp3 audio content")

    mock_driver = MagicMock()
    mock_driver.get_status.return_value = {
        "status": DownloadStatus.COMPLETED.value,
        "progress": 100.0,
        "size_bytes": len("dummy mp3 audio content"),
        "speed_bps": 0,
        "eta_seconds": 0,
        "source_path": str(dl_file),
        "error_message": None,
    }

    mock_plex = MagicMock()
    worker = AcquisitionWorker()

    mock_meta = {
        "artist": "Daft Punk",
        "title": "Get Lucky",
        "album": "Random Access Memories",
        "file_path": str(dl_file),
        "extension": ".mp3",
        "track_number": 3,
        "year": 2013,
        "disc_number": 1,
        "total_discs": 1,
    }

    # Set media management root path to music_dir
    settings = test_db.get_media_management_settings()
    settings["root_folder_path"] = str(music_dir)
    test_db.update_media_management_settings(settings)

    with patch("plex_playlist_sync.acquisition_worker.get_acquisition_driver", return_value=mock_driver):
        with patch("plex_playlist_sync.acquisition_worker.inspect_audio_file", return_value=mock_meta):
            stats = worker.poll_once(db=test_db, plex_client=mock_plex, staging_dir=str(downloads_dir))
            assert stats["completed"] == 1
            assert stats["imported"] == 1

    # Verify download record marked IMPORTED
    updated_dl = test_db.get_active_download("dl-sab-101")
    assert updated_dl is not None
    assert updated_dl["status"] == DownloadStatus.IMPORTED.value
    assert updated_dl["target_path"] is not None
    assert os.path.exists(updated_dl["target_path"])

    # Verify linked request marked AVAILABLE
    updated_req = test_db.get_request("req-101")
    assert updated_req is not None
    assert updated_req["status"] == RequestStatus.AVAILABLE.value

    # Verify Plex library refresh pinged
    mock_plex.refresh_music_library.assert_called_once()


def test_worker_poll_once_failed(test_db, workspace_dirs):
    downloads_dir, music_dir = workspace_dirs

    client = test_db.create_download_client(
        DownloadClientConfig(
            id="client-qbit-1",
            name="Test Qbit",
            driver_type=DownloadDriverType.QBITTORRENT,
            host_url="http://qbit:8080",
        )
    )

    download = test_db.create_active_download(
        ActiveDownload(
            id="dl-bad-1",
            title="Corrupted Torrent",
            artist="Unknown Artist",
            client_id="client-qbit-1",
            download_hash="hash-bad",
            status=DownloadStatus.DOWNLOADING.value,
        )
    )

    mock_driver = MagicMock()
    mock_driver.get_status.return_value = {
        "status": DownloadStatus.FAILED.value,
        "progress": 0.0,
        "error_message": "CRC check failed",
    }

    worker = AcquisitionWorker()

    with patch("plex_playlist_sync.acquisition_worker.get_acquisition_driver", return_value=mock_driver):
        stats = worker.poll_once(db=test_db, staging_dir=str(downloads_dir))
        assert stats["failed"] == 1

    updated = test_db.get_active_download("dl-bad-1")
    assert updated["status"] == DownloadStatus.FAILED.value
    assert updated["error_message"] == "CRC check failed"


def test_worker_lifecycle(test_db, workspace_dirs):
    downloads_dir, _ = workspace_dirs
    worker = AcquisitionWorker()

    started = worker.start(
        db=test_db,
        poll_interval=0.1,
        staging_dir=str(downloads_dir),
    )
    assert started is True
    assert worker.is_running() is True

    worker.stop(timeout=1.0)
    assert worker.is_running() is False
