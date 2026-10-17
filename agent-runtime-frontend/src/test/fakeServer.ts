/**
 * A fake agent-runtime backend for tests: a `fetch` implementation that
 * answers the routes the UI calls, with scripted chat streams. Records each
 * request so tests can assert on what the UI sent.
 */

import type {
  AgentEvent,
  DirectoryListing,
  Health,
  McpServer,
  McpServerConfig,
  ModelsResponse,
  SessionDetail,
  Tool,
} from '../api/types';

export const TOOLS: Tool[] = [
  {
    name: 'read_file',
    description: 'Read a file as text. Works for PDF, Word and more.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'File to read, relative to the workspace.' },
        start_line: { type: 'integer', default: 1, description: 'First line to return.' },
      },
      required: ['path'],
    },
  },
  {
    name: 'write_file',
    description: 'Create a file of any type. Refuses to overwrite.',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string' },
        encoding: { enum: ['text', 'base64'], default: 'text' },
      },
      required: ['path'],
    },
  },
];

export const HEALTH: Health = {
  status: 'ok',
  app_name: 'agent-runtime',
  environment: 'local',
  model: 'gpt-4o',
  tools: TOOLS.map((tool) => tool.name),
  workspace: { read_only: false, path: '/tmp/ws', selectable: true },
};

/** A tiny server disk: `/` holds `/tmp`, which holds `/tmp/ws` and `/tmp/project`. */
export function directoryListing(path: string | null): DirectoryListing {
  const children: Record<string, string[]> = {
    '/': ['/tmp'],
    '/tmp': ['/tmp/project', '/tmp/ws'],
  };
  const at = path ?? '';
  const directories = (path === null ? ['/'] : (children[at] ?? [])).map((dir) => ({
    name: dir === '/' ? '/' : (dir.split('/').pop() ?? dir),
    path: dir,
  }));
  const parent = path === null || path === '/' ? null : path.slice(0, path.lastIndexOf('/')) || '/';
  return { path, parent, directories, truncated: false };
}

export const MODELS: ModelsResponse = {
  default: 'gpt-4o',
  models: [
    {
      id: 'gpt-4o',
      label: 'GPT-4o',
      description: 'Fast.',
      input_usd_per_1m: 2.5,
      output_usd_per_1m: 10,
    },
    {
      id: 'gpt-5.2',
      label: 'GPT-5.2',
      description: 'Strong.',
      input_usd_per_1m: 1.25,
      output_usd_per_1m: 10,
    },
  ],
};

export const MCP_CONFIG: McpServerConfig = {
  type: 'stdio',
  command: 'uvx',
  args: ['mcp-server-fetch'],
  env: {},
  cwd: null,
  url: null,
  headers: {},
  enabled: true,
  timeout_s: 60,
  description: '',
};

function mcpTool(server: string, tool: string) {
  return {
    name: tool,
    qualified_name: `${server}__${tool}`,
    description: `The ${tool} tool.`,
    parameters: {},
  };
}

/** A server as the backend reports it: connected with one tool, or disabled. */
export function mcpServer(name: string, config: McpServerConfig = MCP_CONFIG): McpServer {
  const on = config.enabled;
  return {
    name,
    config,
    status: on ? 'connected' : 'disabled',
    error: null,
    server_name: on ? `${name}-server` : null,
    server_version: on ? '1.0' : null,
    connected_at: on ? new Date().toISOString() : null,
    tools: on ? [mcpTool(name, 'search')] : [],
  };
}

/** Serialise events the way the backend's SSE endpoint does. */
export function sseBody(events: AgentEvent[]): string {
  return events
    .map(({ type, data }) => `event: ${type}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`)
    .join('');
}

/** A body that streams `first`, then never ends until the request is aborted. */
function hangingStream(first: string, signal: AbortSignal | null | undefined): ReadableStream {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(first));
      signal?.addEventListener('abort', () => {
        controller.error(new DOMException('Aborted', 'AbortError'));
      });
    },
  });
}

