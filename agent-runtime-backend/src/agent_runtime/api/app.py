"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from agent_runtime import __version__
from agent_runtime.api.auth import router as auth_router
from agent_runtime.api.directories import router as directories_router
from agent_runtime.api.files import router as files_router
from agent_runtime.api.mcp import router as mcp_router
from agent_runtime.api.routes import router
from agent_runtime.api.schemas import ErrorResponse
from agent_runtime.api.sessions import router as sessions_router
from agent_runtime.auth import LoginThrottle
from agent_runtime.config import Settings, get_settings
from agent_runtime.logging import configure_logging
from agent_runtime.runtime import (
    build_directory_policy,
    build_mcp_manager,
    build_tools,
    build_workspace,
)
from agent_runtime.sessions import ConversationStore, SessionStore
from agent_runtime.storage import DatabaseStore, create_database_store

logger = logging.getLogger(__name__)


def build_session_store(settings: Settings) -> ConversationStore:
    """The database store when `DATABASE_URL` is set, otherwise in-memory sessions."""
    if settings.database_url is not None:
        return create_database_store(
            settings.database_url.get_secret_value(),
            max_messages=settings.session_max_messages,
            token_ttl=settings.auth_token_ttl,
            echo=settings.database_echo,
        )
    return SessionStore(ttl_s=settings.session_ttl_s, max_messages=settings.session_max_messages)


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
        if app.state.mcp is not None:
            await app.state.mcp.start()  # Connects in the background.
        if isinstance(app.state.sessions, DatabaseStore):
            # Fail at startup, not on the first chat, if the database is unreachable.
            await app.state.sessions.create_schema()
            await app.state.sessions.users.purge_expired_tokens()
            logger.info("sessions are stored in the database")
        yield
        if app.state.mcp is not None:
            await app.state.mcp.close()
        if isinstance(app.state.sessions, DatabaseStore):
            await app.state.sessions.close()
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
    app.state.directories = build_directory_policy(settings, app.state.workspace)
    app.state.tools = build_tools(settings, app.state.workspace)
    app.state.sessions = build_session_store(settings)
    app.state.login_throttle = LoginThrottle()
    app.state.mcp = build_mcp_manager(settings)

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
    app.include_router(directories_router)
    app.include_router(sessions_router)
    app.include_router(auth_router)
    app.include_router(mcp_router)
    return app
