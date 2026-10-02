"""FastAPI Application factory with security middleware and router registration."""

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles

from plex_playlist_sync.api.routes import (
    acquisition,
    auth,
    discovery,
    download_clients,
    indexers,
    missing,
    notifications,
    playlists,
    quality_profiles,
    queue,
    requests,
    settings,
    sync,
    system,
    users,
)
from plex_playlist_sync.config import Config
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)


def create_app(
    db: Optional[Database] = None,
    config: Optional[Config] = None,
) -> FastAPI:
    """Creates and configures a FastAPI application instance."""
    app = FastAPI(
        title="TrackSeerr API",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # Attach instances to app state if provided
    if db is not None:
        app.state.db = db
    if config is not None:
        app.state.config = config

    # 1. Security Headers Middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-eval' 'unsafe-inline' "
            "https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "media-src 'self' https: data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response

    cors_origins_env = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5250,http://127.0.0.1:5250").strip()
    if cors_origins_env:
        if cors_origins_env == "*":
            # Wildcard origin cannot be used with credentials
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=False,
                allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                allow_headers=["*"],
            )
        else:
            origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]
            app.add_middleware(
                CORSMiddleware,
                allow_origins=origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

    # 3. Mount Routers under /api
    api_router = APIRouter(prefix="/api")
    api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
    api_router.include_router(users.router, prefix="/users", tags=["users"])
    api_router.include_router(playlists.router, prefix="/playlists", tags=["playlists"])
    api_router.include_router(sync.router, prefix="/sync", tags=["sync"])
    api_router.include_router(missing.router, prefix="/missing", tags=["missing"])
    api_router.include_router(discovery.router, prefix="/discovery", tags=["discovery"])
    api_router.include_router(requests.router, prefix="/requests", tags=["requests"])
    api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
    api_router.include_router(
        download_clients.router, prefix="/settings/download-clients", tags=["download_clients"]
    )
    api_router.include_router(indexers.router, prefix="/settings/indexers", tags=["indexers"])
    api_router.include_router(
        quality_profiles.router, prefix="/settings/quality-profiles", tags=["quality_profiles"]
    )
    api_router.include_router(
        notifications.router, prefix="/settings/notifications", tags=["notifications"]
    )
    api_router.include_router(queue.router, prefix="/queue", tags=["queue"])
    api_router.include_router(acquisition.router, prefix="/acquisition", tags=["acquisition"])
    api_router.include_router(system.router, prefix="/system", tags=["system"])

    @api_router.api_route("/health", methods=["GET", "HEAD"], tags=["health"])
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)

    # 4. Mount Static Directory & Serve Root
    static_dir = Path(__file__).resolve().parent.parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.api_route("/", methods=["GET", "HEAD"], response_class=FileResponse, include_in_schema=False)
    def serve_index() -> FileResponse:
        index_file = static_dir / "index.html"
        return FileResponse(str(index_file), media_type="text/html")

    return app


app = create_app()
