/**
 * Wire types for the agent-runtime HTTP API.
 *
 * These mirror the backend's Pydantic schemas (`api/schemas.py`) and its
 * streaming events (`agent/events.py`) field for field. When the backend
 * contract changes, change it here, and the compiler will point at every
 * place in the UI that has to follow.
 */

/** JSON Schema for a tool's arguments, as the model is given it. */
export interface JsonSchemaProperty {
  type?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  anyOf?: JsonSchemaProperty[];
  minimum?: number;
  minLength?: number;
}

export interface ToolParameters {
  type: 'object';
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
}

/** `GET /v1/tools` item. */
export interface Tool {
  name: string;
  description: string;
  parameters: ToolParameters;
}

export interface ToolsResponse {
  tools: Tool[];
}

/** `GET /v1/models` item. */
export interface Model {
  id: string;
  label: string;
  description: string;
  input_usd_per_1m: number;
  output_usd_per_1m: number;
}

export interface ModelsResponse {
  default: string;
  models: Model[];
}

/** `GET /health`. */
export interface Health {
  status: string;
  app_name: string;
  environment: string;
  model: string;
  tools: string[];
  workspace: {
    read_only: boolean;
    path: string | null;
    /** Whether a request may choose another directory to work in (absent on older servers). */
    selectable?: boolean;
  };
  /** True when sessions are stored in a database and listed at `/v1/sessions`. */
  history?: boolean;
}

/** `GET /v1/directories` item: a folder on the server. */
export interface DirectoryEntry {
  name: string;
  /** Absolute path on the server. */
  path: string;
}

/** `GET /v1/directories`: the subfolders of `path`, or the top-level locations if it is null. */
export interface DirectoryListing {
  path: string | null;
  /** The folder above; null when `path` is a top-level location. */
  parent: string | null;
  directories: DirectoryEntry[];
  truncated: boolean;
}

/** `POST /v1/files` response, and an item of `GET /v1/files`. */
export interface WorkspaceFile {
  path: string;
  size: number;
  modified: string;
}

/** Body of `POST /v1/chat` and `POST /v1/chat/stream`. */
export interface ChatRequest {
  message: string;
  session_id?: string;
  model?: string;
  /** Absolute directory for the agent's tools; omit for the server's workspace. */
  workspace?: string;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  /** `null` when the model has no known price, which is not the same as free. */
  cost_usd: number | null;
}

// --- Sign-in (`/v1/auth`, when the server has a database) ----------------------

/** `GET /v1/auth/status`. */
export interface AuthStatus {
  enabled: boolean;
  /** True until the first (admin) account exists. */
  setup_required: boolean;
}

export interface User {
  id: string;
  username: string;
  display_name: string;
  is_admin: boolean;
  created_at: string;
  last_login_at: string | null;
}

/** `POST /v1/auth/login` and `/v1/auth/setup`. */
export interface LoginResponse {
  token: string;
  user: User;
}

// --- Stored sessions (`/v1/sessions`, when the server has a database) ----------

/** `GET /v1/sessions` item. */
export interface SessionSummary {
  id: string;
  title: string;
  model: string | null;
  /** Absolute folder the latest run worked in. */
  workspace: string | null;
  created_at: string;
  updated_at: string;
  run_count: number;
  usage: Usage;
}

export interface SessionsResponse {
  sessions: SessionSummary[];
}

export type RunStatus = 'running' | 'completed' | 'failed' | 'cancelled';

/** One stored run; `events` are what the stream sent (tokens merged per step). */
export interface StoredRun {
  id: string;
  status: RunStatus;
  user_message: string;
  model: string;
  workspace: string | null;
  answer: string | null;
  error: string | null;
  steps_used: number;
  tool_call_count: number;
  usage: Usage;
  started_at: string;
  finished_at: string | null;
  duration_s: number | null;
  events: { type: string; data: unknown; created_at: string }[];
}

/** `GET /v1/sessions/{id}`. */
export interface SessionDetail extends SessionSummary {
  runs: StoredRun[];
}

// --- Streaming events (`POST /v1/chat/stream`) -----------------------------------
// The SSE event name is the backend class name in snake_case; the data is
// the event's fields plus `session_id` and `model`, which the server adds.

interface EventBase {
  run_id: string;
  session_id: string;
  model: string;
}

export interface RunStartedEvent extends EventBase {
  max_steps: number;
}

export interface StepStartedEvent extends EventBase {
  step: number;
}

export interface ModelTokenEvent extends EventBase {
  step: number;
  text: string;
}

export interface ToolCallRequestedEvent extends EventBase {
  step: number;
  call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}

export interface ToolCallResultEvent extends EventBase {
  step: number;
  call_id: string;
  tool_name: string;
  content: string;
  is_error: boolean;
  duration_s: number;
  image_count: number;
}

export interface UsageUpdatedEvent extends EventBase {
  step: number;
  step_usage: Usage;
  run_usage: Usage;
}

export interface FinalAnswerEvent extends EventBase {
  step: number;
  content: string;
}

export interface RunFailedEvent extends EventBase {
  step: number;
  reason: string;
}

/** Every event the stream can carry, discriminated by its SSE event name. */
export type AgentEvent =
  | { type: 'run_started'; data: RunStartedEvent }
  | { type: 'step_started'; data: StepStartedEvent }
  | { type: 'model_token'; data: ModelTokenEvent }
  | { type: 'tool_call_requested'; data: ToolCallRequestedEvent }
  | { type: 'tool_call_result'; data: ToolCallResultEvent }
  | { type: 'usage_updated'; data: UsageUpdatedEvent }
  | { type: 'final_answer'; data: FinalAnswerEvent }
  | { type: 'run_failed'; data: RunFailedEvent };

export const AGENT_EVENT_TYPES: ReadonlySet<AgentEvent['type']> = new Set([
  'run_started',
  'step_started',
  'model_token',
  'tool_call_requested',
  'tool_call_result',
  'usage_updated',
  'final_answer',
  'run_failed',
]);
