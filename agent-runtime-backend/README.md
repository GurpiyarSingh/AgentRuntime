# Agent Runtime

A small, transparent **agent runtime backend**. An explicit think → act →
observe loop runs over OpenAI models (via LangChain), with a built-in set of
tools for **reading, viewing and creating files of any type**. Use it two
ways, both on the same core:

- **CLI**: `agent-runtime chat` for a conversation, or `agent-runtime ask` for
  one-shot and scriptable use.
- **HTTP API**: `agent-runtime serve` starts a FastAPI/uvicorn service. A React
  web app for it (sign-in, streaming chat, saved conversations, a folder
  picker) lives next to this folder in
  [agent-runtime-frontend](../agent-runtime-frontend), and any other HTTP client
  works too.

> New to this project, or not a developer? Start with the
> **[User Guide](USER_GUIDE.md)**, which walks through setup and everyday use in
> plain language.

| Tool | What it does |
|---|---|
| `list_files` | Lists a workspace folder (optionally recursively) with sizes |
| `read_file` | Reads any file as text: text/code in any encoding, **PDF**, **Word** (.docx), **Excel** (.xlsx, CSV per sheet), **PowerPoint** (.pptx, with speaker notes), zip/tar archives (lists contents). Other binaries are described rather than dumped. Long files are paged. |
| `read_image` | Lets the model *see* an image: PNG, JPEG, GIF, WEBP, BMP, TIFF, ICO, PSD, AVIF, … (HEIC with an extra). Images are EXIF-oriented, converted and downscaled automatically. |
| `write_file` | Creates any file: text, code, Markdown, CSV, JSON, HTML, **.docx**, **.pdf**, **.xlsx**, **.pptx**, or any binary format from base64 |
| `edit_file` | Exact-text replacement in an existing text/code file |
| `search_files` | Grep across the workspace's text files (literal or regex) |

