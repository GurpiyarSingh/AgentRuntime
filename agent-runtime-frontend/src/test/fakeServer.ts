/**
 * A fake agent-runtime backend for tests: a `fetch` implementation that
 * answers the routes the UI calls, with scripted chat streams. Records each
 * request so tests can assert on what the UI sent.
 */

import type { AgentEvent, Health, ModelsResponse, Tool } from '../api/types';

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
  workspace: { read_only: false, path: '/tmp/ws' },
};

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
  /** Respond to /v1/tools with this status instead of the tool list. */
  toolsStatus?: number;
  offline?: boolean;
}

export function createFakeServer(options: FakeServerOptions = {}) {
  const requests: RecordedRequest[] = [];
  const chats = [...(options.chats ?? [])];

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

    if (url.endsWith('/health')) return json(HEALTH);
    if (url.endsWith('/v1/models')) return json(MODELS);
    if (url.endsWith('/v1/tools')) {
      return options.toolsStatus
        ? json({ detail: 'Invalid or missing API key' }, options.toolsStatus)
        : json({ tools: TOOLS });
    }
    if (url.endsWith('/v1/files') && method === 'POST') {
      const file = (init.body as FormData).get('file') as File;
      return json({ path: `uploads/${file.name}`, size: file.size, modified: '' }, 201);
    }
    if (url.includes('/v1/files/')) {
      return new Response(new Blob(['file-bytes']), { status: 200 });
    }
    if (url.endsWith('/v1/chat/stream')) {
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
