# Agent Runtime

An AI agent that **works with your files**. Ask it in plain English to read a
PDF, look at a screenshot, summarise a spreadsheet, or produce a Word report or
a slide deck, and it does the work inside a sandboxed folder, showing every
step it takes.

![The Agent Runtime web app](agent-runtime-frontend/docs/screenshot.png)

The repository has two parts:

| Folder | What it is | Built with |
|---|---|---|
| [`agent-runtime-backend/`](agent-runtime-backend) | The agent itself: the reasoning loop, the file tools, a command-line interface and an HTTP API | Python 3.11+, FastAPI, LangChain, OpenAI |
| [`agent-runtime-frontend/`](agent-runtime-frontend) | A web app for chatting with the agent, with its tools listed in a sidebar | React 19, TypeScript, Vite |

The backend works on its own (from the terminal, or as an API for your own
apps). The frontend is an optional web interface on top of it.

---

## What it can do

The agent decides which tool to use for each step of a request:

| Tool | What it does |
|---|---|
| `list_files` | Lists the files in the workspace |
| `read_file` | Reads text and code in any encoding, plus **PDF**, **Word**, **Excel**, **PowerPoint**, and zip/tar archives |
| `read_image` | Looks at images: PNG, JPEG, GIF, WEBP, BMP, TIFF, PSD, AVIF and more |
| `write_file` | Creates **Word**, **PDF**, **Excel** and **PowerPoint** files, text, code, CSV, JSON, HTML, or any binary format |
| `edit_file` | Changes part of an existing text file |
| `search_files` | Searches the workspace's text files |

Every tool is confined to one **workspace** folder (`data/workspace` by
default). Paths that try to leave it are refused, whether they use `..`,
absolute paths or symlinks.

---

## How the pieces fit

```
  ┌───────────────────┐     ┌──────────────────────┐
  │  Web app (React)  │     │  CLI                 │
  │  localhost:5173   │     │  agent-runtime chat  │
  └─────────┬─────────┘     │  agent-runtime ask   │
            │ HTTP + SSE    └──────────┬───────────┘
            ▼                          │ in-process
  ┌───────────────────┐                │
  │  HTTP API         │                │
  │  (FastAPI) :8000  │                │
  └─────────┬─────────┘                │
            └───────────┬──────────────┘
                        ▼
            ┌───────────────────────┐   model calls   ┌────────────┐
            │  Agent loop           │ ──────────────▶ │  OpenAI    │
            │  think → act → observe│ ◀────────────── │  GPT-4o /  │
            └───────────┬───────────┘                 │  GPT-5.2   │
                        │ tool calls                  └────────────┘
                        ▼
            ┌───────────────────────┐
            │  File tools           │ ───▶  workspace folder
            └───────────────────────┘       (the only place it can touch)
```

The CLI and the API share the same agent loop and tools, so they behave the
same. The web app talks to the API, and streams each step of the agent's work
live over Server-Sent Events.

---

## Quick start

### Prerequisites

