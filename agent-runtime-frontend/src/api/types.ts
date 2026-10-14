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
  workspace: { read_only: boolean; path: string | null };
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
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  /** `null` when the model has no known price, which is not the same as free. */
  cost_usd: number | null;
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
