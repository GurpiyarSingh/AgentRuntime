/**
 * Typed client for the agent-runtime HTTP API.
 *
 * Every request goes through `request`, which adds the optional API key,
 * turns non-2xx responses into `ApiError` (with the server's `detail`), and
 * turns network failures into an `ApiError` with status 0, so callers deal
 * with one error type.
 */

import { readSse } from './sse';
import {
  AGENT_EVENT_TYPES,
  type AgentEvent,
  type ChatRequest,
  type Health,
  type ModelsResponse,
  type Tool,
  type ToolsResponse,
  type WorkspaceFile,
} from './types';

/** A failed API call. `status` is the HTTP status, or 0 if the server was unreachable. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }

  /** True when the request never got a response (server down, network, CORS). */
  get isNetworkError(): boolean {
    return this.status === 0;
  }
}

export interface ApiClientOptions {
  /** Backend origin, e.g. `https://agent.example.com`; empty for same-origin. */
  baseUrl: string;
  /** Returns the current API key (read per request, so a changed key applies at once). */
  getApiKey?: () => string;
  /** Injectable for tests. */
  fetch?: typeof fetch;
}

/** Pull a readable message out of an error response (FastAPI puts it in `detail`). */
async function errorMessage(response: Response): Promise<string> {
  const fallback = `${response.status} ${response.statusText}`.trim();
  try {
    const body: unknown = await response.json();
    if (body && typeof body === 'object' && 'detail' in body) {
      const { detail } = body;
      if (typeof detail === 'string') return detail;
      // Validation errors (422) are a list of {loc, msg}.
      if (Array.isArray(detail)) {
        return detail
          .map((item: unknown) =>
            item && typeof item === 'object' && 'msg' in item ? String(item.msg) : String(item),
          )
          .join('; ');
      }
    }
  } catch {
    // Not JSON; the status line is the best we have.
  }
  return fallback;
}

export class ApiClient {
  private readonly baseUrl: string;
  private readonly getApiKey: () => string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.getApiKey = options.getApiKey ?? (() => '');
    // Bound so it is never called with the client as `this` (an "Illegal invocation").
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  private async request(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    const apiKey = this.getApiKey();
    if (apiKey) headers.set('X-API-Key', apiKey);

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, { ...init, headers });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      throw new ApiError(0, 'Cannot reach the agent server. Is it running?');
    }
    if (!response.ok) throw new ApiError(response.status, await errorMessage(response));
    return response;
  }

  private async getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
    const response = await this.request(path, signal ? { signal } : {});
    return (await response.json()) as T;
  }

  health(signal?: AbortSignal): Promise<Health> {
    return this.getJson<Health>('/health', signal);
  }

  async tools(signal?: AbortSignal): Promise<Tool[]> {
    return (await this.getJson<ToolsResponse>('/v1/tools', signal)).tools;
  }

  models(signal?: AbortSignal): Promise<ModelsResponse> {
    return this.getJson<ModelsResponse>('/v1/models', signal);
  }

  /** Upload a file into the workspace folder `folder` (e.g. `"uploads/"`). */
  async uploadFile(file: File, folder: string): Promise<WorkspaceFile> {
    const form = new FormData();
    form.append('file', file);
    form.append('path', folder);
    const response = await this.request('/v1/files', { method: 'POST', body: form });
    return (await response.json()) as WorkspaceFile;
  }

  /**
   * Download a workspace file as a Blob.
   *
   * Fetched rather than linked: a plain `<a href>` can't carry the
   * `X-API-Key` header a protected server requires.
   */
  async downloadFile(path: string): Promise<Blob> {
    const encoded = path.split('/').map(encodeURIComponent).join('/');
    const response = await this.request(`/v1/files/${encoded}`);
    return response.blob();
  }

  /**
   * Run the agent on `body`, yielding each event as it streams in.
   *
   * Aborting `signal` stops the run. The server then discards the
   * unfinished turn, so the conversation stays consistent.
   */
  async *chatStream(body: ChatRequest, signal: AbortSignal): AsyncGenerator<AgentEvent> {
    const response = await this.request('/v1/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal,
    });
    if (!response.body) throw new ApiError(response.status, 'The server sent an empty stream.');

    for await (const message of readSse(response.body)) {
      if (!AGENT_EVENT_TYPES.has(message.event as AgentEvent['type'])) continue; // Unknown: newer server.
      const data: unknown = JSON.parse(message.data);
      yield { type: message.event, data } as AgentEvent;
    }
  }
}
