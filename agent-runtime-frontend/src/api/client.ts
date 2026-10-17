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
  type AuthStatus,
  type ChatRequest,
  type DirectoryListing,
  type Health,
  type LoginResponse,
  type McpImportResult,
  type McpServer,
  type McpServerConfig,
  type McpServersResponse,
  type McpTestResult,
  type ModelsResponse,
  type SessionDetail,
  type SessionsResponse,
  type SessionSummary,
  type Tool,
  type ToolsResponse,
  type User,
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
  /** Returns the signed-in user's token, sent as `Authorization: Bearer`. */
  getToken?: () => string;
  /** Called when a request made with a token is refused (expired or revoked). */
  onUnauthorized?: () => void;
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
  private readonly getToken: () => string;
  private readonly onUnauthorized: () => void;
  private readonly fetchImpl: typeof fetch;
  /** Directory the agent works in for chats and file transfers; empty = the server's own. */
  private workspaceDir = '';

  constructor(options: ApiClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.getApiKey = options.getApiKey ?? (() => '');
    this.getToken = options.getToken ?? (() => '');
    this.onUnauthorized = options.onUnauthorized ?? (() => undefined);
    // Bound so it is never called with the client as `this` (an "Illegal invocation").
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  private async request(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    const apiKey = this.getApiKey();
    if (apiKey) headers.set('X-API-Key', apiKey);
    const token = this.getToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, { ...init, headers });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      throw new ApiError(0, 'Cannot reach the agent server. Is it running?');
    }
    if (!response.ok) {
      if (response.status === 401 && token) this.onUnauthorized();
      throw new ApiError(response.status, await errorMessage(response));
    }
    return response;
  }

  private async postJson<T>(path: string, body: unknown): Promise<T> {
    return this.sendJson<T>('POST', path, body);
  }

  private async sendJson<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await this.request(path, {
      method,
      ...(body === undefined
        ? {}
        : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    });
    return (await response.json()) as T;
  }

  /** Choose the directory every later chat, upload and download works in ('' = server default). */
  setWorkspace(path: string): void {
    this.workspaceDir = path;
  }

  get workspace(): string {
    return this.workspaceDir;
  }

  /** `?workspace=` for the files API, or nothing when using the server's workspace. */
  private workspaceQuery(): string {
    return this.workspaceDir ? `?${new URLSearchParams({ workspace: this.workspaceDir })}` : '';
  }

  private async getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
    const response = await this.request(path, signal ? { signal } : {});
    return (await response.json()) as T;
  }

  authStatus(signal?: AbortSignal): Promise<AuthStatus> {
    return this.getJson<AuthStatus>('/v1/auth/status', signal);
  }

  login(username: string, password: string): Promise<LoginResponse> {
    return this.postJson<LoginResponse>('/v1/auth/login', { username, password });
  }

  /** Create the first (admin) account; only allowed while there is none. */
  setup(account: { username: string; password: string; display_name: string }) {
    return this.postJson<LoginResponse>('/v1/auth/setup', account);
  }

  me(signal?: AbortSignal): Promise<User> {
    return this.getJson<User>('/v1/auth/me', signal);
  }

  async logout(): Promise<void> {
    await this.request('/v1/auth/logout', { method: 'POST' });
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

  async sessions(signal?: AbortSignal): Promise<SessionSummary[]> {
    return (await this.getJson<SessionsResponse>('/v1/sessions', signal)).sessions;
  }

  session(id: string, signal?: AbortSignal): Promise<SessionDetail> {
    return this.getJson<SessionDetail>(`/v1/sessions/${encodeURIComponent(id)}`, signal);
  }

  async renameSession(id: string, title: string): Promise<SessionSummary> {
    const response = await this.request(`/v1/sessions/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    return (await response.json()) as SessionSummary;
  }

  async deleteSession(id: string): Promise<void> {
    await this.request(`/v1/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }

  // --- MCP servers ---------------------------------------------------------------

  mcpServers(signal?: AbortSignal): Promise<McpServersResponse> {
    return this.getJson<McpServersResponse>('/v1/mcp/servers', signal);
  }

  createMcpServer(name: string, config: McpServerConfig): Promise<McpServer> {
    return this.postJson<McpServer>('/v1/mcp/servers', { name, config });
  }

  updateMcpServer(name: string, config: McpServerConfig): Promise<McpServer> {
    return this.sendJson<McpServer>('PUT', `/v1/mcp/servers/${encodeURIComponent(name)}`, config);
  }

  setMcpServerEnabled(name: string, enabled: boolean): Promise<McpServer> {
    return this.sendJson<McpServer>('PATCH', `/v1/mcp/servers/${encodeURIComponent(name)}`, {
      enabled,
    });
  }

  reconnectMcpServer(name: string): Promise<McpServer> {
    return this.postJson<McpServer>(`/v1/mcp/servers/${encodeURIComponent(name)}/reconnect`, {});
  }

  async deleteMcpServer(name: string): Promise<void> {
    await this.request(`/v1/mcp/servers/${encodeURIComponent(name)}`, { method: 'DELETE' });
  }

  /** Try a config without saving it; `name` fills masked secrets from a stored server. */
  testMcpServer(config: McpServerConfig, name?: string): Promise<McpTestResult> {
    return this.postJson<McpTestResult>('/v1/mcp/test', { config, ...(name ? { name } : {}) });
  }

  importMcpServers(json: string, overwrite = false): Promise<McpImportResult> {
    return this.postJson<McpImportResult>('/v1/mcp/import', { json, overwrite });
  }

  /** The subfolders of server directory `path`, or the top-level locations if omitted. */
  directories(path?: string, signal?: AbortSignal): Promise<DirectoryListing> {
    const query = path ? `?${new URLSearchParams({ path })}` : '';
    return this.getJson<DirectoryListing>(`/v1/directories${query}`, signal);
  }

  /** Upload a file into the workspace folder `folder` (e.g. `"uploads/"`). */
  async uploadFile(file: File, folder: string): Promise<WorkspaceFile> {
    const form = new FormData();
    form.append('file', file);
    form.append('path', folder);
    const response = await this.request(`/v1/files${this.workspaceQuery()}`, {
      method: 'POST',
      body: form,
    });
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
    const response = await this.request(`/v1/files/${encoded}${this.workspaceQuery()}`);
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
      body: JSON.stringify(
        this.workspaceDir && !body.workspace ? { ...body, workspace: this.workspaceDir } : body,
      ),
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
