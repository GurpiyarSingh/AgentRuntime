/** A single turn in the conversation: the user's message or the agent's reply. */

import type { AssistantTurn, UserTurn } from '../../chat/chatReducer';
import { formatUsage } from '../../lib/format';
import { Icon } from '../Icon';
import { Markdown } from './Markdown';
import styles from './Message.module.css';
import { ToolCallCard } from './ToolCallCard';

export function UserMessage({ turn }: { turn: UserTurn }) {
  return (
    <article className={styles.user} aria-label="You">
      <div className={styles.userBubble}>
        <p className={styles.userText}>{turn.text}</p>
        {turn.attachments.length > 0 && (
          <ul className={styles.attachments} aria-label="Attached files">
            {turn.attachments.map((path) => (
              <li key={path} className={styles.attachment}>
                <Icon name="paperclip" size={13} />
                {path}
              </li>
            ))}
          </ul>
        )}
      </div>
    </article>
  );
}

function Thinking() {
  return (
    <span className={styles.thinking} role="status">
      <span />
      <span />
      <span />
      <span className="sr-only">The agent is working</span>
    </span>
  );
}

export function AssistantMessage({ turn }: { turn: AssistantTurn }) {
  const streaming = turn.status === 'streaming';
  // While streaming, show the dots until the first token or tool call, and
  // again after a tool call while the model decides what to do next.
  const showThinking = streaming && turn.parts.at(-1)?.kind !== 'text';

  return (
    <article className={styles.assistant} aria-label="Agent" aria-busy={streaming}>
      <span className={styles.avatar} aria-hidden="true">
        A
      </span>
      <div className={styles.assistantBody}>
        {turn.parts.map((part, index) =>
          part.kind === 'text' ? (
            // Parts only ever grow at the end, so the index is a stable key.
            <Markdown key={index} text={part.text} />
          ) : (
            <ToolCallCard key={part.call.callId} call={part.call} />
          ),
        )}
        {showThinking && <Thinking />}

        {turn.status === 'failed' && (
          <div className={styles.error} role="alert">
            <Icon name="alert" size={16} />
            <span>{turn.error ?? 'The agent run failed.'}</span>
          </div>
        )}
        {turn.status === 'stopped' && (
          <p className={styles.meta}>
            Stopped. This reply was not saved, so the agent won&apos;t remember it.
          </p>
        )}
        {turn.status === 'done' && turn.usage && (
          <p className={styles.meta}>
            {turn.model && <span>{turn.model} · </span>}
            {formatUsage(turn.usage)}
          </p>
        )}
      </div>
    </article>
  );
}
