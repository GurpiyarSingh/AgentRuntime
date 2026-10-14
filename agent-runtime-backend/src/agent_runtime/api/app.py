"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agent_runtime import __version__
from agent_runtime.api.files import router as files_router
from agent_runtime.api.routes import router
from agent_runtime.api.schemas import ErrorResponse
from agent_runtime.config import Settings, get_settings
from agent_runtime.logging import configure_logging
from agent_runtime.runtime import build_tools, build_workspace
from agent_runtime.sessions import SessionStore

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. Settings are read once, at startup."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "starting %s",
            settings.app_name,
            extra={
                "environment": settings.environment,
                "model": settings.openai_model,
                "workspace": str(app.state.workspace.root),
                "read_only": settings.workspace_read_only,
                "tools": ",".join(app.state.tools.names()),
            },
        )
        yield
        logger.info("shutting down %s", settings.app_name)

    app = FastAPI(
        title="Agent Runtime",
        description=(
            "A backend agent runtime with a transparent think/act/observe loop and "
            "built-in tools for reading, viewing and creating files of any type."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.workspace = build_workspace(settings)
    app.state.tools = build_tools(settings, app.state.workspace)
    app.state.sessions = SessionStore(
        ttl_s=settings.session_ttl_s, max_messages=settings.session_max_messages
    )

    # Auth is a header (X-API-Key), never a cookie, so browsers never need
    # to send credentials. Allowing them alongside a wildcard origin would
    # make Starlette echo back any origin as trusted.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
        detail = str(exc) if not settings.is_prod else None
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(error="internal_error", detail=detail).model_dump(),
        )

    app.include_router(router)
    app.include_router(files_router)
    return app
