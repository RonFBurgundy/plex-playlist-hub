"""Missing tracks reporting and CSV export routes."""

import csv
import io
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from plex_playlist_sync.api.dependencies import get_current_user, get_db
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()


def _sanitize_csv_cell(value: Any) -> str:
    """Sanitizes CSV cell to prevent formula injection attacks.

    Prefixes leading dangerous characters (=, +, -, @, tab, CR) with a single quote.
    """
    text = str(value if value is not None else "")
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{text}"
    return text


@router.get("")
def get_missing_tracks(
    playlist_id: Optional[str] = Query(default=None, description="Optional playlist ID filter"),
    current_user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Returns missing tracks list.

    Admins can view all or filtered by playlist_id.
    Regular users only see missing tracks for playlists targeted to them.
    """
    is_admin = bool(current_user.get("is_admin"))

    if not is_admin:
        user_playlists = {p["id"] for p in db.list_playlists(user_id=str(current_user["id"]))}
        if playlist_id:
            if playlist_id not in user_playlists:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to requested playlist missing tracks",
                )
            return db.get_missing_tracks(playlist_id=playlist_id)
        all_tracks = db.get_missing_tracks()
        return [t for t in all_tracks if t["playlist_id"] in user_playlists]

    return db.get_missing_tracks(playlist_id=playlist_id)


@router.get("/csv")
def download_missing_csv(
    playlist_id: Optional[str] = Query(default=None, description="Optional playlist ID filter"),
    current_user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> StreamingResponse:
    """Generates and streams a safe CSV download of missing tracks."""
    tracks = get_missing_tracks(playlist_id=playlist_id, current_user=current_user, db=db)

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Header
    writer.writerow(["Playlist ID", "Title", "Artist", "Album", "URL", "Created At"])

    for t in tracks:
        writer.writerow([
            _sanitize_csv_cell(t.get("playlist_id", "")),
            _sanitize_csv_cell(t.get("title", "")),
            _sanitize_csv_cell(t.get("artist", "")),
            _sanitize_csv_cell(t.get("album", "")),
            _sanitize_csv_cell(t.get("url", "")),
            _sanitize_csv_cell(t.get("created_at", "")),
        ])

    csv_bytes = output.getvalue().encode("utf-8")
    filename = f"missing_tracks_{playlist_id}.csv" if playlist_id else "missing_tracks.csv"

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
