import type { SessionDetail, StoredRun } from '../api/types';
import { turnsFromSession } from './history';
import { composeMessage, splitMessage } from './useChat';

const base = { run_id: 'run_1', session_id: 'sess_1', model: 'gpt-4o' };
const usage = { input_tokens: 10, output_tokens: 5, total_tokens: 15, cost_usd: 0.001 };

function storedRun(overrides: Partial<StoredRun>): StoredRun {
  return {
    id: 'run_1',
    status: 'completed',
    user_message: 'hi',
    model: 'gpt-4o',
    workspace: null,
    answer: null,
    error: null,
    steps_used: 1,
    tool_call_count: 0,
    usage,
    started_at: '2026-10-17T10:00:00Z',
    finished_at: null,
    duration_s: null,
    events: [],
    ...overrides,
  };
}

export function session(runs: StoredRun[]): SessionDetail {
  return {
    id: 'sess_1',
    title: 'Plan',
    model: 'gpt-4o',
    workspace: null,
    created_at: '2026-10-17T10:00:00Z',
    updated_at: '2026-10-17T10:01:00Z',
    run_count: runs.length,
    usage,
    runs,
  };
}

const ev = (type: string, data: Record<string, unknown>) => ({
  type,
  data: { ...base, ...data },
  created_at: '2026-10-17T10:00:00Z',
});

describe('turnsFromSession', () => {
  it('replays a run into the same turns the live stream produced', () => {
    const turns = turnsFromSession(
      session([
        storedRun({
          user_message: composeMessage('Summarise it', ['uploads/a.pdf']),
          events: [
            ev('run_started', { max_steps: 8 }),
            ev('tool_call_requested', {
              step: 1,
              call_id: 'c1',
              tool_name: 'read_file',
              arguments: { path: 'uploads/a.pdf' },
            }),
            ev('tool_call_result', {
              step: 1,
              call_id: 'c1',
              tool_name: 'read_file',
              content: 'text',
              is_error: false,
              duration_s: 0.2,
              image_count: 0,
            }),
            ev('model_token', { step: 2, text: 'It says hi.' }),
            ev('usage_updated', { step: 2, step_usage: usage, run_usage: usage }),
            ev('final_answer', { step: 2, content: 'It says hi.' }),
          ],
        }),
      ]),
    );

    expect(turns[0]).toMatchObject({
      role: 'user',
      text: 'Summarise it',
      attachments: ['uploads/a.pdf'],
    });
    expect(turns[1]).toMatchObject({
      role: 'assistant',
      status: 'done',
      usage,
      parts: [
        { kind: 'tool', call: { toolName: 'read_file', status: 'ok', content: 'text' } },
        { kind: 'text', text: 'It says hi.' },
      ],
    });
  });

  it('closes runs that never finished', () => {
    const turns = turnsFromSession(
      session([
        storedRun({
          id: 'r1',
          status: 'cancelled',
          events: [
            ev('tool_call_requested', { step: 1, call_id: 'c1', tool_name: 'x', arguments: {} }),
          ],
        }),
        storedRun({ id: 'r2', status: 'running', events: [] }),
      ]),
    );

    expect(turns[1]).toMatchObject({
      status: 'stopped',
      parts: [{ kind: 'tool', call: { status: 'cancelled' } }],
    });
    expect(turns[3]).toMatchObject({ status: 'failed', error: 'This run did not finish.' });
  });
});

describe('splitMessage', () => {
  it('undoes composeMessage', () => {
    expect(splitMessage(composeMessage('a\nb', ['x.txt', 'y z.pdf']))).toEqual({
      text: 'a\nb',
      attachments: ['x.txt', 'y z.pdf'],
    });
    expect(splitMessage('plain')).toEqual({ text: 'plain', attachments: [] });
  });
});
