"""FastAPI dependency wiring.

Everything long-lived (settings, the agent registry, the session store) is
built once in `create_app` and stashed on `app.state`; these dependencies
just fetch it back out per-request. The `Orchestrator` is cheap and
stateless across requests, so it is built fresh per call — which is what
lets each request pick its own model.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from agent_runtime.agents.registry import AgentRegistry
from agent_runtime.config import Settings
from agent_runtime.orchestrator.orchestrator import Orchestrator
from agent_runtime.sessions import SessionStore


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_agents(request: Request) -> AgentRegistry:
    return request.app.state.agents  # type: ignore[no-any-return]


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.sessions  # type: ignore[no-any-return]


class OrchestratorFactory:
    """Builds an `Orchestrator` for one request, honouring its model choice.

    The model can only be chosen once the request body has been parsed,
    which is after dependencies resolve — so the dependency hands back a
    factory rather than a finished orchestrator. Tests replace this with a
    factory that closes over a scripted fake model.
    """

    def __init__(self, settings: Settings, agents: AgentRegistry) -> None:
        self._settings = settings
        self._agents = agents

    def __call__(self, model_id: str | None = None) -> Orchestrator:
        return Orchestrator(settings=self._settings, agents=self._agents, model_id=model_id)


def get_orchestrator(
    settings: Settings = Depends(get_settings),
    agents: AgentRegistry = Depends(get_agents),
) -> OrchestratorFactory:
    return OrchestratorFactory(settings=settings, agents=agents)


async def require_api_key(
    settings: Settings = Depends(get_settings),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    """No-op when `API_KEY` is unset (open, for local dev); enforced otherwise."""
    if settings.api_key is None:
        return
    if x_api_key != settings.api_key.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key"
        )
