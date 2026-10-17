/**
 * The chat controller: sends messages, streams the agent's run into the
 * reducer, and supports stopping a run or starting a new conversation.
 */

import { useCallback, useEffect, useReducer, useRef } from 'react';

import { ApiError, type ApiClient } from '../api/client';
import {
  chatReducer,
  initialChatState,
  type ChatAction,
  type ChatState,
  type Turn,
} from './chatReducer';

export interface SendOptions {
  /** Model id, or undefined for the server's default. */
  model?: string | undefined;
  /** Workspace paths of files attached to this message. */
  attachments?: string[];
}

export interface Chat {
  state: ChatState;
  send: (text: string, options?: SendOptions) => Promise<void>;
  stop: () => void;
  reset: () => void;
  /** Replace the conversation with a stored one; the next message continues it. */
  load: (sessionId: string, turns: Turn[]) => void;
}

const ATTACHMENTS_HEADING = '\n\nAttached files (in the workspace):\n';

/** Tell the agent which workspace files the user attached. */
export function composeMessage(text: string, attachments: string[]): string {
  if (attachments.length === 0) return text;
  const list = attachments.map((path) => `- ${path}`).join('\n');
  return `${text}${ATTACHMENTS_HEADING}${list}`;
}

/** Undo `composeMessage`: the text the user typed, and the files they attached. */
export function splitMessage(message: string): { text: string; attachments: string[] } {
  const at = message.lastIndexOf(ATTACHMENTS_HEADING);
  if (at === -1) return { text: message, attachments: [] };
  const attachments = message
    .slice(at + ATTACHMENTS_HEADING.length)
    .split('\n')
    .map((line) => line.replace(/^- /, ''))
    .filter(Boolean);
  return { text: message.slice(0, at), attachments };
}

function newId(): string {
  return crypto.randomUUID();
}

export function useChat(client: ApiClient): Chat {
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const abortRef = useRef<AbortController | null>(null);
  // Bumped by `reset`. A run started before a reset may still deliver events
  // or its abort error afterwards; its generation no longer matches, so they
  // are dropped instead of landing on the new conversation.
  const generationRef = useRef(0);
  // The session id is read inside `send` without re-creating it on every
  // state change. Synced after render, as refs must not be written during it.
  const sessionIdRef = useRef(state.sessionId);
  useEffect(() => {
    sessionIdRef.current = state.sessionId;
  }, [state.sessionId]);

  // Never leave a run streaming into an unmounted component.
  useEffect(() => () => abortRef.current?.abort(), []);

  const send = useCallback(
    async (text: string, options: SendOptions = {}) => {
      const message = text.trim();
      // The controller doubles as a synchronous in-flight flag: state.busy only
      // updates after a render, so a fast double submit would slip past it.
      if (!message || abortRef.current) return;

      const attachments = options.attachments ?? [];
      const controller = new AbortController();
      abortRef.current = controller;
      const generation = generationRef.current;
      const emit = (action: ChatAction) => {
        if (generationRef.current === generation) dispatch(action);
      };
      emit({
        type: 'send',
        user: { id: newId(), role: 'user', text: message, attachments },
        assistantId: newId(),
      });

      try {
        const stream = client.chatStream(
          {
            message: composeMessage(message, attachments),
            ...(sessionIdRef.current ? { session_id: sessionIdRef.current } : {}),
            ...(options.model ? { model: options.model } : {}),
          },
          controller.signal,
        );
        for await (const event of stream) emit({ type: 'event', event });
        emit({ type: 'streamEnded' });
      } catch (error) {
        if (controller.signal.aborted) {
          emit({ type: 'stopped' });
        } else {
          const description =
            error instanceof ApiError ? error.message : 'Something went wrong while streaming.';
          if (!(error instanceof ApiError)) console.error(error);
          emit({ type: 'failed', message: description });
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
      }
    },
    [client],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    generationRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    sessionIdRef.current = null;
    dispatch({ type: 'reset' });
  }, []);

  const load = useCallback((sessionId: string, turns: Turn[]) => {
    generationRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    sessionIdRef.current = sessionId;
    dispatch({ type: 'load', sessionId, turns });
  }, []);

  return { state, send, stop, reset, load };
}
