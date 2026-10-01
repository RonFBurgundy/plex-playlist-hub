"""FastAPI Application factory with security middleware and router registration."""

import logging
import os
from typing import Optional

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from plex_playlist_sync.api.routes import auth, missing, playlists, sync, users
from plex_playlist_sync.config import Config
from plex_playlist_sync.storage import Database

logger = logging.getLogger(__name__)


def create_app(
    db: Optional[Database] = None,
    config: Optional[Config] = None,
) -> FastAPI:
    """Creates and configures a FastAPI application instance."""
    app = FastAPI(
        title="Plex Playlist Hub API",
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
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response

    # 2. CORS Middleware
    cors_origins_env = os.getenv("CORS_ORIGINS", "*").strip()
    if cors_origins_env == "*":
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r"^https?://.*$",
            allow_credentials=True,
            allow_methods=["*"],
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

    @api_router.get("/health", tags=["health"])
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router)

    return app


app = create_app()
