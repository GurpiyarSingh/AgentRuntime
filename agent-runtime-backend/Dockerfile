# syntax=docker/dockerfile:1
#
# Agent Runtime backend: the HTTP API (and CLI) in a small, non-root image.
#
#   docker build -t agent-runtime-backend .
#   docker run --rm -p 8000:8000 --env-file .env \
#       -v agent-workspace:/data/workspace agent-runtime-backend
#
# Two stages: `build` compiles the package and its dependencies into a
# virtualenv; `runtime` copies only that virtualenv onto a clean slim image,
# so no compiler, pip cache or source tree ships.

ARG PYTHON_VERSION=3.13

# --- build ----------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /src
# Metadata first: dependency layers stay cached until pyproject.toml changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# --- runtime --------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="agent-runtime-backend" \
      org.opencontainers.image.description="Agent Runtime HTTP API: an AI agent with file tools."

# DejaVu fonts let generated PDFs carry any Unicode text; without a TrueType
# font the PDF writer falls back to Latin-1 only.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# An unprivileged user owns only the workspace, nothing else.
RUN groupadd --system --gid 10001 agent \
    && useradd --system --uid 10001 --gid agent --home-dir /app --shell /usr/sbin/nologin agent \
    && mkdir -p /data/workspace \
    && chown agent:agent /data/workspace

COPY --from=build /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=prod \
    LOG_JSON=true

WORKDIR /app
USER agent

# Agent workspace: uploads and every file the agent creates. Mount a volume
# here, or they are lost with the container.
VOLUME ["/data/workspace"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# Host, port and workspace are passed as flags on purpose: flags win over
# environment variables and .env, so an --env-file copied from a laptop
# (HOST=127.0.0.1, WORKSPACE_DIR=data/workspace) can't make the API
# unreachable or write files outside the volume. Everything else (model,
# limits, API_KEY, ...) comes from the environment.
# One worker only: conversation sessions are held in memory.
ENTRYPOINT ["agent-runtime"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000", "--workspace", "/data/workspace"]
