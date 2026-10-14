# Agent Runtime: Frontend

A React web UI for the [agent-runtime backend](../agent-runtime-backend). The
**tools sidebar** on the left lists every tool the agent can call, each
expandable to its full description and parameters. The **chat** on the right
streams the agent's reply token by token and shows each tool call inline as it
runs.

![The Agent Runtime web app](docs/screenshot.png)

> Not a developer? The **[User Guide](USER_GUIDE.md)** explains how to start and
> use the web app in plain language.

What it does:

- **Live streaming** over `POST /v1/chat/stream`. Each tool call appears as a
  card with its status, arguments, result and duration.
- **File attachments**: picked files are uploaded to the workspace's
  `uploads/` folder and their paths are passed to the agent.
- **Downloads**: files the agent creates with `write_file` get a download
  button.
- **Conversations**: follow-up messages continue the same session. **New
  chat** starts over, and **Stop** cancels a run. The backend then discards
  the unfinished turn, so the conversation stays consistent.
- **Model picker** from `GET /v1/models`, remembered per browser, with token
  usage and cost shown under each reply.
- **Optional API key** (Settings), for servers started with `API_KEY`.
- **Connection and read-only status**, with a retry banner when the server is
  unreachable.
- **Responsive and accessible**: on narrow screens the sidebar becomes a
  drawer. It has light and dark themes, works fully from the keyboard, and
  announces finished replies to screen readers.

## Quick start

Requires Node.js 20.19+ and a running backend (`agent-runtime serve`, by
default on port 8000).

```bash
npm install
npm run dev        # http://localhost:5173
```

In development, Vite proxies `/v1` and `/health` to the backend, so no CORS
setup is needed. To proxy to a backend somewhere else, set `VITE_PROXY_TARGET`
in `.env.local` (see [.env.example](.env.example)).

## Scripts

| Command                           | What it does                                                   |
| --------------------------------- | -------------------------------------------------------------- |
| `npm run dev`                     | Dev server with hot reload                                     |
| `npm run build`                   | Type-check and build to `dist/`                                |
| `npm run preview`                 | Serve the production build locally                             |
| `npm run check`                   | Everything CI should run: typecheck, lint, format check, tests |
| `npm test` / `npm run test:watch` | Vitest, once or in watch mode                                  |
| `npm run lint` / `npm run format` | ESLint / Prettier                                              |

## Deploying

**With Docker:** the [Dockerfile](Dockerfile) builds an unprivileged nginx
image that serves the app and proxies the API, already configured for
streaming. See the **[Docker guide](DOCKER.md)**.

**Without Docker:** `npm run build` produces static files in `dist/`. Serve
them however you like. There are two setups.

**Same origin (recommended).** Serve `dist/` and proxy the API paths to the
backend from one host. Leave `VITE_API_BASE_URL` empty. Example nginx config:

```nginx
server {
    listen 80;
    root /srv/agent-runtime-frontend/dist;

    location / {
        try_files $uri /index.html;
    }

    location ~ ^/(v1|health) {
        proxy_pass http://127.0.0.1:8000;
        # Stream chat events as they are produced, not when the reply ends.
        proxy_buffering off;
        proxy_read_timeout 300s;
        client_max_body_size 30m;   # Attachments; match MAX_FILE_BYTES.
    }
}
```

**Separate origins.** Build with `VITE_API_BASE_URL=https://api.example.com`
and add the UI's origin to the backend's `CORS_ALLOW_ORIGINS`.

Every `VITE_*` value is compiled into the JavaScript bundle and is visible to
anyone. Never put the API key there. Users enter it in Settings, and it stays in
their browser's localStorage. Use HTTPS whenever an API key is in use.

## Project structure

```
src/
  api/
    types.ts          Wire types, mirroring the backend's schemas and events
    client.ts         Typed API client: errors, API key, uploads, downloads, streaming
    sse.ts            Server-Sent Events parser for fetch streams (EventSource can't POST)
    ApiContext.tsx    Provides the client to components
  chat/
    chatReducer.ts    Pure reducer: stream events -> conversation turns
    useChat.ts        Sends messages, streams runs, stop / new chat
    useAttachments.ts Uploads attached files into the workspace
  components/
    sidebar/          Sidebar, ToolList, ToolItem (parameters), SettingsPanel
    chat/             ChatPanel, MessageList, Message, ToolCallCard, Composer, Markdown
    Icon.tsx          Inline SVG icons
  hooks/useResource.ts  Load-once data hook with cancellation and reload
  lib/                Formatting, storage, schema and tool-call helpers
  styles/global.css   Design tokens (light and dark) and base styles
  Root.tsx, App.tsx   Client and API key setup; the two-column shell
  test/               Test setup and a fake backend for integration tests
```

Design notes:

- **The API contract lives in one file.** `api/types.ts` mirrors the backend
  field for field. When the backend changes, update it, and the compiler
  points at everything that has to follow.
- **Conversation logic is a pure reducer.** Every rule about how events become
  what the user sees (token merging, pairing tool results with their calls,
  terminal states) is unit-tested without React.
- **Model output is never rendered as HTML.** Markdown is rendered with
  `react-markdown`, which ignores raw HTML, and links open in a new tab
  without opener access.
- **No UI framework.** CSS Modules with design tokens in `global.css`, so
  there's no runtime styling cost and nothing to override.

## Testing

`npm test` runs four kinds of tests, all offline:

- **The SSE parser**, including events split at every possible chunk boundary,
  CRLF split across chunks, and UTF-8 characters split across byte chunks.
- **The chat reducer.**
- **The API client**: error mapping, API key header, streaming, URL encoding.
- **Integration tests of the whole app** against a fake backend
  (`src/test/fakeServer.ts`): tools in the sidebar, streaming replies with
  tool cards and downloads, sessions, stop, attachments, errors and the
  offline state.
