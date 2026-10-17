/** The main column: header controls, the conversation, and the message box. */

import { useState } from 'react';

import type { Health, ModelsResponse } from '../../api/types';
import type { Chat } from '../../chat/useChat';
import type { Attachments } from '../../chat/useAttachments';
import type { Resource } from '../../hooks/useResource';
import { formatCost } from '../../lib/format';
import { Icon } from '../Icon';
import styles from './ChatPanel.module.css';
import { Composer } from './Composer';
import { MessageList } from './MessageList';

interface ChatPanelProps {
  chat: Chat;
  attachments: Attachments;
  health: Resource<Health>;
  models: Resource<ModelsResponse>;
  model: string;
  onModelChange: (model: string) => void;
  /** The open conversation's stored title, if it has one. */
  title?: string | undefined;
  onOpenSidebar: () => void;
}

const ANNOUNCEMENTS: Partial<Record<string, string>> = {
  done: 'The agent replied.',
  failed: 'The agent run failed.',
  stopped: 'Stopped.',
};

/**
 * Text for a screen-reader live region. Streamed tokens are not read one by
 * one; instead the region goes empty during a run and announces its outcome.
 */
function completionAnnouncement(chat: Chat): string {
  const last = chat.state.turns.at(-1);
  return last?.role === 'assistant' ? (ANNOUNCEMENTS[last.status] ?? '') : '';
}

export function ChatPanel({
  chat,
  attachments,
  health,
  models,
  model,
  onModelChange,
  title,
  onOpenSidebar,
}: ChatPanelProps) {
  const [draft, setDraft] = useState('');
  const announcement = completionAnnouncement(chat);
  const offline = health.error?.isNetworkError === true;

  const send = () => {
    void chat.send(draft, { model, attachments: attachments.readyPaths });
    setDraft('');
    attachments.clear();
  };

  return (
    <main className={styles.panel}>
      <header className={styles.header}>
        <button
          type="button"
          className={styles.menu}
          onClick={onOpenSidebar}
          aria-controls="sidebar"
        >
          <Icon name="menu" label="Show tools" />
        </button>
        <div className={styles.heading}>
          <h2 className={styles.title}>
            {chat.state.turns.length === 0 ? 'New conversation' : title || 'Conversation'}
          </h2>
          {chat.state.busy && (
            <span className={styles.working}>
              <span className={styles.workingDot} />
              Working
            </span>
          )}
        </div>

        <label className={styles.modelLabel}>
          <span className="sr-only">Model</span>
          <Icon name="cpu" size={15} className={styles.modelIcon} />
          <select
            className={styles.model}
            value={model}
            disabled={!models.data || chat.state.busy}
            onChange={(event) => {
              onModelChange(event.target.value);
            }}
          >
            {models.data ? (
              models.data.models.map((option) => (
                <option
                  key={option.id}
                  value={option.id}
                  title={`${option.description} ${formatCost(option.input_usd_per_1m)} in / ${formatCost(option.output_usd_per_1m)} out per 1M tokens`}
                >
                  {option.label}
                </option>
              ))
            ) : (
              <option value={model}>{model || 'Loading models…'}</option>
            )}
          </select>
          <Icon name="chevronDown" size={14} className={styles.modelChevron} />
        </label>

        <button
          type="button"
          className={styles.newChat}
          aria-label="New chat"
          onClick={() => {
            chat.reset();
            attachments.clear();
          }}
          disabled={chat.state.turns.length === 0}
        >
          <Icon name="plus" size={16} />
          <span className={styles.newChatText}>New chat</span>
        </button>
      </header>

      {health.error && (
        <div className={styles.banner} role="alert">
          <Icon name="alert" size={16} />
          <span>
            {offline
              ? 'Cannot reach the agent server. Start it with “agent-runtime serve”.'
              : health.error.message}
          </span>
          <button type="button" className={styles.retry} onClick={health.reload}>
            Retry
          </button>
        </div>
      )}

      <div className={styles.backdrop} aria-hidden="true" />
      <MessageList turns={chat.state.turns} onPickSuggestion={setDraft} />

      <Composer
        value={draft}
        onChange={setDraft}
        onSend={send}
        onStop={chat.stop}
        busy={chat.state.busy}
        attachments={attachments}
        disabled={offline}
      />

      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>
    </main>
  );
}