- **Python 3.11+** for the backend
- **Node.js 20.19+** for the web app (optional)
- An **OpenAI API key** ([get one here](https://platform.openai.com/api-keys))

### 1. Set up the backend

```powershell
cd agent-runtime-backend
python -m venv venv
.\venv\Scripts\Activate.ps1          # Mac/Linux: source venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env               # Mac/Linux: cp .env.example .env
```

Open `.env` and set `OPENAI_API_KEY`. Always run backend commands from inside
`agent-runtime-backend/`, because that's where `.env` is read from.

### 2. Use it from the terminal

```powershell
agent-runtime chat                   # conversation
agent-runtime ask "List my files"    # one question
```

### 3. Or use the web app

Run these in two terminals:

```powershell
# Terminal 1 (in agent-runtime-backend/, venv active)
agent-runtime serve                  # API on http://127.0.0.1:8000

# Terminal 2
cd agent-runtime-frontend
npm install                          # first time only
npm run dev                          # web app on http://localhost:5173
```

Open **http://localhost:5173**. In development, the web app forwards its API
calls to the backend, so no CORS setup is needed.

---

## Running with Docker

Each part has its own `Dockerfile`, and [`docker-compose.yml`](docker-compose.yml)
at the root runs both together. With Docker Desktop running and
`agent-runtime-backend/.env` containing your OpenAI key, run from this folder:

```powershell
docker compose up --build -d      # build and start the API and the web app
```

Then open **http://localhost:8080**. Stop with `docker compose down`; the
workspace files are kept in a Docker volume.

Step-by-step instructions for building and running each image, configuration,
and troubleshooting:

- [Backend Docker guide](agent-runtime-backend/DOCKER.md): the API image, the
  CLI in a container, getting files in and out
- [Frontend Docker guide](agent-runtime-frontend/DOCKER.md): Compose, separate
  containers, or a backend elsewhere

---

## Three ways to use it

| Mode | Start it with | Best for |
|---|---|---|
| **Web app** | `agent-runtime serve` + `npm run dev` | Everyday use: chat, attach files, download results |
| **CLI** | `agent-runtime chat` / `agent-runtime ask` | Quick tasks and scripting. Answers go to stdout and activity to stderr, with exit codes, and `--json` output matches the API. |
| **HTTP API** | `agent-runtime serve` | Building your own apps. Interactive docs are at http://127.0.0.1:8000/docs. |

Main API endpoints:

| Endpoint | Purpose |
|---|---|
| `POST /v1/chat` / `POST /v1/chat/stream` | Run the agent (whole answer, or streamed events) |
| `GET /v1/tools` · `GET /v1/models` · `GET /health` | What it can do, models and prices, status |
| `POST /v1/files` · `GET`/`DELETE /v1/files/{path}` | Upload, download and delete workspace files |

---

## Documentation

| Read this | If you want to |
|---|---|
| [Backend User Guide](agent-runtime-backend/USER_GUIDE.md) | Install and use the agent from the terminal, in plain language |
| [Web App User Guide](agent-runtime-frontend/USER_GUIDE.md) | Use the web app, in plain language |
| [Backend README](agent-runtime-backend/README.md) | Understand the architecture, the API, configuration, and adding tools |
| [Frontend README](agent-runtime-frontend/README.md) | Develop, test and deploy the web app |
| [Backend Docker guide](agent-runtime-backend/DOCKER.md) | Build and run the API as a Docker container |
| [Frontend Docker guide](agent-runtime-frontend/DOCKER.md) | Build and run the web app in Docker, alone or with Compose |

---

## Development

Each part has its own checks, and both run fully offline. The tests never call
OpenAI.

```powershell
# Backend (in agent-runtime-backend/, venv active)
pytest
ruff check .
ruff format --check .
mypy

# Frontend (in agent-runtime-frontend/)
npm run check          # typecheck + lint + format check + tests
npm run build          # production build into dist/
```

| | Backend | Frontend |
|---|---|---|
| Language | Python 3.11+, mypy strict | TypeScript 6, strict |
| Lint / format | ruff (incl. docstring and security rules) | ESLint (type-checked) / Prettier |
| Tests | pytest: loop, tools, every file format, API, CLI | Vitest + Testing Library: SSE parser, state, API client, full-app integration |

---

## Configuration

- **Backend:** environment variables, or `agent-runtime-backend/.env`. See
  [`.env.example`](agent-runtime-backend/.env.example) for the full list:
  model and prices, workspace folder and read-only mode, file size limits,
  step and time budgets, API key, and CORS.
- **Frontend:** `VITE_API_BASE_URL` and `VITE_PROXY_TARGET`. See
  [`.env.example`](agent-runtime-frontend/.env.example). It needs no
  configuration when it runs next to the backend.

---

## Security notes

- **Keep `.env` private.** It holds your OpenAI key, and it's git-ignored.
- **The workspace is the agent's only reach.** Choose `WORKSPACE_DIR`
  deliberately, and set `WORKSPACE_READ_ONLY=true` to allow reading only.
- **Before exposing the API beyond your own machine, set `API_KEY`.** Without
  it, anyone who can reach the server can read, upload and delete workspace
  files. The web app sends the key from its Settings panel. Use HTTPS when a key
  is in use.
- **Files the agent reads are sent to OpenAI** for processing.

For production deployment, see the Docker guides above, or the
[Frontend README](agent-runtime-frontend/README.md#deploying) for serving the
web app behind your own reverse proxy.
