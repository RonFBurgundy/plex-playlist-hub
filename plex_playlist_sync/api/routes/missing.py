"""Missing tracks reporting, CSV export, RSS feeds, and Lidarr integration routes."""

import csv
from email.utils import formatdate
import io
import logging
from typing import Any, Optional
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from plex_playlist_sync.api.dependencies import (
    get_config,
    get_current_user,
    get_db,
    get_lidarr_client,
    verify_feed_access,
)
from plex_playlist_sync.clients.lidarr import LidarrClient
from plex_playlist_sync.config import Config
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()


class LidarrPushRequest(BaseModel):
    track_ids: Optional[list[int]] = Field(default=None, description="Optional list of specific missing track IDs to push")
    auto_search: Optional[bool] = Field(default=None, description="Override auto_search setting")


def _sanitize_csv_cell(value: Any) -> str:
    """Sanitizes CSV cell to prevent formula injection attacks.

    Prefixes leading dangerous characters (=, +, -, @, tab, CR) with a single quote.
    """
    text = str(value if value is not None else "")
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{text}"
    return text


def _filter_missing_for_user(
    all_tracks: list[dict[str, Any]],
    user_context: Optional[dict[str, Any]],
    db: Database,
) -> list[dict[str, Any]]:
    """Applies RBAC filtering: Admins and feed tokens see all; standard users see only their targeted playlists;

    LAN readers without a token see only public/shared playlists.
    """
    if not user_context:
        return []
    if bool(user_context.get("is_admin")):
        return all_tracks
    if user_context.get("id") == "lan_reader":
        all_playlists = db.list_playlists()
        shared_ids = {p["id"] for p in all_playlists if not p.get("creator_id") or p.get("creator_id") in ("admin", "admin_1")}
        return [t for t in all_tracks if t.get("playlist_id") in shared_ids]

    user_playlists = {p["id"] for p in db.list_playlists(user_id=str(user_context["id"]))}
    return [t for t in all_tracks if t.get("playlist_id") in user_playlists]


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


@router.get("/rss")
def feed_missing_rss(
    playlist_id: Optional[str] = Query(default=None, description="Optional playlist ID filter"),
    token: Optional[str] = Query(default=None, description="Optional feed token or API key"),
    user_context: Optional[dict[str, Any]] = Depends(verify_feed_access),
    db: Database = Depends(get_db),
) -> Response:
    """Generates an RSS 2.0 XML feed of missing music for Lidarr and RSS clients."""
    all_tracks = db.get_missing_tracks(playlist_id=playlist_id)
    filtered = _filter_missing_for_user(all_tracks, user_context, db)

    playlists_map = {p["id"]: p["name"] for p in db.list_playlists()}
    now_rfc822 = formatdate(usegmt=True)

    items_xml = []
    for t in filtered:
        p_name = playlists_map.get(t.get("playlist_id", ""), t.get("playlist_id", ""))
        title = escape(f"{t.get('artist', '')} - {t.get('title', '')}")
        album = escape(t.get("album", "") or "Unknown Album")
        artist = escape(t.get("artist", "") or "Unknown Artist")
        track_title = escape(t.get("title", ""))
        pl_name_esc = escape(p_name)
        guid = f"plex-playlist-hub-missing-{t.get('id', 0)}"

        def _clean_cdata(val: Any) -> str:
            return str(val or "").replace("]]>", "]]&gt;")

        desc = (
            f"<![CDATA[Track: {_clean_cdata(track_title)}<br/>Artist: {_clean_cdata(artist)}<br/>Album: {_clean_cdata(album)}<br/>Playlist: {_clean_cdata(pl_name_esc)}]]>"
        )

        item = f"""    <item>
      <title>{title}</title>
      <description>{desc}</description>
      <guid isPermaLink="false">{guid}</guid>
      <pubDate>{now_rfc822}</pubDate>
      <category>{pl_name_esc}</category>
    </item>"""
        items_xml.append(item)

    items_block = "\n".join(items_xml)
    channel_desc = "Missing tracks unmatched in Plex Media Server music library"
    if playlist_id and playlist_id in playlists_map:
        channel_desc += f" for playlist {playlists_map[playlist_id]}"

    rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Plex Playlist Hub - Missing Music</title>
    <description>{escape(channel_desc)}</description>
    <link>http://localhost:5250</link>
    <language>en-us</language>
    <lastBuildDate>{now_rfc822}</lastBuildDate>
{items_block}
  </channel>
