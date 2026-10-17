/** A single turn in the conversation: the user's message or the agent's reply. */

import type { AssistantTurn, UserTurn } from '../../chat/chatReducer';
import { formatUsage } from '../../lib/format';
import { toolMeta } from '../../lib/toolMeta';
import { Logo } from '../brand/Logo';
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

/** What the agent is doing right now, while no text is streaming. */
function Thinking({ turn }: { turn: AssistantTurn }) {
  const last = turn.parts.at(-1);
  const running = last?.kind === 'tool' && last.call.status === 'running';
  const label = running ? `Using ${toolMeta(last.call.toolName).label.toLowerCase()}` : 'Thinking';
  return (
    <span className={styles.thinking} role="status">
      <span className={styles.dots} aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span className={styles.thinkingLabel}>{label}…</span>
      <span className="sr-only">The agent is working</span>
    </span>
  );
}

export function AssistantMessage({ turn }: { turn: AssistantTurn }) {
  const streaming = turn.status === 'streaming';
  // While streaming, show progress until the first token or tool call, and
  // again after a tool call while the model decides what to do next.
  const showThinking = streaming && turn.parts.at(-1)?.kind !== 'text';

  return (
    <article className={styles.assistant} aria-label="Agent" aria-busy={streaming}>
      <span className={`${styles.avatar ?? ''} ${streaming ? (styles.avatarLive ?? '') : ''}`}>
        <Logo size={30} />
      </span>
      <div className={styles.assistantBody}>
        <div className={styles.byline}>
          <span className={styles.author}>Agent</span>
          {turn.model && <span className={styles.modelTag}>{turn.model}</span>}
        </div>
        {turn.parts.map((part, index) =>
          part.kind === 'text' ? (
            // Parts only ever grow at the end, so the index is a stable key.
            <Markdown key={index} text={part.text} />
          ) : (
            <ToolCallCard key={part.call.callId} call={part.call} />
          ),
        )}
        {showThinking && <Thinking turn={turn} />}

        {turn.status === 'failed' && (
          <div className={styles.error} role="alert">
            <Icon name="alert" size={16} />
            <span>{turn.error ?? 'The agent run failed.'}</span>
          </div>
        )}
        {turn.status === 'stopped' && (
          <p className={styles.meta}>
            <Icon name="stop" size={13} />
            Stopped. This reply was not saved, so the agent won&apos;t remember it.
          </p>
        )}
        {turn.status === 'done' && turn.usage && (
          <p className={styles.meta}>
            <Icon name="bolt" size={13} />
            {formatUsage(turn.usage)}
          </p>
        )}
      </div>
    </article>
  );
}
