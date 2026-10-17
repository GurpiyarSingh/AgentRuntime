# Running the Backend with Docker

This guide builds the backend into a Docker image and runs it as a container.
Follow the steps in order. Every command is meant to be typed into
**PowerShell** from the **`agent-runtime-backend`** folder unless a step says
otherwise.

> **Want the web app too?** The quickest way to run everything (API and web
> app) is Docker Compose. See
> [Running the whole stack](#running-the-whole-stack-api--web-app) at the end.

---

## What's in the image

The [Dockerfile](Dockerfile) builds a small production image:

- **Python 3.13 (slim)** with the backend and its dependencies installed into
  a virtualenv. No compiler, pip cache or source code ships in the final image.
- **DejaVu fonts**, so PDFs the agent creates can contain any language.
- **Runs as an unprivileged user** (`agent`, uid 10001), not root.
- **Starts the HTTP API** on port **8000**, with the agent's workspace at
  **`/data/workspace`** inside the container.
- **A built-in health check** against `/health`, so Docker reports the
  container as `healthy` once the API answers.
- **Production defaults**: `ENVIRONMENT=prod` hides internal error details from
  clients, and `LOG_JSON=true` writes one JSON log line per event.

---

## 1. Check Docker is ready

Start **Docker Desktop** and wait until it says it's running. Then check:

```powershell
docker version
```

You should see both a **Client** and a **Server** section. If the Server part
shows an error, Docker Desktop isn't running yet.

---

## 2. Prepare your settings (`.env`)

The container reads its settings from the same `.env` file the backend uses
outside Docker. If you don't have one yet:

```powershell
copy .env.example .env
```

Open `.env` and set at least:

```
OPENAI_API_KEY=sk-...your key...
```

The container ignores three settings in `.env`, on purpose:

| Setting | In the container it is always | Why |
|---|---|---|
| `HOST` | `0.0.0.0` | `127.0.0.1` would make the API unreachable from outside the container |
| `PORT` | `8000` | Map a different port on your machine with `-p` instead (step 4) |
| `WORKSPACE_DIR` | `/data/workspace` | So files always land in the persistent volume |

Everything else in `.env` applies: model, limits, `API_KEY`, sessions, and so
on.

> **The `.env` file is never copied into the image** ([.dockerignore](.dockerignore)
> excludes it). It's read only when the container starts, so your key isn't
> baked into an image you might share.

---

## 3. Build the image

```powershell
docker build -t agent-runtime-backend .
```

- `-t agent-runtime-backend` names the image.
- The final `.` means "build from this folder".

The first build downloads the Python base image and the dependencies, which
takes a few minutes. Later builds reuse the cached layers and are much faster.

Check the image exists:

```powershell
docker image ls agent-runtime-backend
```

---

## 4. Run the container

```powershell
docker run -d --name agent-backend -p 127.0.0.1:8000:8000 --env-file .env -v agent-workspace:/data/workspace --restart unless-stopped agent-runtime-backend
```

What each part does:

| Part | Meaning |
|---|---|
| `-d` | Run in the background |
| `--name agent-backend` | A name for the container, used by later commands |
| `-p 127.0.0.1:8000:8000` | Make the API available at `http://localhost:8000`, **on this computer only** |
| `--env-file .env` | Load your settings, including the OpenAI key |
| `-v agent-workspace:/data/workspace` | Keep the workspace in a Docker volume named `agent-workspace`, so files survive restarts and rebuilds |
| `--restart unless-stopped` | Start again automatically after a reboot or a crash |
| `agent-runtime-backend` | The image built in step 3 |

To use a different port on your machine, e.g. 9000, change only the first
number: `-p 127.0.0.1:9000:8000`.

---

## 5. Check it's working

**Container status.** It shows `(health: starting)` at first, then `(healthy)`
after about 30 seconds:

```powershell
docker ps --filter name=agent-backend
```

**Health endpoint:**

```powershell
Invoke-RestMethod http://localhost:8000/health
```

You should see `status : ok` and the list of tools.

**Interactive API docs.** Open **http://localhost:8000/docs** in your browser.

**Logs:**

```powershell
docker logs -f agent-backend
```

Press **Ctrl+C** to stop following the logs. The container keeps running.

---

## Using the container

### Talk to the agent from the terminal (CLI)

Run the CLI inside the running container. Always pass the workspace, so the
CLI uses the same files as the API:

```powershell
docker exec -it agent-backend agent-runtime chat --workspace /data/workspace
```

For a single question:

```powershell
docker exec agent-backend agent-runtime ask --workspace /data/workspace "What files are in the workspace?"
```

### Put files in and get files out

**Option A: through the API.** This works with the volume from step 4:

```powershell
# Upload report.pdf into the workspace's uploads/ folder
curl.exe -F "file=@report.pdf" -F "path=uploads/" http://localhost:8000/v1/files

# Download a file the agent created
curl.exe -o summary.docx http://localhost:8000/v1/files/summary.docx
```

(`curl.exe` comes with Windows 10 and 11. Type `curl.exe`, not `curl`: in
Windows PowerShell, plain `curl` is an alias for a different command. If you
set `API_KEY`, add `-H "X-API-Key: your-key"`.)

**Option B: copy directly:**

```powershell
docker cp .\report.pdf agent-backend:/data/workspace/
docker cp agent-backend:/data/workspace/summary.docx .
```

**Option C: use a folder on your computer as the workspace.** Replace the `-v`
part of the step-4 command with a folder path:

```powershell
docker run -d --name agent-backend -p 127.0.0.1:8000:8000 --env-file .env -v "${PWD}\data\workspace:/data/workspace" --restart unless-stopped agent-runtime-backend
```

Files the agent creates then appear directly in `data\workspace`, and anything
you drop there is visible to the agent. (Remove the old container first: see
[Stopping and removing](#stopping-and-removing).)

> **On a Linux host** (not Docker Desktop), the container's user (uid 10001)
> must be able to write to that folder. Run once:
> `mkdir -p data/workspace && sudo chown 10001:10001 data/workspace`. Docker
> Desktop on Windows and Mac handles this for you.

---

## Configuration

Settings come from environment variables. `--env-file .env` loads them all
from your file; individual ones can be set with `-e`, which takes priority:

```powershell
docker run -d --name agent-backend -p 127.0.0.1:8000:8000 --env-file .env -e OPENAI_MODEL=gpt-5.2 -e WORKSPACE_READ_ONLY=true -v agent-workspace:/data/workspace agent-runtime-backend
```

The ones you're most likely to want:

| Variable | Default in the image | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | (none) | **Required** for chat |
| `OPENAI_MODEL` | `gpt-4o` | Default model |
| `API_KEY` | (none) | Require this key in an `X-API-Key` header on every request. **Set it before exposing the API beyond your computer.** |
| `WORKSPACE_READ_ONLY` | `false` | The agent can read files but never create or change them |
| `MAX_FILE_BYTES` | 25 MB | Largest file to read or upload |
| `ENVIRONMENT` | `prod` | `local` shows full error details (handy while debugging) |
| `LOG_JSON` | `true` | `false` for human-readable logs |
| `CORS_ALLOW_ORIGINS` | `*` | Only matters if a browser app on another origin calls the API directly |
| `DATABASE_URL` | (none) | Store sessions and every run's activity in PostgreSQL. See [Storing sessions in PostgreSQL](#storing-sessions-in-postgresql) |
| `AUTH_ENABLED` | `true` | With `DATABASE_URL`, the web app requires sign-in. Add accounts with `docker compose exec backend agent-runtime users add NAME` |
| `WORKSPACE_BROWSE_ROOTS` | `/data` | Folders the web app's folder picker may open. Mount your own folders under `/data` to make them choosable |

The full list is in [.env.example](.env.example).

### Storing sessions in PostgreSQL

Inside a container, `localhost` is the container itself, not your computer.
A `DATABASE_URL` copied from your `.env` (`...@localhost:5432/...`) makes the
container fail at startup. To use a PostgreSQL server running on your
computer, use the host name **`host.docker.internal`** instead:

```powershell
docker run -d --name agent-backend -p 127.0.0.1:8000:8000 --env-file .env -e "DATABASE_URL=postgresql://postgres:PASSWORD@host.docker.internal:5432/agent_runtime" -v agent-workspace:/data/workspace agent-runtime-backend
```

With Docker Compose, put the URL in a `.env` file at the **repository root**
(next to `docker-compose.yml`; it's git-ignored) instead:

```
DOCKER_DATABASE_URL=postgresql://postgres:PASSWORD@host.docker.internal:5432/agent_runtime
```

The database must already exist (`CREATE DATABASE agent_runtime;`); the tables
are created when the container starts.

> **`no pg_hba.conf entry for host "…"`** in `docker logs` means PostgreSQL
> refused the container's address. By default it only accepts `127.0.0.1`.
> Add a line for the address in the message to `pg_hba.conf` (e.g.
> `host  agent_runtime  postgres  192.168.65.0/24  scram-sha-256` for Docker
> Desktop), then reload PostgreSQL.

> **Note:** if your `.env` contains `ENVIRONMENT=local` or `LOG_JSON=false`
> (as `.env.example` does), those win over the image defaults. Remove them, or
> set them to `prod` / `true`, for production-style behaviour.

---

## Everyday commands

| Task | Command |
|---|---|
| See if it's running | `docker ps --filter name=agent-backend` |
| Follow the logs | `docker logs -f agent-backend` |
| Stop | `docker stop agent-backend` |
| Start again | `docker start agent-backend` |
| Restart (e.g. after editing `.env`) | `docker rm -f agent-backend`, then the step-4 `docker run` command |
| Open a shell inside | `docker exec -it agent-backend sh` |

> `docker restart` does **not** re-read `.env`: environment variables are fixed
> when the container is created. After changing `.env`, remove the container
> and run it again. The workspace volume is kept.

### Updating after code changes

```powershell
docker build -t agent-runtime-backend .
docker rm -f agent-backend
docker run -d --name agent-backend -p 127.0.0.1:8000:8000 --env-file .env -v agent-workspace:/data/workspace --restart unless-stopped agent-runtime-backend
```

### Stopping and removing

```powershell
docker rm -f agent-backend            # remove the container (files in the volume are kept)
docker volume rm agent-workspace      # ALSO delete all workspace files - cannot be undone
docker image rm agent-runtime-backend # remove the image
```

---

## Running the whole stack (API + web app)

The repository root has a [docker-compose.yml](../docker-compose.yml) that
builds and runs this image together with the web app. From the **repository
root** (the folder containing both `agent-runtime-backend` and
`agent-runtime-frontend`):

```powershell
docker compose up --build -d
```

Then open **http://localhost:8080**. Compose reads
`agent-runtime-backend/.env`, keeps the workspace in a volume, and starts the
web app once the API is healthy. Details are in the
[frontend Docker guide](../agent-runtime-frontend/DOCKER.md#option-a-run-everything-with-docker-compose-recommended).

---

## Security checklist

- **Never bake secrets into the image.** Pass them at run time with
  `--env-file` or `-e`. The `.dockerignore` keeps `.env` out of builds.
- **Keep `127.0.0.1` in `-p`** unless other computers must reach the API. If
  they must, set `API_KEY` first, and put HTTPS in front of it (e.g. a reverse
  proxy).
- **The container runs as a non-root user**, and the agent can only touch
  `/data/workspace`.
- **Files the agent reads are sent to OpenAI** for processing.
- **The folder picker stays inside `/data`** (`WORKSPACE_BROWSE_ROOTS`).
  Don't widen it to `/`: the agent could then read `/proc/self/environ`,
  which holds your OpenAI key and database password.
- **Run one container.** Without `DATABASE_URL`, conversations are kept in
  memory, so don't scale this service to several replicas behind a load
  balancer.

---

## Troubleshooting

| Problem | What to do |
|---|---|
| `docker: command not found` / not recognised | Install or start Docker Desktop, then open a **new** PowerShell window. |
| `error during connect` / Server section shows an error | Docker Desktop isn't running. Start it and wait until it's ready. |
| `Bind for 127.0.0.1:8000 failed: port is already allocated` | Something else uses port 8000, perhaps `agent-runtime serve` running outside Docker. Stop it, or use `-p 127.0.0.1:9000:8000`. |
| `Conflict. The container name "/agent-backend" is already in use` | A container with that name exists. Run `docker rm -f agent-backend`, then run again. |
| Status stays `(health: starting)` for more than a minute, or turns `(unhealthy)` | Check `docker logs agent-backend`. A typo in `.env` (e.g. an invalid `LOG_LEVEL`) stops startup, and the log says which setting. |
| Chat fails with **OPENAI_API_KEY is not set** | The key isn't in `.env`, or the container was created before you added it. Run `docker rm -f agent-backend`, then run again. |
| `401 Invalid or missing API key` | `API_KEY` is set in `.env`: send it as the `X-API-Key` header, or enter it in the web app's Settings. |
| `open .env: The system cannot find the file specified` | Run the command from the `agent-runtime-backend` folder, or create `.env` (step 2). |
| Files written with Option C don't appear | Check the path in `-v`. On Windows, make sure Docker Desktop is allowed to share that drive (Settings → Resources → File sharing). |
