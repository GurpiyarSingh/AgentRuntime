# syntax=docker/dockerfile:1
#
# Agent Runtime backend: the HTTP API (and CLI) in a small, non-root image.
#
#   docker build -t agent-runtime-backend .
#   docker run --rm -p 8000:8000 --env-file .env \
#       -v agent-workspace:/data/workspace -v agent-config:/config agent-runtime-backend
#
# Two stages: `build` compiles the package and its dependencies into a
# virtualenv; `runtime` copies only that virtualenv onto a clean slim image,
# so no compiler, pip cache or source tree ships.

ARG PYTHON_VERSION=3.13
# Node.js, so MCP servers started with `npx` (Playwright, GitHub, filesystem,
# memory, ...) run inside the container.
ARG NODE_VERSION=22

# --- node: only its runtime is copied out ------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS node

# --- build ----------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS build

# A slow or flaky connection makes pip's default 15 s timeout give up on an
# index page, which it reports misleadingly as "from versions: none".
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /src
# Dependencies first, from pyproject.toml alone, so this slow layer stays
# cached until the dependency list changes, not on every source edit.
COPY pyproject.toml README.md ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > requirements.txt \
    && pip install -r requirements.txt
# uv provides `uvx`, which starts Python MCP servers (mcp-atlassian for Jira,
# mcp-server-fetch, ...) without installing them first.
RUN pip install "uv>=0.8,<1"
COPY src ./src
RUN pip install --no-deps .

# --- runtime --------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="agent-runtime-backend" \
      org.opencontainers.image.description="Agent Runtime HTTP API: an AI agent with file tools."

# DejaVu fonts let generated PDFs carry any Unicode text; without a TrueType
# font the PDF writer falls back to Latin-1 only.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Node.js and npm/npx, for MCP servers published on npm.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version && npx --version

# An unprivileged user owns only what it must write: the workspace, the MCP
# servers file, and a home for npm's and uv's download caches.
RUN groupadd --system --gid 10001 agent \
    && useradd --system --uid 10001 --gid agent --home-dir /home/agent --create-home \
        --shell /usr/sbin/nologin agent \
    && mkdir -p /data/workspace /config \
    && chown agent:agent /data/workspace /config

COPY --from=build /opt/venv /opt/venv

# WORKSPACE_BROWSE_ROOTS keeps the web app's folder picker inside /data.
# Without it a client could point the agent at any folder in the container,
# e.g. /proc/self, whose `environ` holds OPENAI_API_KEY and DATABASE_URL.
# Mount extra folders under /data (e.g. /data/projects) to make them choosable.
#
# The MCP servers file lives in /config, outside /data, so the folder picker
# (and so the agent) can never read the tokens stored in it.
ENV PATH="/opt/venv/bin:$PATH" \
    HOME=/home/agent \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=prod \
    LOG_JSON=true \
    WORKSPACE_BROWSE_ROOTS=/data

WORKDIR /app
USER agent

# Agent workspace: uploads and every file the agent creates. MCP servers the
# web app adds. Mount volumes on both, or they are lost with the container.
VOLUME ["/data/workspace", "/config"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# Host, port, workspace and MCP file are passed as flags on purpose: flags
# win over environment variables and .env, so an --env-file copied from a
# laptop (HOST=127.0.0.1, WORKSPACE_DIR=data/workspace) can't make the API
# unreachable or write files outside the volumes. Everything else (model,
# limits, API_KEY, ...) comes from the environment.
# One worker: without DATABASE_URL, conversations are held in memory, and MCP
# connections belong to the process.
ENTRYPOINT ["agent-runtime"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000", "--workspace", "/data/workspace", "--mcp-config", "/config/mcp.json"]
