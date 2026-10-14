# syntax=docker/dockerfile:1
#
# Agent Runtime web app: built with Node, served by unprivileged nginx, which
# also proxies /v1 and /health to the backend.
#
#   docker build -t agent-runtime-frontend .
#   docker run --rm -p 8080:8080 -e BACKEND_URL=http://host.docker.internal:8000 \
#       agent-runtime-frontend
#
# Runtime settings (see docker/nginx.conf.template): BACKEND_URL,
# CLIENT_MAX_BODY_SIZE, CSP_CONNECT_SRC.

ARG NODE_VERSION=22
ARG NGINX_VERSION=1.28

# --- build ----------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS build

WORKDIR /app
# Lockfile first: the dependency layer stays cached until it changes.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .

# Compiled into the bundle (visible to anyone who loads the page; never a
# secret). Leave empty to call the API on the same origin, through this
# image's proxy; set it only for a backend on another origin.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

# Type-check and build; source maps aren't shipped.
RUN npm run build && find dist -name '*.map' -delete

# --- runtime --------------------------------------------------------------------
FROM nginxinc/nginx-unprivileged:${NGINX_VERSION}-alpine AS runtime

LABEL org.opencontainers.image.title="agent-runtime-frontend" \
      org.opencontainers.image.description="Agent Runtime web app (static files + API proxy)."

ENV BACKEND_URL=http://backend:8000 \
    CLIENT_MAX_BODY_SIZE=30m \
    CSP_CONNECT_SRC="'self'"

COPY docker/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

# The base image runs as the unprivileged "nginx" user and listens on 8080.
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
