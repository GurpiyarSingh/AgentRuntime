# Running the Web App with Docker

This guide builds the web app into a Docker image and runs it. Commands are
for **PowerShell**. Each section says which folder to run them from.

The web app needs the **backend API** to talk to. Pick one way of running them:

| Option                                                                                          | When to use it                                                  |
| ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| **[A. Docker Compose](#option-a-run-everything-with-docker-compose-recommended)** (recommended) | Run the API and the web app together with one command           |
| **[B. Two containers](#option-b-web-app-and-backend-as-separate-containers)**                   | You want to manage each container yourself                      |
| **[C. Backend outside Docker](#option-c-backend-running-outside-docker)**                       | The API already runs on your machine with `agent-runtime serve` |
| **[D. Backend on another server](#option-d-backend-on-another-server-or-domain)**               | The API is hosted somewhere else, on its own domain             |

---

## What's in the image

The [Dockerfile](Dockerfile) builds in two stages:

1. **Build** (Node 22): installs the exact dependency versions from
   `package-lock.json`, type-checks, and produces the static site.
2. **Run** (nginx, unprivileged): serves the site on port **8080**, running as
   a non-root user. It also **forwards `/v1` and `/health` to the backend**, so
   the browser talks to one address and no CORS setup is needed.

The nginx configuration ([docker/nginx.conf.template](docker/nginx.conf.template))
also:

- **Streams chat replies live** (proxy buffering is off for the API).
- **Caches the app's files efficiently**, while always picking up a new
  deployment.
- **Sends security headers**, including a Content-Security-Policy.
- **Provides a `/healthz` endpoint** for the container health check.

Runtime settings, passed with `-e`:

| Variable               | Default               | Purpose                                                                                               |
| ---------------------- | --------------------- | ----------------------------------------------------------------------------------------------------- |
| `BACKEND_URL`          | `http://backend:8000` | Where the API is: `scheme://host:port`, **no path, no trailing slash**                                |
| `CLIENT_MAX_BODY_SIZE` | `30m`                 | Largest file upload. Keep it above the backend's `MAX_FILE_BYTES` (25 MB by default).                 |
| `CSP_CONNECT_SRC`      | `'self'`              | Origins the page may call. Only needed for [option D](#option-d-backend-on-another-server-or-domain). |

---

## Before you start

1. Start **Docker Desktop**, and check it's running:

   ```powershell
   docker version
   ```

   You should see both a **Client** and a **Server** section.

2. Make sure the backend has a settings file with your OpenAI key, at
   `agent-runtime-backend\.env`. If it doesn't exist:

   ```powershell
   cd "D:\D Drive\Codes\AgentRuntime\agent-runtime-backend"
   copy .env.example .env
   ```

   Then open `.env` and set `OPENAI_API_KEY`.

---

## Option A: Run everything with Docker Compose (recommended)

The [docker-compose.yml](../docker-compose.yml) at the repository root builds
both images and runs them together.

**Start it** from the **repository root**, the folder that contains
`agent-runtime-backend` and `agent-runtime-frontend`:

```powershell
cd "D:\D Drive\Codes\AgentRuntime"
docker compose up --build -d
```

The first run builds both images, which takes a few minutes. Then open
**http://localhost:8080**.

If the backend has a database (see
[Storing sessions in PostgreSQL](../agent-runtime-backend/DOCKER.md#storing-sessions-in-postgresql)),
the page opens on a sign-in screen, and the first visitor creates the admin
account. Add more accounts with
`docker compose exec backend agent-runtime users add NAME`. Without a
database, the app opens directly in "Local mode".

What Compose sets up:

- **The backend**, with settings from `agent-runtime-backend\.env` and the
  workspace in a Docker volume, so files survive restarts and rebuilds. It is
  not published on its own port; the web app reaches it internally.
- **The web app**, on **http://localhost:8080**, this computer only. It starts
  once the backend reports healthy.

**Everyday commands** (run from the repository root):

| Task                                             | Command                                                                      |
| ------------------------------------------------ | ---------------------------------------------------------------------------- |
| See status                                       | `docker compose ps`                                                          |
| Follow all logs                                  | `docker compose logs -f`                                                     |
| Logs of one service                              | `docker compose logs -f backend`                                             |
| Stop (keeps everything)                          | `docker compose stop`                                                        |
| Start again                                      | `docker compose start`                                                       |
| Apply `.env` changes                             | `docker compose up -d --force-recreate backend`                              |
| Rebuild after code changes                       | `docker compose up --build -d`                                               |
| Use the CLI                                      | `docker compose exec backend agent-runtime chat --workspace /data/workspace` |
| Stop and remove containers (workspace kept)      | `docker compose down`                                                        |
| **Remove everything, including workspace files** | `docker compose down -v` (cannot be undone)                                  |

**Calling the API directly** (for scripts, the CLI from your machine, or the
`/docs` page): in `docker-compose.yml`, uncomment the backend's `ports:` lines
and run `docker compose up -d`. The API is then at **http://localhost:8000**.

**Letting other computers use it:** in `docker-compose.yml`, change
`"127.0.0.1:8080:8080"` to `"8080:8080"`. **Set `API_KEY` in the backend's
`.env` first.** Without it, anyone who can reach the page can read, upload and
delete workspace files. For access over the internet, put HTTPS in front of it.

---

## Option B: Web app and backend as separate containers

**1. Build both images.** From the backend folder:

```powershell
cd "D:\D Drive\Codes\AgentRuntime\agent-runtime-backend"
docker build -t agent-runtime-backend .
```

Then from the frontend folder:

```powershell
cd "D:\D Drive\Codes\AgentRuntime\agent-runtime-frontend"
docker build -t agent-runtime-frontend .
```

**2. Create a network** so the two containers can find each other by name:

```powershell
docker network create agent-net
```

**3. Start the backend** on that network, named `backend`. Run this from the
backend folder, so `.env` is found:

```powershell
cd "D:\D Drive\Codes\AgentRuntime\agent-runtime-backend"
docker run -d --name backend --network agent-net --env-file .env -v agent-workspace:/data/workspace --restart unless-stopped agent-runtime-backend
```

Wait until `docker ps` shows it as `(healthy)`, which takes about 30 seconds.

**4. Start the web app:**

```powershell
docker run -d --name agent-frontend --network agent-net -p 127.0.0.1:8080:8080 -e BACKEND_URL=http://backend:8000 --restart unless-stopped agent-runtime-frontend
```

Open **http://localhost:8080**.

To remove it all later:

```powershell
docker rm -f agent-frontend backend
docker network rm agent-net
```

The backend's own options (CLI, file access, configuration) are covered in the
[backend Docker guide](../agent-runtime-backend/DOCKER.md).

---

## Option C: Backend running outside Docker

If the API already runs on your machine (`agent-runtime serve`, port 8000),
point the web app container at your computer through Docker's special host
name, `host.docker.internal`.

From the frontend folder:

```powershell
cd "D:\D Drive\Codes\AgentRuntime\agent-runtime-frontend"
docker build -t agent-runtime-frontend .
docker run -d --name agent-frontend -p 127.0.0.1:8080:8080 -e BACKEND_URL=http://host.docker.internal:8000 agent-runtime-frontend
```

Open **http://localhost:8080**.

> If the page reports that it can't reach the server (or **502 Bad Gateway**),
> your Docker setup can't reach services that listen only on `127.0.0.1`.
> Restart the backend with `agent-runtime serve --host 0.0.0.0`. That also
> makes it reachable from your network, so set `API_KEY` if you're not on a
> trusted network.

---

## Option D: Backend on another server or domain

Use this when the API is hosted separately, e.g. at
`https://api.example.com`, and the browser should call it directly.

**1. Build with the API address compiled in.** It's a build argument, because
it becomes part of the app's JavaScript:

```powershell
docker build -t agent-runtime-frontend --build-arg VITE_API_BASE_URL=https://api.example.com .
```

**2. Run, allowing the page to call that origin.** Point `BACKEND_URL` at the
same server, so `/health` and any same-origin API calls still reach it.

```powershell
docker run -d --name agent-frontend -p 8080:8080 -e BACKEND_URL=https://api.example.com -e "CSP_CONNECT_SRC='self' https://api.example.com" agent-runtime-frontend
```

**3. Allow the web app's address on the backend.** In the backend's `.env`, set
`CORS_ALLOW_ORIGINS` to the address users open the web app at, e.g.
`CORS_ALLOW_ORIGINS=https://app.example.com`, and recreate the backend
container.

> `VITE_API_BASE_URL` is visible to anyone who loads the page. Never put a
> secret in it. Users enter the API key in the app's **Settings**.

---

## Checking it's working

| Check                           | How                                                                                          |
| ------------------------------- | -------------------------------------------------------------------------------------------- |
| Container is healthy            | `docker ps`: the web app shows `(healthy)` after about 30 seconds                            |
| nginx is serving                | `Invoke-RestMethod http://localhost:8080/healthz` returns `ok`                               |
| The API is reachable through it | `Invoke-RestMethod http://localhost:8080/health` returns `status : ok`                       |
| The app works                   | Open http://localhost:8080. The tools panel shows a green **Connected** and lists the tools. |

Logs: `docker logs -f agent-frontend` (or `docker compose logs -f frontend`).

### Updating after code changes

Option A: `docker compose up --build -d` from the repository root.

Options B, C and D: rebuild, remove, and run again:

```powershell
docker build -t agent-runtime-frontend .
docker rm -f agent-frontend
```

Then repeat the `docker run` command for your option.

---

## Troubleshooting

| Problem                                                                                       | What to do                                                                                                                                                                                                                 |
| --------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docker: command not found` / not recognised                                                  | Install or start Docker Desktop, then open a **new** PowerShell window.                                                                                                                                                    |
| The page loads, but API calls fail with **502 Bad Gateway**; logs say `could not be resolved` | nginx can't find the host in `BACKEND_URL`. With option B, make sure the backend container is named `backend` and both are on `agent-net`. With option A, use `docker compose up` rather than starting the frontend alone. |
| Page shows **Cannot reach the agent server** or **502 Bad Gateway**                           | The backend isn't running or isn't reachable at `BACKEND_URL`. Check `docker ps` and the backend's logs. For option C, see the note there.                                                                                 |
| Page shows **OPENAI_API_KEY is not set**                                                      | Add the key to `agent-runtime-backend\.env`, then recreate the backend: `docker compose up -d --force-recreate backend` (option A) or remove and run it again (option B).                                                  |
| Page shows **The server needs an API key**                                                    | `API_KEY` is set on the backend. Enter it in the app under **Settings**.                                                                                                                                                   |
| Replies appear all at once instead of word by word                                            | Something between the browser and this container is buffering. If you added your own reverse proxy in front, turn its buffering off for `/v1/chat/stream` (nginx: `proxy_buffering off`).                                  |
| Uploads fail with **413**                                                                     | The file is larger than `CLIENT_MAX_BODY_SIZE` (30 MB) or the backend's `MAX_FILE_BYTES` (25 MB). Raise both if needed.                                                                                                    |
| `Bind for 127.0.0.1:8080 failed: port is already allocated`                                   | Something else uses port 8080. Use another, e.g. `-p 127.0.0.1:8081:8080`, or change the Compose `ports:` line.                                                                                                            |
| `npm ci` fails during the build                                                               | Make sure `package-lock.json` is present and up to date: run `npm install` once outside Docker, then build again.                                                                                                          |
| Changes to the code don't show up                                                             | Rebuild the image. The container runs the code baked in at build time.                                                                                                                                                     |
