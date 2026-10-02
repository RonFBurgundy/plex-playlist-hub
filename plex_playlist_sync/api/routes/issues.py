"""Media Issues REST API endpoints for user reporting and resolution workflows."""

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from plex_playlist_sync.api.dependencies import (
    get_db,
    has_permission,
    require_permission,
    require_user,
)
from plex_playlist_sync.models import NotificationEvent, UserPermission
from plex_playlist_sync.notifications import notification_dispatcher
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateIssueBody(BaseModel):
    media_title: str
    artist: str
    issue_type: str
    problem_details: str
    request_id: Optional[str] = None


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
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_user),
) -> list[dict[str, Any]]:
    """Lists issues. Filterable by status. Admin or MANAGE_REQUESTS see all; regular users see only their own."""
    is_manager = bool(
        current_user.get("is_admin")
        or has_permission(current_user, UserPermission.MANAGE_REQUESTS)
    )
    user_id_filter = None if is_manager else current_user["id"]
    return db.list_issues(status=status_filter, user_id=user_id_filter)


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
    """Creates an issue, emits ISSUE_REPORTED notification event, and returns the created issue."""
    issue_id = f"issue-{uuid.uuid4().hex[:12]}"
    issue_data = {
        "id": issue_id,
        "user_id": current_user["id"],
        "media_title": body.media_title.strip(),
        "artist": body.artist.strip(),
        "issue_type": body.issue_type.strip(),
        "problem_details": body.problem_details.strip(),
        "request_id": body.request_id.strip() if body.request_id else None,
        "status": "open",
    }
    created = db.create_issue(issue_data)

    notification_data = dict(created)
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
    """Retrieves an issue by ID. If non-admin/non-manager and not owner, raises 403 Forbidden."""
    issue = db.get_issue(issue_id)
    if not issue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media issue {issue_id} not found",
        )
    is_manager = bool(
        current_user.get("is_admin")
        or has_permission(current_user, UserPermission.MANAGE_REQUESTS)
    )
    if not is_manager and issue["user_id"] != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: cannot view this issue",
        )
    return issue


@router.put("/{issue_id}", response_model=IssueResponse, summary="Update media issue")
def update_issue(
    issue_id: str,
    body: UpdateIssueBody,
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Updates issue. Admin or MANAGE_REQUESTS can update status and problem_details.

    Regular owners can only update problem_details if status is still open.
    """
    issue = db.get_issue(issue_id)
    if not issue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media issue {issue_id} not found",
        )

    is_manager = bool(
        current_user.get("is_admin")
        or has_permission(current_user, UserPermission.MANAGE_REQUESTS)
    )
    is_owner = issue["user_id"] == current_user["id"]
    if not is_manager and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: cannot update this issue",
        )

    updates: dict[str, Any] = {}
    if is_manager:
        if body.status is not None:
            updates["status"] = body.status
        if body.problem_details is not None:
            updates["problem_details"] = body.problem_details
    else:
        # Regular owner
        if issue["status"] != "open":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot update issue once it is no longer open",
            )
        if body.status is not None and body.status != "open":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: cannot modify issue status",
            )
        if body.problem_details is not None:
            updates["problem_details"] = body.problem_details

    if updates:
        return db.update_issue(issue_id, updates)
    return issue


@router.delete("/{issue_id}", summary="Delete media issue")
def delete_issue(
    issue_id: str,
    db: Database = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Deletes an issue. Admin or owner can delete."""
    issue = db.get_issue(issue_id)
    if not issue:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Media issue {issue_id} not found",
        )

    is_admin = bool(
        current_user.get("is_admin")
        or has_permission(current_user, UserPermission.ADMIN)
    )
    is_owner = issue["user_id"] == current_user["id"]
    if not (is_admin or is_owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: cannot delete this issue",
        )

    deleted = db.delete_issue(issue_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete issue",
        )

    return {"status": "deleted", "id": issue_id}