All of them work inside one sandboxed **workspace** directory, and nothing
outside it. By default that's `WORKSPACE_DIR`; a request may name another
existing directory instead (the web app's folder picker), within limits you
set.

With `DATABASE_URL` set (PostgreSQL, or SQLite), the runtime also keeps
**every conversation and a full activity log** (each event, tool call, token
count and cost), and the web app **signs people in**, each seeing only their
own conversations.

## Why this shape

Most "LangChain agent" examples hide the loop behind a black-box executor.
Here the loop is readable code that announces each thing it does:

```
RunStarted → StepStarted → ModelToken* → ToolCallRequested → ToolCallResult
           → UsageUpdated → StepStarted → ... → FinalAnswer | RunFailed
```

Those events are the same objects whether you read server logs, consume the
streaming API, or assert on them in a test.

```
┌──────────────┐  messages  ┌─────────────┐  tool calls  ┌──────────────────┐
│  AgentLoop   │ ─────────▶ │ OpenAIModel │ ───────────▶ │ list/read/write/ │
│ (think/act/  │ ◀───────── │ (LangChain) │              │ edit/search file │
│   observe)   │ turn+usage └─────────────┘              │ read_image       │
└──────┬───────┘        ▲ images go back as a user turn  └────────┬─────────┘
       │ events         └─────────────────────────────────────────┤
       ▼                                                          ▼
┌──────────────┐ ── /v1/chat  /v1/chat/stream          ┌──────────────────┐
│   FastAPI    │ ── /v1/files  /v1/directories         │    Workspace     │
│   routes     │ ── /v1/tools  /v1/models  /health ──▶ │ (sandboxed dir)  │
└──────┬───────┘ ── /v1/sessions  /v1/auth             └──────────────────┘
       │ transcripts, events, tool calls, accounts
       ▼
┌──────────────────────────────────────┐
│ ConversationStore                    │
│  SessionStore   in memory (default)  │
│  DatabaseStore  PostgreSQL / SQLite  │
└──────────────────────────────────────┘
```

## Project layout

```
src/agent_runtime/
  agent/
    loop.py        The think/act/observe loop: budgets, parallel tool calls, events
    events.py      Everything the loop emits
    messages.py    Plain transcript types (incl. ImageAttachment), no LangChain
    openai.py      The only module that talks to LangChain/OpenAI
    protocols.py   The small ChatModel interface the loop depends on
    outcome.py     Folds a run's events into its result (shared by API and CLI)
  tools/
    base.py        Tool contract: name, description, pydantic args, run()
    registry.py    Name -> Tool lookup, OpenAI schema export
    file_tools.py  The default tools, and default_tools() to build the set
  files/
    workspace.py   Sandboxed path resolution, atomic writes
    directories.py Which directories a request may choose, and browsing them
    readers.py     Any file -> text (PDF, DOCX, XLSX, PPTX, archives, encodings)
    writers.py     Text -> any file (Markdown -> DOCX/PDF, CSV/JSON -> XLSX, ...)
    images.py      Any raster image -> a scaled PNG/JPEG for the model
  storage/
    tables.py      Database schema: users, tokens, sessions, messages, runs, events, tool calls
    store.py       DatabaseStore: persistent history + the run recorder
    users.py       Accounts and sign-in tokens
    codec.py       Transcript messages <-> database rows
  api/
    app.py         FastAPI factory
    routes.py      /health, /v1/models, /v1/tools, /v1/chat, /v1/chat/stream
    files.py       /v1/files: upload, list, download, delete
    directories.py /v1/directories: browse the server's folders
    sessions.py    /v1/sessions: list, open, rename, delete stored conversations
    auth.py        /v1/auth: setup, login, logout, me
    schemas.py     Request/response models
    deps.py        Dependency wiring; who is calling (token, API key, or open)
  auth.py          Password hashing (scrypt), tokens, login throttling, Principal
  cli.py           Command line: chat, ask, serve, tools, models, users
  runtime.py       Composition root: workspace, tools, system prompt, AgentFactory
  config.py        Typed settings from env / .env
  models.py        Selectable models and their token prices
  usage.py         Token + cost accounting
  sessions.py      ConversationStore interface, and the in-memory SessionStore
tests/             Fully offline: no OpenAI calls, no network (databases are SQLite)
```

## Quick start

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -e ".[dev]"          # add ,heic for iPhone HEIC photos
copy .env.example .env           # then set OPENAI_API_KEY
agent-runtime chat               # talk to the agent in the terminal
agent-runtime serve              # or run the HTTP API
```

Run everything from this folder (`agent-runtime-backend/`, the one with
`pyproject.toml`). Settings are read from `.env` in the **current working
directory**, so starting the CLI or server from the repository root won't pick
up your key. If you move or rename the folder, re-run `pip install -e ".[dev]"`,
because the editable install records the absolute path to `src/`.

`python -m agent_runtime` is equivalent to `agent-runtime`. The server listens
on `http://127.0.0.1:8000`, with interactive API docs at `/docs`. The workspace
(`data/workspace` by default) is created on first use.

To run the API in a container instead, see the **[Docker guide](DOCKER.md)**.

## Using the CLI

| Command | Purpose |
|---|---|
| `agent-runtime chat` | Interactive conversation with memory. `/new` resets it, `/help` lists commands, `/exit` (or Ctrl+D) quits. Ctrl+C stops the current answer. |
| `agent-runtime ask MESSAGE...` | One request. `-` reads it from stdin, and `--json` prints the same body `/v1/chat` returns. |
| `agent-runtime serve` | Run the HTTP API (`--host`, `--port`, `--reload`). |
| `agent-runtime tools` | List the tools the agent can call. |
| `agent-runtime models` | List selectable models and their prices. |
| `agent-runtime users add NAME` | Create a web app account (asks for the password twice; `--admin`, `--display-name`, `--password-stdin` for scripts). Needs `DATABASE_URL`. |
| `agent-runtime users list` | Show every account and when it last signed in. |

`chat` and `ask` take `--workspace DIR`, `--read-only`, `--model ID`,
`--max-steps N`, `--no-stream`, `-q/--quiet` and `-v/--verbose`. `serve` and
`tools` take `--workspace` and `--read-only`. Flags override `.env`.

The CLI is built for scripting. The answer goes to **stdout**, while tool
activity, usage, errors and logs go to **stderr**. Exit codes are `0` for
success, `1` when the agent run failed, `2` for bad usage or configuration
(unknown model, missing key) and `130` when interrupted:

```bash
agent-runtime ask -q "Summarise inbox/report.pdf" > summary.txt
cat notes.txt | agent-runtime ask -        # message from stdin
agent-runtime ask --json "List my files" | jq .tool_calls
```

If a turn is interrupted with Ctrl+C, it is discarded, so the conversation
never ends on a tool call without its result.

## Using the API

A typical flow: upload a file, ask the agent about it, then download what it
made.

```bash
# 1. Put an input into the workspace
curl -F "file=@invoice.pdf" -F "path=inbox/" http://127.0.0.1:8000/v1/files

# 2. Ask the agent to work on it
curl -X POST http://127.0.0.1:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Summarise inbox/invoice.pdf into a one-page summary.docx"}'

# 3. Fetch the result
curl -O http://127.0.0.1:8000/v1/files/summary.docx
```

The chat response:

```json
{
  "run_id": "run_3f2a...",
  "session_id": "sess_9c1b...",
  "status": "completed",
  "answer": "I read inbox/invoice.pdf (2 pages) and created summary.docx ...",
  "model": "gpt-4o",
  "steps_used": 3,
  "usage": {"input_tokens": 4210, "output_tokens": 512, "total_tokens": 4722, "cost_usd": 0.015645},
  "tool_calls": [
    {"call_id": "call_1", "tool_name": "read_file", "arguments": {"path": "inbox/invoice.pdf"},
     "content": "File: inbox/invoice.pdf (pdf, 84.2 KB)\nLines 1-61 of 61 ...",
     "is_error": false, "duration_s": 0.21, "image_count": 0},
    {"call_id": "call_2", "tool_name": "write_file", "arguments": {"path": "summary.docx", "...": "..."},
     "content": "Created summary.docx (docx, 36.9 KB).", "is_error": false, "duration_s": 0.08, "image_count": 0}
  ],
  "error": null
}
```

Send the returned `session_id` back to continue the conversation,
`"model": "gpt-5.2"` to pick a model from `/v1/models`, and
`"workspace": "/abs/path/to/folder"` to work in another directory (see
[Choosing the workspace](#choosing-the-workspace)). A run that hits its
step or time budget, or fails upstream, comes back with `"status": "failed"`,
an empty `answer` and the reason in `error`. It is never disguised as
success. (In `ENVIRONMENT=prod` the reason is generic.)

Errors that happen before any model call use HTTP status codes: `400` for an
unknown model or a directory that can't be used, `422` for an invalid body
(`session_id` is at most 128 characters of `A-Z a-z 0-9 _ . : -`), `401` when
not signed in (or a bad API key), `403` when choosing a directory is turned
off, `404` for someone else's session, and `503` when the server has no
`OPENAI_API_KEY`.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Status, default model, enabled tools, workspace mode, whether history is stored |
| `GET` | `/v1/models` | Selectable models and the prices used to cost runs |
| `GET` | `/v1/tools` | Every tool, with the exact JSON schema the model sees |
| `POST` | `/v1/chat` | Run the agent to completion |
| `POST` | `/v1/chat/stream` | Same, as Server-Sent Events |
| `GET` | `/v1/files?path=.` | List workspace files (recursive) |
| `POST` | `/v1/files` | Upload (multipart: `file`, optional `path`, `overwrite`) |
| `GET` | `/v1/files/{path}` | Download a file |
| `DELETE` | `/v1/files/{path}` | Delete a file |
| `GET` | `/v1/directories?path=` | Subfolders of a server folder; top-level locations without `path` |
| `GET` | `/v1/sessions` | Your stored conversations, newest first (`limit`, `offset`, `q` title filter) |
| `GET` | `/v1/sessions/{id}` | One conversation: every run with its recorded events |
| `PATCH` | `/v1/sessions/{id}` | Rename (`{"title": "..."}`) |
| `DELETE` | `/v1/sessions/{id}` | Delete it, with its transcript and activity log |
| `GET` | `/v1/auth/status` | Is sign-in on, and does the first account still need creating? (public) |
| `POST` | `/v1/auth/setup` | Create the first account, as admin; refused once one exists (public) |
| `POST` | `/v1/auth/login` | Username + password -> token (public) |
| `POST` | `/v1/auth/logout` | Revoke this token |
| `GET` | `/v1/auth/me` | The signed-in account |

Every `/v1/files` endpoint also takes `?workspace=` to use a chosen directory.
The `/v1/sessions` endpoints need a database (`501` otherwise).

### Streaming

`POST /v1/chat/stream` takes the same body and emits these SSE events:
`run_started`, `step_started`, `model_token`, `tool_call_requested`,
`tool_call_result`, `usage_updated`, and finally `final_answer` or
`run_failed`. Each `data:` payload is the event as JSON, plus `session_id`
and `model`.

### Auth

Who may call the API depends on the configuration:

| Configuration | Callers must send | They see |
|---|---|---|
| A database, `AUTH_ENABLED=true` (the default with a database) | `Authorization: Bearer <token>` from `/v1/auth/login`, or the `API_KEY` | Their own sessions (admins also see sessions from before sign-in); the API key sees all |
| No database, `API_KEY` set | `X-API-Key: <key>` | Everything |
| No database, no `API_KEY` | Nothing: the server is open | Everything |

`/health`, `/v1/models`, `/v1/tools` and `/v1/auth/status`, `/setup` and
`/login` stay public, so the sign-in page can load.

How sign-in works:

- **The first account is created from the web app** (`/v1/auth/setup`) and is
  an admin. After that, setup is closed; add people with
  `agent-runtime users add NAME`.
- **Passwords** are hashed with scrypt (salted, memory-hard) from the standard
  library. Usernames are case-insensitive.
- **Tokens** are 32 random bytes. The database stores only their SHA-256, so a
  leaked database can't be used to sign in. They last `AUTH_TOKEN_TTL_HOURS`
  (7 days by default) and are revoked on sign-out.
- **Guessing is throttled**: after 5 wrong passwords for one name from one
  address within 5 minutes, sign-in answers `429` with `Retry-After`.
- **Sessions are private.** Listing, opening, renaming, deleting and continuing
  a session all check its owner. Someone else's session answers `404`, not
  `403`, so its existence isn't revealed.

**Without a database, set `API_KEY` before exposing the server beyond
localhost**: the files API can read, upload and delete anything in the
workspace.

## Choosing the workspace

A request may work in a directory other than `WORKSPACE_DIR`: `"workspace"` in
the chat body, `?workspace=` on the files API. The web app's **Browse…** button
uses `GET /v1/directories` to let people pick one on the server's disk (a
browser can't reveal real paths, and the tools run on the server anyway).

A chosen directory must be absolute and already exist. Two settings bound it:

- `WORKSPACE_SELECTABLE=false` turns choosing off: requests always use
  `WORKSPACE_DIR`, and `/v1/directories` answers `403`.
- `WORKSPACE_BROWSE_ROOTS=/data,/srv/shared` limits browsing and choosing to
  those directories and below. Empty (the default) allows anything the server
  process can read. **Set it on any shared server.** The Docker image sets
  `/data`.

Inside the chosen directory, the usual sandbox applies: nothing outside it can
be reached.

## Sessions and the activity log

Without `DATABASE_URL`, conversations live in memory: they expire after
`SESSION_TTL_S` of inactivity and vanish on restart, and nothing else is
recorded.

With it, the `DatabaseStore` keeps everything, in these tables (created at
startup; columns added since are added automatically):

| Table | One row per | Holds |
|---|---|---|
| `users` | Account | Username, display name, scrypt hash, admin flag, last sign-in |
| `auth_tokens` | Signed-in browser | SHA-256 of the token, expiry, last use, client address |
| `sessions` | Conversation | Owner, title (its first message), model, folder, client, totals: runs, tokens, cost |
| `messages` | Transcript entry | The exact messages replayed to the model, including images it was shown |
| `runs` | User message | Status (`running`, `completed`, `failed`, `cancelled`), answer or error, steps, tool calls, tokens, cost, duration |
| `run_events` | Streamed event | The event's type and its JSON payload, exactly as the client received it |
| `tool_calls` | Tool call | Tool, arguments, result, ok/error/cancelled, duration |

A few details:

- **Each event is recorded before it is sent**, so a client that disconnects
  loses nothing; its run is marked `cancelled`.
- **Streamed tokens are stored as one `model_token` event per step**, not one
  per token. Replaying a run's events through the client's reducer rebuilds
  the reply exactly as it was shown live.
- **Recording is best effort.** A failed write is logged and the run carries
  on.
- **The model sees at most `SESSION_MAX_MESSAGES`** of a long conversation,
  but every message is kept.

Payloads are `JSONB` on PostgreSQL, so questions are plain SQL:

```sql
-- Cost per day
select date_trunc('day', started_at) as day, sum(cost_usd) from runs group by 1 order by 1;

-- Which tools fail most
select tool_name, count(*) filter (where is_error) as failures, count(*) from tool_calls group by 1;
```

## Working with files

**The workspace is a sandbox.** Every path from the model or a client is
resolved (following `..` and symlinks) and refused if it lands outside the
request's workspace (`WORKSPACE_DIR`, or the directory the request chose).
Absolute paths are accepted only when they already point inside it. Set `WORKSPACE_READ_ONLY=true` to give the agent no tool that
creates or changes files (the files API still works for the operator).

**How images reach the model.** OpenAI tool results can only carry text. So
`read_image` returns a short text summary as its result, and the loop
attaches the image to that tool message. The OpenAI binding then sends all
images from one step as a single user turn right after the tool results.
Events and API responses carry only `image_count`, never base64. Images stay
in the session history, so follow-up questions about them still work.

**Formats `write_file` understands**, chosen by extension:

- `.docx`, `.pdf`: light Markdown: `#` headings, `-`/`1.` lists, `| tables |`
  and `**bold**`. PDFs use a system TrueType font (Arial/DejaVu) when one is
  found, for full Unicode. Otherwise they fall back to Latin-1.
- `.xlsx`: CSV, a JSON list of rows (lists or objects), or a JSON object of
  `{"Sheet name": rows}`. Numbers stay numeric, and cells starting with `=`
  are formulas.
- `.pptx`: slides separated by `---` lines. The first line is the title,
  `- ` lines are bullets (indent two spaces per level), and `Notes:` lines
  become speaker notes.
- `.json` is validated, and anything else is written as UTF-8 text.
- `encoding: "base64"` writes raw bytes, for images, archives or any binary.
  Writing text into a binary extension such as `.png` is refused.

Writes are atomic (temp file + rename), so a failed render never leaves a
half-written file. Existing files are only replaced with `overwrite: true`.

**Limits.** `read_file` refuses files over `MAX_FILE_BYTES` and returns at
most `READ_MAX_CHARS` per call, with a header like
`Lines 1-812 of 3000 (continue with start_line=813)`. Images are scaled to
fit `IMAGE_MAX_DIMENSION`. Legacy `.doc`/`.xls`/`.ppt` files get a clear
"save as .docx/.xlsx/.pptx" error. Scanned PDFs have no text layer, and the
agent is told so page by page.

## Adding a tool

Subclass `Tool` with a pydantic `args_schema`, and add it in
`default_tools()` in [tools/file_tools.py](src/agent_runtime/tools/file_tools.py)
(or build your own `ToolRegistry` in [runtime.py](src/agent_runtime/runtime.py)):

```python
class WordCountArgs(BaseModel):
    path: str = Field(..., description="File to count, relative to the workspace.")


class WordCountTool(Tool):
    name = "word_count"
    description = "Count the words in a text file."
    args_schema = WordCountArgs

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    async def run(self, path: str) -> str:  # type: ignore[override]
        try:
            file = self._workspace.existing_file(path)
        except WorkspaceError as exc:
            raise ToolError(str(exc)) from exc
        return str(len(file.read_text(encoding="utf-8").split()))
```

Return a string, or a `ToolOutput(content=..., images=[...])` if the model
should see images. Raise `ToolError` for anything the model should be told
about and recover from. `/v1/tools` and `/health` pick the new tool up
automatically.

### Using a different model provider

The loop never imports LangChain or OpenAI. It depends only on the four-member
`ChatModel` protocol in [agent/protocols.py](src/agent_runtime/agent/protocols.py):
`invoke`, `stream`, `chunk_text` and `accumulate`, plus a `model_id`. To swap
providers, write a class like
[`OpenAIModel`](src/agent_runtime/agent/openai.py) and build it in
`AgentFactory` in [runtime.py](src/agent_runtime/runtime.py), which is the
composition root that decides what every request runs with.

## Configuration

All settings live in [config.py](src/agent_runtime/config.py), read from the
environment or `.env`. See [.env.example](.env.example) for the full list:
workspace (`WORKSPACE_DIR`, `WORKSPACE_READ_ONLY`, `WORKSPACE_SELECTABLE`,
`WORKSPACE_BROWSE_ROOTS`, `MAX_FILE_BYTES`, `READ_MAX_CHARS`,
`IMAGE_MAX_DIMENSION`), persistence (`DATABASE_URL`, `DATABASE_ECHO`),
sign-in (`AUTH_ENABLED`, `AUTH_TOKEN_TTL_HOURS`), loop budget (`MAX_STEPS`,
`TOOL_TIMEOUT_S`, `RUN_TIMEOUT_S`, `MAX_PARALLEL_TOOL_CALLS`), sessions,
server and the API key.

`DATABASE_URL` takes a plain URL, and the async driver is picked for you:
`postgresql://user:password@host:5432/agent_runtime` uses asyncpg, and
`sqlite:///path/to/file.db` uses aiosqlite. The database itself must exist.

**`.env` is read once, at startup.** After changing it, restart the server:
`--reload` restarts only on code changes.

### Token prices

Costs are computed from the token counts the provider reports, times the
rates in [models.py](src/agent_runtime/models.py) (USD per 1M tokens).
**Check those against OpenAI's current pricing.** The `gpt-5.2` entry in
particular ships as a placeholder. You can correct any of them without
touching code:

```
MODEL_PRICING_JSON={"gpt-5.2": {"input_usd_per_1m": 1.25, "output_usd_per_1m": 10.0}}
```

When a provider reports no counts, `cost_usd` is `null` rather than `0`, so
"unknown" and "free" never look the same. Image inputs are billed by OpenAI
as input tokens and show up in the same counts.

## Development

```powershell
pytest                 # the full suite, fully offline
ruff check .           # lint, including docstring and security rules
ruff format --check .  # formatting
mypy                   # strict type checking
```

Lint goes beyond style. Every public module, class and function must have a
docstring (Google convention), and the bandit security rules, blind-`except`
checks and logging rules are on. Tests are exempt from the docstring rules,
since their names state their intent.

The suite never calls OpenAI and never opens a socket. `tests/fakes.py`
provides a `FakeChatModel` that replays scripted turns. The file tools,
readers and writers run against real libraries in a temporary directory:
every document format is written and read back. Workspace escapes
(`..`, absolute paths, symlinks), choosing and browsing directories, the
files API, image delivery to the model and token accounting are all tested
deterministically. The database store, the activity log, history across a
restart, sign-in, per-user isolation and throttling run against a temporary
SQLite file, through the same code that serves PostgreSQL.

Run one server process. Without a database, conversations live in that
process's memory. With one, history is shared, but two runs on the same
session at once could interleave their transcript writes. For several
workers, also point `WORKSPACE_DIR` at shared storage. As the schema stops
being purely additive, adopt a migration tool such as Alembic.
