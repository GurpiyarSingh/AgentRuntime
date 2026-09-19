"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from agent_runtime.api.routes import router
from agent_runtime.api.schemas import ErrorResponse
from agent_runtime.config import Settings, get_settings
from agent_runtime.logging import configure_logging
from agent_runtime.sessions import SessionStore
from agent_runtime.web import STATIC_DIR
from agent_runtime.wiring import build_agents

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
                "agents": ",".join(app.state.agents.names()),
                "email_dry_run": not settings.can_send_email,
            },
        )
        if not settings.can_send_email:
            logger.warning(
                "email delivery is OFF (dry run): the email agent will compose and "
                "validate messages but nothing will be sent"
            )
        yield
        logger.info("shutting down %s", settings.app_name)

    app = FastAPI(
        title="Agent Runtime",
        description=(
            "A multi-agent runtime with a transparent agent loop. "
            "An orchestrator routes each request to a specialist agent; "
            "the first is an email agent."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.settings = settings
    app.state.agents = build_agents(settings)
    app.state.sessions = SessionStore(
        ttl_s=settings.session_ttl_s, max_messages=settings.session_max_messages
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        detail = str(exc) if not settings.is_prod else None
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(error="internal_error", detail=detail).model_dump(),
        )

    app.include_router(router)

    # The chat UI is served same-origin so the browser can call the streaming
    # endpoint directly. Registered after the API router, so /health and /v1/*
    # always win over the static mount.
    @app.get("/", include_in_schema=False)
    async def index() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

    app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")

    return app
