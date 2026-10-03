"""Media Issues REST API endpoints for user reporting and resolution workflows."""

import logging
import re
import uuid
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, StringConstraints, field_validator

from plex_playlist_sync.api.dependencies import (
    get_db,
    has_permission,
    require_admin,
    require_permission,
    require_user,
)
from plex_playlist_sync.models import IssueType, NotificationEvent, UserPermission
from plex_playlist_sync.notifications import notification_dispatcher
from plex_playlist_sync.request_submission import user_request_lock
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()

ISSUE_DAILY_LIMIT = 10
ISSUE_NOTIFICATION_DETAILS_MAX = 500

_Stripped = Annotated[str, StringConstraints(strip_whitespace=True)]
# Control characters (C0 range, DEL, C1 range) other than \n and \t.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _is_admin(user: dict[str, Any]) -> bool:
    """True only for a real admin session or API key; gateway-forwarded principals never qualify."""
    if user.get("forwarded"):
        return False
    return bool(user.get("is_admin") or has_permission(user, UserPermission.ADMIN))


class CreateIssueBody(BaseModel):
    media_title: _Stripped = Field(min_length=1, max_length=300)
    artist: _Stripped = Field(min_length=1, max_length=300)
    issue_type: IssueType
    problem_details: _Stripped = Field(min_length=1, max_length=2000)
    request_id: Optional[_Stripped] = Field(default=None, max_length=200)

    @field_validator("media_title", "artist", "problem_details")
    @classmethod
    def _no_control_chars(cls, value: str) -> str:
        if _CONTROL_CHARS.search(value):
            raise ValueError("must not contain control characters")
        return value

    @field_validator("request_id")
    @classmethod
    def _blank_request_id_is_none(cls, value: Optional[str]) -> Optional[str]:
        return value or None


class UpdateIssueBody(BaseModel):
    status: Optional[str] = None
    problem_details: Optional[str] = None


class IssueResponse(BaseModel):
    id: str
    media_title: str
    artist: str
    issue_type: str
    problem_details: str
    status: str
    user_id: str
    request_id: Optional[str] = None
    username: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@router.get("", response_model=list[IssueResponse], summary="List media issues")
@router.get("/", response_model=list[IssueResponse], include_in_schema=False)
def list_issues(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    media_title: Optional[str] = Query(default=None, max_length=300),
    artist: Optional[str] = Query(default=None, max_length=300),
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_user),
) -> list[dict[str, Any]]:
    """Lists issues. Filterable by status, media_title and artist (exact, case-insensitive).

    Admins see all; regular users see only their own, regardless of filters.
    """
    user_id_filter = None if _is_admin(current_user) else current_user["id"]
    return db.list_issues(
        status=status_filter,
        user_id=user_id_filter,
        media_title=(media_title or "").strip() or None,
        artist=(artist or "").strip() or None,
    )


@router.post(
    "",
    response_model=IssueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Report a media issue",
)
@router.post(
    "/",
    response_model=IssueResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_issue(
    body: CreateIssueBody,
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_permission(UserPermission.REPORT_ISSUE)),
) -> dict[str, Any]:
    """Creates an issue, emits ISSUE_REPORTED notification event, and returns the created issue.

    Rejections: 404 (request_id not owned/unknown), 409 (duplicate open issue), 429 (24h cap).
    """
    is_admin = _is_admin(current_user)
    user_id = str(current_user["id"])

    if body.request_id:
        request = db.get_request(body.request_id)
        if not request or (not is_admin and str(request["user_id"]) != user_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Request {body.request_id} not found",
            )

    issue_type = body.issue_type.value
    with user_request_lock(user_id):
        duplicate = db.find_active_duplicate_issue(user_id, body.media_title, body.artist, issue_type)
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"You already have an open issue for this item (issue {duplicate['id']})",
            )
        if not is_admin and db.count_recent_issues(user_id, hours=24) >= ISSUE_DAILY_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Issue limit reached: at most {ISSUE_DAILY_LIMIT} issues per 24 hours",
            )
        created = db.create_issue(
            {
                "id": f"issue-{uuid.uuid4().hex[:12]}",
                "user_id": user_id,
                "media_title": body.media_title,
                "artist": body.artist,
                "issue_type": issue_type,
                "problem_details": body.problem_details,
                "request_id": body.request_id,
                "status": "open",
            }
        )

    notification_data = dict(created)
    notification_data["problem_details"] = str(created.get("problem_details") or "")[
        :ISSUE_NOTIFICATION_DETAILS_MAX
    ]
    if not notification_data.get("username"):
        notification_data["username"] = current_user.get("username")
    notification_data.setdefault("title", created.get("media_title"))
    notification_dispatcher.dispatch(NotificationEvent.ISSUE_REPORTED, notification_data, db)

    return created


@router.get("/{issue_id}", response_model=IssueResponse, summary="Get media issue by ID")
def get_issue(
    issue_id: str,
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Retrieves an issue by ID. Non-admins get 404 for issues they do not own."""
    issue = db.get_issue(issue_id)
    if not issue or (not _is_admin(current_user) and str(issue["user_id"]) != str(current_user["id"])):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media issue {issue_id} not found",
        )
    return issue


@router.put("/{issue_id}", response_model=IssueResponse, summary="Update media issue")
def update_issue(
    issue_id: str,
    body: UpdateIssueBody,
    db: Database = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Admin-only: updates issue status and problem_details."""
    issue = db.get_issue(issue_id)
    if not issue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media issue {issue_id} not found",
        )

    updates: dict[str, Any] = {}
    if body.status is not None:
        updates["status"] = body.status
    if body.problem_details is not None:
        updates["problem_details"] = body.problem_details

    if updates:
        return db.update_issue(issue_id, updates)
    return issue


@router.delete("/{issue_id}", summary="Delete media issue")
def delete_issue(
    issue_id: str,
    db: Database = Depends(get_db),
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Admin-only: deletes an issue."""
    issue = db.get_issue(issue_id)
    if not issue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media issue {issue_id} not found",
        )

    deleted = db.delete_issue(issue_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete issue",
        )

    return {"status": "deleted", "id": issue_id}