export interface RecordedRequest {
  url: string;
  method: string;
  headers: Headers;
  body: unknown;
}

export interface FakeServerOptions {
  /** One entry per chat request: events to stream, or 'hang' to never finish. */
  chats?: (AgentEvent[] | { hangAfter: AgentEvent[] } | { status: number; detail: string })[];
  /**
   * Sign-in: the server's accounts (username -> password). Empty means the
   * first visitor must create the admin. Omitted means sign-in is off.
   */
  accounts?: Record<string, string>;
  /** MCP servers; when given, health reports `mcp: true`. */
  mcp?: { servers: McpServer[]; canManage?: boolean };
  /** Stored sessions; when given, health reports `history: true`. */
  sessions?: SessionDetail[];
  /** Respond to /v1/tools with this status instead of the tool list. */
  toolsStatus?: number;
  offline?: boolean;
}

export function createFakeServer(options: FakeServerOptions = {}) {
  const requests: RecordedRequest[] = [];
  const chats = [...(options.chats ?? [])];
  const sessions = options.sessions ? [...options.sessions] : null;
  const mcpServers = options.mcp ? [...options.mcp.servers] : null;
  const accounts = options.accounts ? { ...options.accounts } : null;
  const tokens = new Map<string, string>(); // token -> username
  const userFor = (username: string) => ({
    id: `usr_${username}`,
    username,
    display_name: username === 'ada' ? 'Ada Lovelace' : '',
    is_admin: true,
    created_at: '',
    last_login_at: null,
  });
  const signIn = (username: string) => {
    const token = `tok_${username}_${tokens.size}`;
    tokens.set(token, username);
    return { token, user: userFor(username) };
  };

  const fetch: typeof globalThis.fetch = async (input, init = {}) => {
    const url = input instanceof Request ? input.url : input.toString();
    const method = init.method ?? 'GET';
    const body = typeof init.body === 'string' ? (JSON.parse(init.body) as unknown) : init.body;
    requests.push({ url, method, headers: new Headers(init.headers), body });
    await Promise.resolve();

    if (options.offline) throw new TypeError('Failed to fetch');
    const json = (data: unknown, status = 200) =>
      new Response(JSON.stringify(data), {
        status,
        headers: { 'Content-Type': 'application/json' },
      });

    if (url.includes('/v1/auth/')) {
      const route = url.slice(url.indexOf('/v1/auth/') + '/v1/auth/'.length);
      if (!accounts) return json({ detail: 'Not Found' }, 404);
      const credentials = body as { username: string; password: string } | undefined;
      const bearer = new Headers(init.headers).get('Authorization')?.replace('Bearer ', '') ?? '';
      if (route === 'status') {
        return json({ enabled: true, setup_required: Object.keys(accounts).length === 0 });
      }
      if (route === 'setup' && credentials) {
        accounts[credentials.username] = credentials.password;
        return json(signIn(credentials.username), 201);
      }
      if (route === 'login' && credentials) {
        return accounts[credentials.username] === credentials.password
          ? json(signIn(credentials.username))
          : json({ detail: 'Wrong username or password.' }, 401);
      }
      if (route === 'logout') {
        tokens.delete(bearer);
        return new Response(null, { status: 204 });
      }
      if (route === 'me') {
        const username = tokens.get(bearer);
        return username ? json(userFor(username)) : json({ detail: 'Sign in to continue.' }, 401);
      }
    }
    if (url.endsWith('/health')) {
      return json({ ...HEALTH, history: sessions !== null, mcp: mcpServers !== null });
    }
    if (mcpServers !== null && url.includes('/v1/mcp/')) {
      const route = new URL(url, 'http://x').pathname.slice('/v1/mcp/'.length).split('/');
      const name = decodeURIComponent(route[1] ?? '');
      const index = mcpServers.findIndex((server) => server.name === name);
      if (route[0] === 'test') {
        return json({
          ok: true,
          duration_s: 0.42,
          error: null,
          server_name: 'fake-mcp',
          server_version: '1.0',
          tools: [mcpTool('server', 'fetch')],
        });
      }
      if (route[0] === 'import') {
        const pasted = JSON.parse((body as { json: string }).json) as {
          mcpServers: Record<string, Partial<McpServerConfig>>;
        };
        const added = Object.entries(pasted.mcpServers).map(([serverName, config]) => {
          mcpServers.push(mcpServer(serverName, { ...MCP_CONFIG, ...config }));
          return serverName;
        });
        return json({ added, replaced: [], skipped: [] });
      }
      if (route[0] === 'servers' && !name) {
        if (method === 'POST') {
          const created = body as { name: string; config: McpServerConfig };
          const server = mcpServer(created.name, created.config);
          mcpServers.push(server);
          return json(server, 201);
        }
        return json({
          servers: mcpServers,
          can_manage: options.mcp?.canManage ?? true,
          allow_stdio: true,
        });
      }
      const current = mcpServers[index];
      if (!current) return json({ detail: 'Not found' }, 404);
      if (method === 'DELETE') {
        mcpServers.splice(index, 1);
        return new Response(null, { status: 204 });
      }
      if (method === 'PATCH') {
        const { enabled } = body as { enabled: boolean };
        mcpServers[index] = mcpServer(name, { ...current.config, enabled });
        return json(mcpServers[index]);
      }
      if (method === 'PUT') {
        mcpServers[index] = mcpServer(name, body as McpServerConfig);
        return json(mcpServers[index]);
      }
      return json(current); // reconnect
    }
    if (sessions !== null && url.includes('/v1/sessions')) {
      const id = decodeURIComponent(new URL(url, 'http://x').pathname.split('/')[3] ?? '');
      if (!id) return json({ sessions: sessions.map(({ runs: _runs, ...summary }) => summary) });
      const index = sessions.findIndex((session) => session.id === id);
      if (index === -1) return json({ detail: 'Not found' }, 404);
      if (method === 'DELETE') {
        sessions.splice(index, 1);
        return new Response(null, { status: 204 });
      }
      if (method === 'PATCH') {
        const session = sessions[index] as SessionDetail;
        session.title = (body as { title: string }).title;
        return json(session);
      }
      return json(sessions[index]);
    }
    if (url.endsWith('/v1/models')) return json(MODELS);
    if (url.endsWith('/v1/tools')) {
      const fromMcp: Tool[] = (mcpServers ?? []).flatMap((server) =>
        server.tools.map((tool) => ({
          name: tool.qualified_name,
          description: `[${server.name}] ${tool.description}`,
          parameters: { type: 'object' as const, properties: {} },
          source: 'mcp' as const,
          server: server.name,
        })),
      );
      return options.toolsStatus
        ? json({ detail: 'Invalid or missing API key' }, options.toolsStatus)
        : json({ tools: [...TOOLS, ...fromMcp] });
    }
    if (url.includes('/v1/directories')) {
      return json(directoryListing(new URL(url, 'http://x').searchParams.get('path')));
    }
    if (url.includes('/v1/files') && !url.includes('/v1/files/') && method === 'POST') {
      const file = (init.body as FormData).get('file') as File;
      return json({ path: `uploads/${file.name}`, size: file.size, modified: '' }, 201);
    }
    if (url.includes('/v1/files/')) {
      return new Response(new Blob(['file-bytes']), { status: 200 });
    }
    if (url.includes('/v1/chat/stream')) {
      const script = chats.shift();
      if (!script) throw new Error('fake server: no scripted chat left');
      if ('status' in script) return json({ detail: script.detail }, script.status);
      const stream =
        'hangAfter' in script
          ? hangingStream(sseBody(script.hangAfter), init.signal)
          : sseBody(script);
      return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } });
    }
    return json({ detail: 'Not Found' }, 404);
  };

  return { fetch, requests };
}
