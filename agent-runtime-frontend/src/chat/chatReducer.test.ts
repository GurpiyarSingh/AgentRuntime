import type { AgentEvent } from '../api/types';
import {
  chatReducer,
  initialChatState,
  type AssistantTurn,
  type ChatAction,
  type ChatState,
} from './chatReducer';

const base = { run_id: 'run_1', session_id: 'sess_1', model: 'gpt-4o' };

function run(...actions: ChatAction[]): ChatState {
  return actions.reduce(chatReducer, initialChatState);
}

function send(text = 'hi'): ChatAction {
  return {
    type: 'send',
    user: { id: 'u1', role: 'user', text, attachments: [] },
    assistantId: 'a1',
  };
}

function event(e: AgentEvent): ChatAction {
  return { type: 'event', event: e };
}

const token = (text: string) => event({ type: 'model_token', data: { ...base, step: 1, text } });
const requested = (callId: string, toolName = 'read_file') =>
  event({
    type: 'tool_call_requested',
    data: { ...base, step: 1, call_id: callId, tool_name: toolName, arguments: { path: 'a.txt' } },
  });
const result = (callId: string, isError = false) =>
  event({
    type: 'tool_call_result',
    data: {
      ...base,
      step: 1,
      call_id: callId,
      tool_name: 'read_file',
      content: isError ? 'File not found' : 'contents',
      is_error: isError,
      duration_s: 0.25,
      image_count: 0,
    },
  });
const final = (content: string) =>
  event({ type: 'final_answer', data: { ...base, step: 2, content } });

function assistant(state: ChatState): AssistantTurn {
  const last = state.turns.at(-1);
  if (last?.role !== 'assistant') throw new Error('expected an assistant turn');
  return last;
}

describe('chatReducer', () => {
  it('adds the user turn and a streaming assistant turn, and locks input', () => {
    const state = run(send('hello'));
    expect(state.busy).toBe(true);
    expect(state.turns.map((t) => t.role)).toEqual(['user', 'assistant']);
    expect(assistant(state).status).toBe('streaming');
  });

  it('records the session id when the run starts', () => {
    const state = run(send(), event({ type: 'run_started', data: { ...base, max_steps: 8 } }));
    expect(state.sessionId).toBe('sess_1');
    expect(assistant(state).model).toBe('gpt-4o');
  });

  it('merges consecutive tokens into one text part', () => {
    const state = run(send(), token('Hel'), token('lo'));
    expect(assistant(state).parts).toEqual([{ kind: 'text', text: 'Hello' }]);
  });

  it('keeps text and tool calls in the order they happened', () => {
    const state = run(send(), token('Let me look.'), requested('c1'), result('c1'), token('Done'));
    expect(assistant(state).parts.map((p) => p.kind)).toEqual(['text', 'tool', 'text']);
  });

  it('pairs each result with its request by call id', () => {
    const state = run(send(), requested('c1'), requested('c2'), result('c2', true), result('c1'));
    const calls = assistant(state).parts.flatMap((p) => (p.kind === 'tool' ? [p.call] : []));
    expect(calls.map((c) => [c.callId, c.status])).toEqual([
      ['c1', 'ok'],
      ['c2', 'error'],
    ]);
    expect(calls[1]?.content).toBe('File not found');
    expect(calls[0]?.durationS).toBe(0.25);
  });

  it('treats the final answer as authoritative over streamed tokens', () => {
    const streamed = run(send(), token('Partial'), final('Complete answer'));
    expect(assistant(streamed).parts).toEqual([{ kind: 'text', text: 'Complete answer' }]);
    expect(assistant(streamed).status).toBe('done');
    expect(streamed.busy).toBe(false);

    // Without token streaming, the answer arrives only in final_answer.
    const unstreamed = run(send(), requested('c1'), result('c1'), final('Answer'));
    expect(assistant(unstreamed).parts.at(-1)).toEqual({ kind: 'text', text: 'Answer' });
  });

  it('keeps the latest run usage', () => {
    const usage = { input_tokens: 10, output_tokens: 5, total_tokens: 15, cost_usd: 0.001 };
    const state = run(
      send(),
      event({
        type: 'usage_updated',
        data: { ...base, step: 1, step_usage: usage, run_usage: usage },
      }),
    );
    expect(assistant(state).usage).toEqual(usage);
  });

  it('marks a failed run and cancels tools still running', () => {
    const state = run(
      send(),
      requested('c1'),
      event({ type: 'run_failed', data: { ...base, step: 1, reason: 'Budget exceeded' } }),
    );
    expect(assistant(state).status).toBe('failed');
    expect(assistant(state).error).toBe('Budget exceeded');
    const part = assistant(state).parts[0];
    expect(part?.kind === 'tool' && part.call.status).toBe('cancelled');
    expect(state.busy).toBe(false);
  });

  it('records request-level failures', () => {
    const state = run(send(), { type: 'failed', message: 'Unknown model' });
    expect(assistant(state).status).toBe('failed');
    expect(assistant(state).error).toBe('Unknown model');
  });

  it('marks a stopped run without touching a finished one', () => {
    expect(assistant(run(send(), token('Hal'), { type: 'stopped' })).status).toBe('stopped');
    expect(assistant(run(send(), final('ok'), { type: 'stopped' })).status).toBe('done');
  });

  it('fails a run whose stream ended without a terminal event', () => {
    const state = run(send(), token('Hal'), { type: 'streamEnded' });
    expect(assistant(state).status).toBe('failed');
    expect(assistant(state).error).toMatch(/connection closed/);
    expect(assistant(run(send(), final('ok'), { type: 'streamEnded' })).status).toBe('done');
  });

  it('resets to an empty conversation with no session', () => {
    const state = run(
      send(),
      event({ type: 'run_started', data: { ...base, max_steps: 8 } }),
      final('ok'),
      { type: 'reset' },
    );
    expect(state).toEqual(initialChatState);
  });
});
