# Agent Runtime

A small, transparent **multi-agent runtime**. An orchestrator routes each
request to a specialist agent; that agent runs an explicit think → act →
observe loop over OpenAI models (via LangChain), served over HTTP with
FastAPI/uvicorn.

Two specialists ship today:

| Agent | What it does | Tool |
|---|---|---|
| **email** | Writes and sends plain-text email over SMTP | `send_email` |
| **youtube** | Finds videos and returns working watch links | `search_youtube` |

The orchestrator routes each message to one of them — and the third agent
is a registration, not a rewrite.

Pick the model per message (**GPT-4o** or **GPT-5.2**), watch every step
of the loop stream live, and see what each message cost in tokens and
dollars.

> **Email is off by default.** `EMAIL_DRY_RUN=true` ships as the default:
> the agent composes and validates a real message, shows you exactly what
> would have gone out, and sends nothing. See [Sending for real](#sending-for-real).

## Why this shape

Most "LangChain agent" examples hide the loop behind a black-box executor,
and most "multi-agent" demos hide the routing too. Here both are readable
code that announce what they did:

```
AgentSelected → RunStarted → StepStarted → ModelToken* → ToolCallRequested
              → ToolCallResult → UsageUpdated → ... → FinalAnswer | RunFailed
              → AgentCompleted
```

Routing brackets the agent's own events, so a future multi-agent turn is
just more of these blocks back to back — no client has to learn a new
shape to read it. Those events are the same objects whether you're reading
server logs, consuming the streaming API, or asserting on them in a test.

```
                    ┌────────────────┐
   request ───────▶ │  Orchestrator  │ ── picks an agent (explicit, or routed)
                    └───────┬────────┘
                            │ AgentSpec: prompt + tools
                            ▼
┌──────────────┐  messages  ┌─────────────┐  tool calls  ┌────────────────┐
│  AgentLoop   │ ─────────▶ │ OpenAIModel │ ───────────▶ │ send_email     │
│ (think/act/  │ ◀───────── │ (LangChain) │              │ search_youtube │
│  observe)    │ turn+usage └─────────────┘              └───────┬────────┘
└──────┬───────┘                                                 │
       │ events                         ┌────────────────────────▼───────────┐
       ▼                                │ EmailPolicy + Transport (SMTP/dry) │
┌──────────────┐ ── /v1/chat            │ YouTube client (links are built)   │
│  FastAPI     │ ── /v1/chat/stream     └────────────────────────────────────┘
│  routes      │ ── /v1/agents  /v1/models
└──────────────┘
```

## Project layout

```
src/agent_runtime/
  orchestrator/
    orchestrator.py  Routes a turn to an agent, runs it, reports how it went
    router.py         Explicit choice > only-agent shortcut > model routing
    events.py          AgentSelected / AgentCompleted
  agents/
    base.py           AgentSpec: name, prompt, tools, readiness — an agent is data
    email_agent.py     The email specialist and its instructions
    youtube_agent.py    The video-search specialist
    registry.py          Name -> spec; first registered is the default
  agent/
    loop.py           The agent loop itself (think/act/observe, budgets, events)
    events.py          Typed events the loop emits (RunStarted, ToolCallResult, ...)
    messages.py         Provider-agnostic message/transcript types
    openai.py            The only module that imports LangChain / OpenAI
    protocols.py          Structural "ChatModel" interface, for test doubles
  mail/
    message.py        OutgoingEmail + EmailPolicy (the rules, independent of LLMs)
    transport.py       DryRun / SMTP / Recording transports behind one protocol
  youtube/
    search.py         VideoResult + query rules; links are built, never echoed
    client.py          API / Unconfigured / Fake clients behind one protocol
  tools/
    base.py           Tool contract (name, args schema, run())
    registry.py        Name -> Tool lookup, schema export for function-calling
    email_tools.py      send_email
    youtube_tools.py     search_youtube
  api/
    app.py            FastAPI app factory (CORS, lifespan, errors, UI mount)
    routes.py          /health, /v1/agents, /v1/models, /v1/chat, /v1/chat/stream
    deps.py             Dependency wiring (settings, agents, sessions, auth)
    schemas.py           Request/response models
  web/static/         Chat UI: agent sidebar, model picker, live trace, cost per message
  wiring.py           Settings -> policy, transport, agent registry (one place)
  models.py            Selectable models + their token prices
  usage.py              Token counts and what they cost
  sessions.py            In-memory, TTL-bounded conversation store
  config.py               Typed settings (env / .env via pydantic-settings)
tests/                pytest suite — no network, no SMTP, no real model calls
```

## Setup

Requires Python 3.11+ and an [OpenAI API key](https://platform.openai.com/api-keys).

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

copy .env.example .env
# then edit .env: set OPENAI_API_KEY, and EMAIL_FROM
```

## Run it

```powershell
python -m agent_runtime      # or: agent-runtime
```

Open **http://127.0.0.1:8000**.

The **left sidebar** lists every registered agent with its description, the
tools it can call, and whether it is actually ready — a green dot for
working, purple for a caveat like the email dry run, red for missing
credentials. The dot pulses on whichever agent is handling the current run.
Click an agent to pin every message to it; click again for auto routing.

The top bar has the compact **Agent** picker (the same state as the sidebar,
kept for narrow screens where the sidebar hides) and the **Model** picker
(`gpt-4o` or `gpt-5.2`, remembered across reloads).

Each message shows which agent took it, every tool call with its arguments
and result, and a footer with tokens and cost.

**Terminal REPL** (no HTTP):

```powershell
python -m agent_runtime.cli
```

## Finding videos

The YouTube agent calls the [YouTube Data API v3](https://developers.google.com/youtube/v3/docs/search/list).
Create a key in the [Google Cloud console](https://console.cloud.google.com/apis/credentials),
enable **YouTube Data API v3** for that project, then:

```
YOUTUBE_API_KEY=your-key
YOUTUBE_MAX_RESULTS=5      # default per search
YOUTUBE_RESULT_CEILING=10  # hard cap, whatever the model asks for
```

Without a key the agent still appears in the sidebar, marked not ready, and
reports that search is unavailable. That is deliberate: the failure mode
worth designing against here is **fabrication**. A model will happily
produce a plausible `youtube.com/watch?v=...` from memory, and a wrong
eleven-character id is indistinguishable from a real one until someone
clicks it. So:

- Every URL is built from the video id by `VideoResult.url` — the agent
  relays links the runtime constructed, never one it recalled.
- Entries without a usable id are dropped rather than surfaced as dead links.
- An empty search returns text that explicitly tells the model to say
  nothing matched instead of guessing.
- The unconfigured client's error message steers the model the same way.

Search is capped at `type=video`, and an over-large `max_results` is clamped
rather than rejected — the exact number is incidental to what the user asked
for. The free API quota is 10,000 units/day and a search costs 100, so
roughly 100 searches a day.

## Sending for real

Dry run is the default. To actually deliver mail, all of the following must
be true — any one missing and the runtime falls back to dry run and logs a
warning rather than silently dropping messages:

```
EMAIL_DRY_RUN=false
EMAIL_FROM=you@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@example.com
SMTP_PASSWORD=your-app-password
```

For Gmail, `SMTP_PASSWORD` must be an
[App Password](https://support.google.com/accounts/answer/185833), not your
account password. `GET /health` always reports the truth in `email.dry_run`.

### What the agent cannot do

The guardrails live in `EmailPolicy` ([mail/message.py](src/agent_runtime/mail/message.py)),
not in the prompt, so they hold regardless of what the model is asked to do:

| Guardrail | Why |
|---|---|
| The sender is server config, never a tool argument | A model that picks its own `From` could impersonate anyone your SMTP server relays for |
| No BCC field exists | Hidden recipients are the one thing a reviewer of the run's trace couldn't see |
| `EMAIL_MAX_RECIPIENTS` (default 5) | One bad instruction shouldn't become a mass mailing |
| `EMAIL_ALLOWED_DOMAINS` (optional) | Pin an agent to your own organisation |
| Plain text only, no HTML | Arbitrary model-authored HTML is a much larger surface for no gain |

A rejected send comes back to the model as an observation it can correct
("that address is malformed"), not a crashed run.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Redirects to the chat UI at `/ui/` |
| `/ui/` | GET | Built-in chat UI |
| `/docs` | GET | Swagger / OpenAPI explorer |
| `/health` | GET | Status, model, agents, **whether email is live and YouTube configured** |
| `/v1/agents` | GET | Every agent, with its tools and whether it is ready |
| `/v1/models` | GET | Selectable models with their per-1M-token prices |
| `/v1/chat` | POST | Routes, runs to completion, returns the answer + trace |
| `/v1/chat/stream` | POST | Same, streamed as SSE as it progresses |

Request body for both chat endpoints:

```json
{
  "message": "Email alex@example.com that Friday's release slipped to Tuesday",
  "session_id": "optional, to continue a conversation",
  "agent": "optional, email or youtube — omit to let the orchestrator route",
  "model": "optional, e.g. gpt-5.2 — defaults to OPENAI_MODEL"
}
```

An unknown `agent` or `model` is rejected with `400` before the run starts,
so a typo costs nothing.

```json
{
  "run_id": "run_9f2c1a7b3e40",
  "session_id": "sess_4d81b2e6c905",
  "status": "completed",
  "answer": "I sent the note to alex@example.com.",
  "agent": "email",
  "model": "gpt-4o",
  "steps_used": 2,
  "usage": { "input_tokens": 930, "output_tokens": 86, "total_tokens": 1016, "cost_usd": 0.003185 },
  "tool_calls": [
    {
      "call_id": "call_email_1",
      "tool_name": "send_email",
      "arguments": { "to": ["alex@example.com"], "subject": "Release moved to Tuesday", "body": "Hi Alex, ..." },
      "content": "Sent to alex@example.com with subject 'Release moved to Tuesday'.",
      "is_error": false,
      "duration_s": 0.41
    }
  ],
  "error": null
}
```

A run that hits its step/time budget or fails upstream comes back with
`"status": "failed"`, an empty `answer`, and the reason in `error` — never
disguised as success. (In `ENVIRONMENT=prod` the reason is generic.) If
`API_KEY` is set, both chat endpoints require an `X-API-Key` header.

## Adding the next agent

This is the whole point of the orchestrator. Build an `AgentSpec` and
register it in [wiring.py](src/agent_runtime/wiring.py):

```python
def build_agents(settings, transport=None, youtube_client=None):
    return AgentRegistry([
        build_email_agent(build_email_policy(settings), transport),
        build_youtube_agent(client, ...),
        build_calendar_agent(...),   # <- the new one
    ])
```

That is the only required change. `/v1/agents`, the sidebar, the picker and
the routing events all pick it up automatically.

**Note on routing cost:** with one agent the router answers for free. From
two agents on, an auto-routed message makes one extra model call to choose
(a short prompt: the agent list plus the user's message). Pin an agent in
the sidebar — or send `"agent": "youtube"` — to skip that call entirely.

A new capability for an *existing* agent is a `Tool` subclass added to its
registry — see [tools/youtube_tools.py](src/agent_runtime/tools/youtube_tools.py)
for the smallest complete example.

To use a different model provider, only
[agent/openai.py](src/agent_runtime/agent/openai.py) changes — the loop
depends on the small `ChatModel` protocol, not on LangChain.

## Configuration

All settings live in [config.py](src/agent_runtime/config.py), read from the
environment or `.env` — see [.env.example](.env.example) for the full list,
including the step budget (`MAX_STEPS`), timeouts, and tool concurrency.

### Token prices

Costs are computed from the token counts the provider reports, times the
rates in [models.py](src/agent_runtime/models.py) (USD per 1M tokens).
**Check those against OpenAI's current pricing** — the `gpt-5.2` entry in
particular ships as a placeholder. Correct any of them without touching code:

```
MODEL_PRICING_JSON={"gpt-5.2": {"input_usd_per_1m": 1.25, "output_usd_per_1m": 10.0}}
```

The figure estimates list price; it doesn't know about cached-input or batch
discounts. When a provider reports no counts, `cost_usd` is `null` rather
than `0` — "unknown" and "free" are never shown as the same thing.

## Testing

```powershell
pytest
ruff check .
mypy
```

The suite never calls OpenAI or YouTube, never opens a socket, and never
sends mail: `tests/fakes.py` provides a `FakeChatModel` replaying scripted
turns, `RecordingTransport` stands in for SMTP, and `FakeYouTubeClient` (plus
`httpx.MockTransport` for the real client's request shape) stands in for the
API. Routing, the loop's control flow, the email guardrails, link
construction and token accounting are all tested deterministically.
