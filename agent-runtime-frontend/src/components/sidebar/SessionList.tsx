/**
 * Stored conversations: open one to read or continue it, rename it, or
 * delete it with everything recorded about it. Shown only when the server
 * keeps sessions in a database.
 */

import { useState, type KeyboardEvent } from 'react';

import { ApiError } from '../../api/client';
import type { SessionSummary } from '../../api/types';
import type { Resource } from '../../hooks/useResource';
import { formatCost, formatRelativeTime } from '../../lib/format';
import { Icon } from '../Icon';
import styles from './SessionList.module.css';

interface SessionListProps {
  sessions: Resource<SessionSummary[]>;
  /** The conversation on screen, highlighted in the list. */
  activeId: string | null;
  /** True while a run is streaming: switching conversations would abandon it. */
  busy: boolean;
  onOpen: (id: string) => Promise<void>;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

type Mode = { kind: 'idle' } | { kind: 'rename'; draft: string } | { kind: 'confirmDelete' };

function describe(session: SessionSummary): string {
  const runs = `${session.run_count} ${session.run_count === 1 ? 'message' : 'messages'}`;
  const cost = session.usage.cost_usd ? ` · ${formatCost(session.usage.cost_usd)}` : '';
  return `${formatRelativeTime(session.updated_at)} · ${runs}${cost}`;
}

function SessionItem({
  session,
  active,
  busy,
  onOpen,
  onRename,
  onDelete,
  onError,
}: {
  session: SessionSummary;
  active: boolean;
  busy: boolean;
  onOpen: () => Promise<void>;
  onRename: (title: string) => Promise<void>;
  onDelete: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [mode, setMode] = useState<Mode>({ kind: 'idle' });
  const title = session.title || 'Untitled conversation';

  const attempt = async (action: () => Promise<void>) => {
    try {
      await action();
      setMode({ kind: 'idle' });
    } catch (reason) {
      onError(reason instanceof ApiError ? reason.message : 'Something went wrong.');
    }
  };

  if (mode.kind === 'rename') {
    const save = () => {
      const next = mode.draft.trim();
      if (!next || next === session.title) {
        setMode({ kind: 'idle' });
        return;
      }
      void attempt(() => onRename(next));
    };
    const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key === 'Enter') save();
      if (event.key === 'Escape') {
        event.stopPropagation(); // Keep the sidebar drawer open.
        setMode({ kind: 'idle' });
      }
    };
    return (
      <li className={styles.item}>
        <input
          className={styles.renameInput}
          value={mode.draft}
          aria-label="Conversation title"
          maxLength={200}
          autoFocus
          onChange={(event) => {
            setMode({ kind: 'rename', draft: event.target.value });
          }}
          onKeyDown={onKeyDown}
          onBlur={save}
        />
      </li>
    );
  }

  return (
    <li className={active ? `${styles.item ?? ''} ${styles.active ?? ''}` : styles.item}>
      <button
        type="button"
        className={styles.open}
        disabled={busy}
        aria-current={active ? 'true' : undefined}
        title={title}
        onClick={() => void attempt(onOpen)}
      >
        <span className={styles.title}>{title}</span>
        <span className={styles.meta}>{describe(session)}</span>
      </button>

      {mode.kind === 'confirmDelete' ? (
        <span className={styles.confirm}>
          <button type="button" className={styles.danger} onClick={() => void attempt(onDelete)}>
            Delete
          </button>
          <button
            type="button"
            className={styles.iconButton}
            onClick={() => {
              setMode({ kind: 'idle' });
            }}
          >
            <Icon name="x" size={14} label="Keep conversation" />
          </button>
        </span>
      ) : (
        <span className={styles.actions}>
          <button
            type="button"
            className={styles.iconButton}
            onClick={() => {
              setMode({ kind: 'rename', draft: session.title });
            }}
          >
            <Icon name="pencil" size={14} label={`Rename “${title}”`} />
          </button>
          <button
            type="button"
            className={styles.iconButton}
            disabled={busy && active}
            onClick={() => {
              setMode({ kind: 'confirmDelete' });
            }}
          >
            <Icon name="trash" size={14} label={`Delete “${title}”`} />
          </button>
        </span>
      )}
    </li>
  );
}

export function SessionList({
  sessions,
  activeId,
  busy,
  onOpen,
  onRename,
  onDelete,
}: SessionListProps) {
  const [error, setError] = useState('');
  const items = sessions.data ?? [];

  return (
    <>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {sessions.error && !sessions.data ? (
        <p className={styles.error}>{sessions.error.message}</p>
      ) : !sessions.data ? (
        <p className={styles.empty}>Loading…</p>
      ) : items.length === 0 ? (
        <p className={styles.empty}>No conversations yet. They are saved as you chat.</p>
      ) : (
        <ul className={styles.list}>
          {items.map((session) => (
            <SessionItem
              key={session.id}
              session={session}
              active={session.id === activeId}
              busy={busy}
              onOpen={() => {
                setError('');
                return onOpen(session.id);
              }}
              onRename={(title) => onRename(session.id, title)}
              onDelete={() => onDelete(session.id)}
              onError={setError}
            />
          ))}
        </ul>
      )}
    </>
  );
}
