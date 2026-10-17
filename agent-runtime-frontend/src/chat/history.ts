/**
 * Rebuild a stored conversation's turns by replaying its recorded events
 * through the same reducer that rendered them live, so a reopened session
 * looks exactly like it did while it streamed.
 */

import { AGENT_EVENT_TYPES, type AgentEvent, type SessionDetail } from '../api/types';
import { chatReducer, initialChatState, type ChatState, type Turn } from './chatReducer';
import { splitMessage } from './useChat';

export function turnsFromSession(session: SessionDetail): Turn[] {
  let state: ChatState = initialChatState;
  for (const run of session.runs) {
    const { text, attachments } = splitMessage(run.user_message);
    state = chatReducer(state, {
      type: 'send',
      user: { id: `${run.id}:user`, role: 'user', text, attachments },
      assistantId: `${run.id}:assistant`,
    });
    for (const { type, data } of run.events) {
      if (!AGENT_EVENT_TYPES.has(type as AgentEvent['type'])) continue;
      state = chatReducer(state, { type: 'event', event: { type, data } as AgentEvent });
    }
    // A run with no terminal event was abandoned (client left) or cut short
    // (server stopped): close it the way the live UI would have.
    if (run.status === 'cancelled') {
      state = chatReducer(state, { type: 'stopped' });
    } else if (state.busy) {
      state = chatReducer(state, {
        type: 'failed',
        message: run.error ?? 'This run did not finish.',
      });
    }
  }
  return state.turns;
}
