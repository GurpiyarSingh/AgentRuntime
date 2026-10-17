/**
 * The scrolling conversation. It follows new output while the reader is at
 * the bottom, and stays put when they've scrolled up to read something.
 */

import { useLayoutEffect, useRef } from 'react';

import type { Turn } from '../../chat/chatReducer';
import type { Tone } from '../../lib/toolMeta';
import { Logo } from '../brand/Logo';
import { Icon, type IconName } from '../Icon';
import { AssistantMessage, UserMessage } from './Message';
import styles from './MessageList.module.css';

/** Pixels from the bottom that still count as "at the bottom". */
const STICK_THRESHOLD = 80;

const SUGGESTIONS: { icon: IconName; tone: Tone; title: string; prompt: string }[] = [
  {
    icon: 'folder',
    tone: 'amber',
    title: 'Explore the workspace',
    prompt: 'What files are in my workspace?',
  },
  {
    icon: 'fileText',
    tone: 'blue',
    title: 'Summarise a document',
    prompt: 'Summarise the newest document in the workspace.',
  },
  {
    icon: 'filePlus',
    tone: 'green',
    title: 'Draft a Word document',
    prompt: 'Create a Word document with a one-page project plan.',
  },
  {
    icon: 'table',
    tone: 'violet',
    title: 'Build a spreadsheet',
    prompt: 'Make a spreadsheet of monthly expenses: rent 1200, food 400, travel 150.',
  },
];

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className={styles.empty}>
      <div className={styles.emblem} aria-hidden="true">
        <span className={styles.emblemGlow} />
        <Logo size={64} />
      </div>
      <h2 className={styles.emptyTitle}>
        What should we <span className="gradient-text">get done</span> today?
      </h2>
      <p className={styles.emptyText}>
        The agent reads documents and images, creates new files and edits existing ones, showing
        every step as it works. Attach a file with the paperclip, or start from an idea:
      </p>
      <ul className={styles.suggestions}>
        {SUGGESTIONS.map((suggestion) => (
          <li key={suggestion.prompt}>
            <button
              type="button"
              className={styles.suggestion}
              onClick={() => {
                onPick(suggestion.prompt);
              }}
            >
              <span className={styles.suggestionIcon} data-tone={suggestion.tone}>
                <Icon name={suggestion.icon} size={17} />
              </span>
              <span className={styles.suggestionTitle}>{suggestion.title}</span>
              <span className={styles.suggestionPrompt}>{suggestion.prompt}</span>
              <Icon name="arrowRight" size={15} className={styles.suggestionArrow} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface MessageListProps {
  turns: Turn[];
  onPickSuggestion: (text: string) => void;
}

export function MessageList({ turns, onPickSuggestion }: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  // Runs before paint, so following the stream never flickers.
  useLayoutEffect(() => {
    const element = scrollRef.current;
    if (element && stickRef.current) element.scrollTop = element.scrollHeight;
  }, [turns]);

  const onScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight;
    stickRef.current = distance < STICK_THRESHOLD;
  };

  return (
    <div ref={scrollRef} className={styles.scroller} onScroll={onScroll}>
      {turns.length === 0 ? (
        <EmptyState onPick={onPickSuggestion} />
      ) : (
        <div className={styles.turns}>
          {turns.map((turn) =>
            turn.role === 'user' ? (
              <UserMessage key={turn.id} turn={turn} />
            ) : (
              <AssistantMessage key={turn.id} turn={turn} />
            ),
          )}
        </div>
      )}
    </div>
  );
}