</rss>"""

    return Response(content=rss_xml, media_type="application/rss+xml; charset=utf-8")


@router.get("/lidarr")
def feed_missing_lidarr(
    playlist_id: Optional[str] = Query(default=None, description="Optional playlist ID filter"),
    token: Optional[str] = Query(default=None, description="Optional feed token or API key"),
    user_context: Optional[dict[str, Any]] = Depends(verify_feed_access),
    db: Database = Depends(get_db),
) -> list[dict[str, Any]]:
    """Returns a deduplicated JSON list formatted for Lidarr Custom Import Lists."""
    all_tracks = db.get_missing_tracks(playlist_id=playlist_id)
    filtered = _filter_missing_for_user(all_tracks, user_context, db)
    playlists_map = {p["id"]: p["name"] for p in db.list_playlists()}

    seen = set()
    lidarr_items = []
    for t in filtered:
        key = (
            (t.get("artist") or "").strip().lower(),
            (t.get("album") or t.get("title") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        p_name = playlists_map.get(t.get("playlist_id", ""), t.get("playlist_id", ""))
        lidarr_items.append({
            "artist": t.get("artist", "").strip(),
            "album": t.get("album", "").strip(),
            "title": t.get("title", "").strip(),
            "playlist": p_name,
            "foreignId": f"missing-{t.get('id', 0)}",
        })

    return lidarr_items


@router.get("/text")
def feed_missing_text(
    playlist_id: Optional[str] = Query(default=None, description="Optional playlist ID filter"),
    token: Optional[str] = Query(default=None, description="Optional feed token or API key"),
    user_context: Optional[dict[str, Any]] = Depends(verify_feed_access),
    db: Database = Depends(get_db),
) -> Response:
    """Returns a plain text list of missing tracks (one per line)."""
    all_tracks = db.get_missing_tracks(playlist_id=playlist_id)
    filtered = _filter_missing_for_user(all_tracks, user_context, db)
    seen = set()
    lines = []
    for t in filtered:
        line = f"{t.get('artist', '').strip()} - {t.get('title', '').strip()}"
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return Response(content="\n".join(lines) + ("\n" if lines else ""), media_type="text/plain; charset=utf-8")


@router.get("/lidarr/status")
def get_lidarr_status(
    _current_user: dict[str, Any] = Depends(get_current_user),
    config: Config = Depends(get_config),
    lidarr_client: Optional[LidarrClient] = Depends(get_lidarr_client),
) -> dict[str, Any]:
    """Returns Lidarr connection and configuration status."""
    if not config.has_lidarr or lidarr_client is None:
        return {
            "configured": False,
            "url": None,
            "auto_search": False,
            "status": {"online": False, "message": "Lidarr is not configured in environment (LIDARR_URL and LIDARR_API_KEY)"},
        }
    conn_result = lidarr_client.test_connection()
    return {
        "configured": True,
        "url": config.lidarr_url,
        "auto_search": config.lidarr_auto_search,
        "status": conn_result,
    }


@router.post("/lidarr/push")
def push_missing_to_lidarr(
    req: Optional[LidarrPushRequest] = None,
    current_user: dict[str, Any] = Depends(get_current_user),
    config: Config = Depends(get_config),
    db: Database = Depends(get_db),
    lidarr_client: Optional[LidarrClient] = Depends(get_lidarr_client),
) -> dict[str, Any]:
    """Pushes missing tracks directly into Lidarr to queue download and monitoring."""
    if not config.has_lidarr or lidarr_client is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lidarr is not configured. Set LIDARR_URL and LIDARR_API_KEY.",
        )

    all_tracks = db.get_missing_tracks()
    filtered = _filter_missing_for_user(all_tracks, current_user, db)

    target_ids = set(req.track_ids) if (req and req.track_ids is not None) else None
    if target_ids is not None:
        filtered = [t for t in filtered if t.get("id") in target_ids]

    # Deduplicate items by (artist, album)
    seen = set()
    deduped = []
    for t in filtered:
        key = ((t.get("artist") or "").strip().lower(), (t.get("album") or "").strip().lower())
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    should_search = req.auto_search if (req and req.auto_search is not None) else config.lidarr_auto_search
    results = []
    added_count = 0
    monitored_count = 0
    failed_count = 0

    for item in deduped:
        artist = item.get("artist", "").strip()
        album = item.get("album", "").strip()
        title = item.get("title", "").strip()
        res = lidarr_client.search_and_add_track(
            artist_name=artist,
            album_name=album,
            title=title,
            auto_search=should_search,
        )
        results.append(res)
        if res.get("status") == "added":
            added_count += 1
        elif res.get("status") == "already_monitored":
            monitored_count += 1
        else:
            failed_count += 1

    return {
        "total_requested": len(filtered),
        "deduplicated_items": len(deduped),
        "added": added_count,
        "already_monitored": monitored_count,
        "failed": failed_count,
        "results": results,
    }
