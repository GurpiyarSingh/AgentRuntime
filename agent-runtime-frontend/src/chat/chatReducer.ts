/**
 * Conversation state, as a pure reducer over user actions and stream events.
 *
 * Keeping this free of React and I/O means every rule about how events
 * become what the user sees (token merging, tool call pairing, terminal
 * states) is unit-tested directly, and `useChat` only has to wire it up.
 */

import type { AgentEvent, Usage } from '../api/types';

export type ToolCallStatus = 'running' | 'ok' | 'error' | 'cancelled';

export interface ToolCall {
  callId: string;
  toolName: string;
  arguments: Record<string, unknown>;
  status: ToolCallStatus;
  /** The observation the model received; set once the call finishes. */
  content?: string;
  durationS?: number;
  imageCount: number;
}

/** An assistant turn is text and tool calls interleaved, in the order they happened. */
export type AssistantPart = { kind: 'text'; text: string } | { kind: 'tool'; call: ToolCall };

export interface UserTurn {
  id: string;
  role: 'user';
  text: string;
  /** Workspace paths of files attached to this message. */
  attachments: string[];
}

export type AssistantStatus = 'streaming' | 'done' | 'failed' | 'stopped';

export interface AssistantTurn {
  id: string;
  role: 'assistant';
  parts: AssistantPart[];
  status: AssistantStatus;
  error?: string;
  usage?: Usage;
  model?: string;
}

export type Turn = UserTurn | AssistantTurn;

export interface ChatState {
  turns: Turn[];
  /** Server-side conversation id; `null` until the first run starts. */
  sessionId: string | null;
  /** True while a run is in flight; the composer is locked meanwhile. */
  busy: boolean;
}

export type ChatAction =
  | { type: 'send'; user: UserTurn; assistantId: string }
  | { type: 'event'; event: AgentEvent }
  | { type: 'failed'; message: string }
  | { type: 'stopped' }
  | { type: 'streamEnded' }
  | { type: 'reset' }
  /** Show a stored conversation, to read or to continue. */
  | { type: 'load'; sessionId: string; turns: Turn[] };

export const initialChatState: ChatState = { turns: [], sessionId: null, busy: false };

/** Apply `update` to the in-flight assistant turn (always the last turn). */
function updateCurrent(state: ChatState, update: (turn: AssistantTurn) => AssistantTurn): Turn[] {
  const last = state.turns.at(-1);
  if (last?.role !== 'assistant') return state.turns;
  return [...state.turns.slice(0, -1), update(last)];
}

function appendText(parts: AssistantPart[], text: string): AssistantPart[] {
  const last = parts.at(-1);
  if (last?.kind === 'text')
    return [...parts.slice(0, -1), { kind: 'text', text: last.text + text }];
  return [...parts, { kind: 'text', text }];
}

/** Set the turn's closing text: the final answer is authoritative over streamed tokens. */
function setFinalText(parts: AssistantPart[], text: string): AssistantPart[] {
  const last = parts.at(-1);
  if (last?.kind === 'text') return [...parts.slice(0, -1), { kind: 'text', text }];
  return text ? [...parts, { kind: 'text', text }] : parts;
}

function cancelRunningTools(parts: AssistantPart[]): AssistantPart[] {
  return parts.map((part) =>
    part.kind === 'tool' && part.call.status === 'running'
      ? { kind: 'tool', call: { ...part.call, status: 'cancelled' } }
      : part,
  );
}

function applyEvent(state: ChatState, event: AgentEvent): ChatState {
  switch (event.type) {
    case 'run_started':
      return {
        ...state,
        sessionId: event.data.session_id,
        turns: updateCurrent(state, (turn) => ({ ...turn, model: event.data.model })),
      };
    case 'model_token':
      return {
        ...state,
        turns: updateCurrent(state, (turn) => ({
          ...turn,
          parts: appendText(turn.parts, event.data.text),
        })),
      };
    case 'tool_call_requested':
      return {
        ...state,
        turns: updateCurrent(state, (turn) => ({
          ...turn,
          parts: [
            ...turn.parts,
            {
              kind: 'tool',
              call: {
                callId: event.data.call_id,
                toolName: event.data.tool_name,
                arguments: event.data.arguments,
                status: 'running',
                imageCount: 0,
              },
            },
          ],
        })),
      };
    case 'tool_call_result':
      return {
        ...state,
        turns: updateCurrent(state, (turn) => ({
          ...turn,
          parts: turn.parts.map((part) =>
            part.kind === 'tool' && part.call.callId === event.data.call_id
              ? {
                  kind: 'tool',
                  call: {
                    ...part.call,
                    status: event.data.is_error ? 'error' : 'ok',
                    content: event.data.content,
                    durationS: event.data.duration_s,
                    imageCount: event.data.image_count,
                  },
                }
              : part,
          ),
        })),
      };
    case 'usage_updated':
      return {
        ...state,
        turns: updateCurrent(state, (turn) => ({ ...turn, usage: event.data.run_usage })),
      };
    case 'final_answer':
      return {
        ...state,
        busy: false,
        turns: updateCurrent(state, (turn) => ({
          ...turn,
          status: 'done',
          parts: setFinalText(turn.parts, event.data.content),
        })),
      };
    case 'run_failed':
      return {
        ...state,
        busy: false,
        turns: updateCurrent(state, (turn) => ({
          ...turn,
          status: 'failed',
          error: event.data.reason,
          parts: cancelRunningTools(turn.parts),
        })),
      };
    case 'step_started':
      return state;
  }
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'send':
      return {
        ...state,
        busy: true,
        turns: [
          ...state.turns,
          action.user,
          { id: action.assistantId, role: 'assistant', parts: [], status: 'streaming' },
        ],
      };
    case 'event':
      return applyEvent(state, action.event);
    case 'failed':
      return {
        ...state,
        busy: false,
        turns: updateCurrent(state, (turn) => ({
          ...turn,
          status: 'failed',
          error: action.message,
          parts: cancelRunningTools(turn.parts),
        })),
      };
    case 'stopped':
      return {
        ...state,
        busy: false,
        turns: updateCurrent(state, (turn) =>
          turn.status === 'streaming'
            ? { ...turn, status: 'stopped', parts: cancelRunningTools(turn.parts) }
            : turn,
        ),
      };
    case 'streamEnded':
      // The connection closed without a final answer or failure event.
      return {
        ...state,
        busy: false,
        turns: updateCurrent(state, (turn) =>
          turn.status === 'streaming'
            ? {
                ...turn,
                status: 'failed',
                error: 'The connection closed before the agent finished.',
                parts: cancelRunningTools(turn.parts),
              }
            : turn,
        ),
      };
    case 'reset':
      return initialChatState;
    case 'load':
      return { turns: action.turns, sessionId: action.sessionId, busy: false };
  }
}
