/**
 * The scrolling conversation. It follows new output while the reader is at
 * the bottom, and stays put when they've scrolled up to read something.
 */

import { useLayoutEffect, useRef } from 'react';

import type { Turn } from '../../chat/chatReducer';
import { AssistantMessage, UserMessage } from './Message';
import styles from './MessageList.module.css';

/** Pixels from the bottom that still count as "at the bottom". */
const STICK_THRESHOLD = 80;

const SUGGESTIONS = [
  'What files are in my workspace?',
  'Summarise the newest document in the workspace.',
  'Create a Word document with a one-page project plan.',
  'Make a spreadsheet of monthly expenses: rent 1200, food 400, travel 150.',
];

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className={styles.empty}>
      <h2 className={styles.emptyTitle}>What should the agent do?</h2>
      <p className={styles.emptyText}>
        It can read documents and images in its workspace, create new files, and edit existing ones.
        Attach a file with the paperclip, or try one of these:
      </p>
      <ul className={styles.suggestions}>
        {SUGGESTIONS.map((text) => (
          <li key={text}>
            <button
              type="button"
              className={styles.suggestion}
              onClick={() => {
                onPick(text);
              }}
            >
              {text}
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
