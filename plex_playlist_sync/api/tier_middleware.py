"""ASGI middleware for the two-tier (DMZ) security model.

* ``SignedBodyMiddleware`` (all roles) hashes the body of gateway-signed requests so the
  synchronous auth dependency can verify the signature without consuming the body.
* ``GatewayGuardMiddleware`` (active only when ``role == "gateway"``) is deny-by-default:
  every ``/api/*`` path outside ``GATEWAY_LOCAL_ALLOWLIST`` / ``GATEWAY_FORWARD_ALLOWLIST``
  returns 404, and forward-listed paths are relayed to core through ``CoreClient.proxy``
  as the signed-in user.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from plex_playlist_sync.clients.core_client import CoreClient
from plex_playlist_sync.internal_auth import HEADER_SIGNATURE

logger = logging.getLogger(__name__)

MAX_PROXY_BODY_BYTES = 1024 * 1024  # 1 MiB cap on bodies relayed to core
MAX_SIGNED_BODY_BYTES = 1024 * 1024  # core-side cap for signed requests (1 MiB)

READ = frozenset({"GET", "HEAD"})
ALL_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})

# A template segment "{}" matches exactly one path segment; a trailing "/**" matches the
# prefix itself and anything below it. Everything else must match exactly.

# Endpoints the gateway serves from its own process (no forwarding by the middleware).
GATEWAY_LOCAL_ALLOWLIST: tuple[tuple[frozenset[str], str], ...] = (
    (READ, "/api/health"),  # container/orchestrator health check
    (frozenset({"POST"}), "/api/auth/plex/pin"),  # sign-in: start the Plex PIN flow
    (frozenset({"POST"}), "/api/auth/plex/verify"),  # sign-in: claim the PIN and create the session
    (frozenset({"POST"}), "/api/auth/logout"),  # sign-out
    (READ, "/api/auth/me"),  # session user + tier
    (READ, "/api/users/me"),  # profile, permissions and quota telemetry
    (READ, "/api/discovery/trending"),  # discovery: trending
    (READ, "/api/discovery/new-releases"),  # discovery: new releases
    (READ, "/api/discovery/search"),  # discovery: search
    (READ, "/api/discovery/album/{}"),  # discovery: album detail
    (READ, "/api/discovery/artist/{}"),  # discovery: artist detail
    (frozenset({"POST"}), "/api/requests"),  # create a request (route forwards to core)
    (frozenset({"POST"}), "/api/requests/batch"),  # batch create (route forwards to core)
    (READ, "/api/library/availability"),  # availability lookup (route forwards to core)
)

# User-scoped endpoints the gateway relays to core as the signed-in user.
GATEWAY_FORWARD_ALLOWLIST: tuple[tuple[frozenset[str], str], ...] = (
    (READ, "/api/requests"),  # list the signed-in user's own requests (state lives on core)
    (frozenset({"DELETE"}), "/api/requests/{}"),  # cancel own pending request (core checks ownership)
    (ALL_METHODS, "/api/playlists/**"),  # user's own sync playlists (core enforces ownership)
    (frozenset({"GET", "POST"}), "/api/issues"),  # list own issues / report an issue
    (READ, "/api/issues/{}"),  # view own issue (core returns 404 for others')
    (ALL_METHODS, "/api/plex-playlists/**"),  # user's own Plex playlists (core enforces ownership)
    (ALL_METHODS, "/api/mixes/**"),  # tailored mixes
    (frozenset({"GET", "PUT"}), "/api/scrobbles/config"),  # own scrobble settings
    (READ, "/api/scrobbles/listens"),  # own listen history
    (READ, "/api/scrobbles/lastfm/auth-url"),  # begin Last.fm connect
    (READ, "/api/scrobbles/lastfm/callback"),  # Last.fm return; core's 303 Location is passed through
)


def _template_matches(template: str, path: str) -> bool:
    if template.endswith("/**"):
        prefix = template[:-3]
        return path == prefix or path.startswith(prefix + "/")
    t_parts = template.split("/")
    p_parts = path.split("/")
    if len(t_parts) != len(p_parts):
        return False
    for t, p in zip(t_parts, p_parts):
        if t == "{}":
            if not p:
                return False
        elif t != p:
            return False
    return True


def _allowed(table: tuple[tuple[frozenset[str], str], ...], method: str, path: str) -> bool:
    return any(method in methods and _template_matches(tpl, path) for methods, tpl in table)


def _path_is_clean(raw_path: str) -> bool:
    """Rejects traversal, backslashes, empty segments and encoded separators."""
    decoded = unquote(raw_path)
    if "\\" in decoded or "\x00" in decoded or "//" in decoded or "//" in raw_path:
        return False
    segments = decoded.split("/") + raw_path.lower().split("/")
    if any(seg in ("..", ".", "%2e", "%2e%2e") for seg in segments):
        return False
    return "%2f" not in raw_path.lower() and "%5c" not in raw_path.lower()


def _is_gateway_role(scope: Scope) -> bool:
    fastapi_app = scope.get("app")
    if fastapi_app is None:
        return os.getenv("ROLE", "all-in-one").lower().strip() == "gateway"
    config = _resolve_config(fastapi_app)
    return (getattr(config, "role", None) or os.getenv("ROLE", "all-in-one")).lower().strip() == "gateway"


def _safe_location(value: str, core_url: Any) -> Any:
    """Returns a relative Location safe to hand to a browser, or None to drop it."""
    if value.startswith("/") and not value.startswith("//") and "\\" not in value and "\n" not in value and "\r" not in value:
        return value
    try:
        loc = urlsplit(value)
        core = urlsplit(str(core_url or ""))
    except ValueError:
        return None
    if loc.scheme and loc.netloc and core.scheme and loc.scheme == core.scheme and loc.netloc.lower() == core.netloc.lower():
        path = loc.path or "/"
        if path.startswith("/") and not path.startswith("//") and "\\" not in path:
            return path + (f"?{loc.query}" if loc.query else "") + (f"#{loc.fragment}" if loc.fragment else "")
    return None


def _not_found() -> JSONResponse:
    return JSONResponse({"detail": "Not Found"}, status_code=404)


def _resolve_config(app: Any) -> Any:
    from plex_playlist_sync.api.dependencies import get_config

    override = app.dependency_overrides.get(get_config)
    return (override or get_config)()


def _resolve_db(app: Any) -> Any:
    from plex_playlist_sync.api.dependencies import get_db

    override = app.dependency_overrides.get(get_db)
    return (override or get_db)()


class SignedBodyMiddleware:
    """Buffers and hashes the body of requests carrying ``X-TS-Signature``, then replays it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        if _is_gateway_role(scope) and any(k.startswith(b"x-ts-") for k in headers):
            # A gateway only ever originates X-TS-* headers; inbound ones are forgery attempts.
            logger.warning("Rejected inbound X-TS-* headers on gateway role")
            await JSONResponse({"detail": "Forbidden headers"}, status_code=400)(scope, receive, send)
            return
        if HEADER_SIGNATURE.lower().encode("latin-1") not in headers:
            await self.app(scope, receive, send)
            return

        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > MAX_SIGNED_BODY_BYTES
            except ValueError:
                await JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)(scope, receive, send)
                return
            if too_big:
                await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
                return

        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > MAX_SIGNED_BODY_BYTES:
                await JSONResponse({"detail": "Request body too large"}, status_code=413)(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        scope.setdefault("state", {})["ts_body_sha256"] = hashlib.sha256(body).hexdigest()

        replayed = False

        async def replay() -> dict[str, Any]:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class GatewayGuardMiddleware:
    """Deny-by-default allowlist and user-scoped forwarding for ``role == "gateway"``."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path != "/api" and not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        fastapi_app = scope.get("app")
        config = _resolve_config(fastapi_app) if fastapi_app is not None else None
        role = ((getattr(config, "role", None) or os.getenv("ROLE", "all-in-one")).lower().strip()) if config else ""
        if role != "gateway":
            await self.app(scope, receive, send)
            return

        raw_bytes = scope.get("raw_path")
        raw_path = raw_bytes.decode("latin-1") if raw_bytes else path
        raw_path = raw_path.split("?", 1)[0]
        if not _path_is_clean(raw_path):
            await _not_found()(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        match_path = path.rstrip("/") or "/"
        if _allowed(GATEWAY_LOCAL_ALLOWLIST, method, match_path):
            await self.app(scope, receive, send)
            return
        if _allowed(GATEWAY_FORWARD_ALLOWLIST, method, match_path):
            response = await self._forward(scope, receive, config, fastapi_app, method, raw_path)
            await response(scope, receive, send)
            return

        await _not_found()(scope, receive, send)

    async def _forward(
        self, scope: Scope, receive: Receive, config: Any, app: Any, method: str, raw_path: str
    ) -> Response:
        request = Request(scope, receive)

        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > MAX_PROXY_BODY_BYTES:
                    return JSONResponse({"detail": "Request body too large"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_PROXY_BODY_BYTES:
                return JSONResponse({"detail": "Request body too large"}, status_code=413)
            chunks.append(chunk)
        body = b"".join(chunks)

        try:
            user = await run_in_threadpool(self._session_user, request, app, config)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

        core_url = getattr(config, "trackseerr_core_url", None)
        secret = getattr(config, "internal_core_secret", None)
        if not core_url or not secret:
            logger.error("Gateway cannot forward %s %s: TRACKSEERR_CORE_URL / INTERNAL_CORE_SECRET not set", method, raw_path)
            return JSONResponse({"detail": "TrackSeerr Core is not configured"}, status_code=503)

        client = CoreClient(core_url=core_url, secret=secret)
        query = scope.get("query_string", b"").decode("latin-1")
        try:
            relayed = await run_in_threadpool(
                client.proxy,
                method,
                raw_path,
                query,
                body,
                {"id": user["id"], "username": user.get("username")},
                request.headers.get("content-type"),
            )
        except ValueError as exc:
            logger.error("Gateway could not sign %s %s: %s", method, raw_path, exc)
            return JSONResponse({"detail": "Request could not be forwarded"}, status_code=400)
        except httpx.HTTPError as exc:
            logger.error("Gateway proxy to core failed for %s %s: %s", method, raw_path, exc)
            return JSONResponse({"detail": "Unable to communicate with TrackSeerr Core engine"}, status_code=502)

        headers: dict[str, str] = {}
        for k, v in relayed.headers.items():
            if k.lower() != "location":
                continue
            safe = _safe_location(v, core_url)
            if safe is None:
                logger.warning("Dropped non-relative redirect Location from core for %s %s", method, raw_path)
            else:
                headers["Location"] = safe
        content_type = relayed.headers.get("Content-Type")
        return Response(
            content=relayed.body,
            status_code=relayed.status_code,
            headers=headers,
            media_type=content_type,
        )

    @staticmethod
    def _session_user(request: Request, app: Any, config: Any) -> dict[str, Any]:
        from plex_playlist_sync.api.dependencies import get_current_user

        return get_current_user(request, db=_resolve_db(app), config=config)


__all__ = [
    "GATEWAY_FORWARD_ALLOWLIST",
    "GATEWAY_LOCAL_ALLOWLIST",
    "GatewayGuardMiddleware",
    "MAX_PROXY_BODY_BYTES",
    "SignedBodyMiddleware",
]
