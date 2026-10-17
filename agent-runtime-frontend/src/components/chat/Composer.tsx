/**
 * The message box: Enter sends, Shift+Enter adds a line, the paperclip
 * attaches files, and while the agent is working the send button becomes
 * a stop button.
 */

import { useLayoutEffect, useRef, type SubmitEvent, type KeyboardEvent } from 'react';

import type { Attachments } from '../../chat/useAttachments';
import { Icon } from '../Icon';
import styles from './Composer.module.css';

/** Tallest the textarea grows before it scrolls, in pixels. */
const MAX_HEIGHT = 220;

interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  attachments: Attachments;
  disabled?: boolean;
}

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  busy,
  attachments,
  disabled = false,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const canSend = !busy && !disabled && !attachments.uploading && value.trim().length > 0;

  // Grow with the content, up to MAX_HEIGHT.
  useLayoutEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = 'auto';
    element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  // Return focus to the box when a run finishes, ready for the next message.
  useLayoutEffect(() => {
    if (!busy) textareaRef.current?.focus();
  }, [busy]);

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (canSend) onSend();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // isComposing: Enter that confirms an IME candidate (e.g. Japanese input) must not send.
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (canSend) onSend();
    }
  };

  return (
    <form className={styles.composer} onSubmit={submit}>
      {attachments.items.length > 0 && (
        <ul className={styles.chips} aria-label="Attachments">
          {attachments.items.map((item) => (
            <li key={item.id} className={`${styles.chip ?? ''} ${styles[item.status] ?? ''}`}>
              <Icon name={item.status === 'error' ? 'alert' : 'paperclip'} size={13} />
              <span className={styles.chipName}>{item.name}</span>
              {item.status === 'uploading' && <span className={styles.chipNote}>uploading…</span>}
              {item.message && <span className={styles.chipNote}>{item.message}</span>}
              <button
                type="button"
                className={styles.chipRemove}
                onClick={() => {
                  attachments.remove(item.id);
                }}
              >
                <Icon name="x" size={12} label={`Remove ${item.name}`} />
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className={styles.box}>
        <button
          type="button"
          className={styles.iconButton}
          disabled={busy || disabled}
          onClick={() => fileRef.current?.click()}
          title="Attach files"
        >
          <Icon name="paperclip" label="Attach files" />
        </button>
        <input
          ref={fileRef}
          type="file"
          multiple
          hidden
          onChange={(event) => {
            if (event.target.files) attachments.add(event.target.files);
            event.target.value = ''; // Allow picking the same file again.
          }}
        />

        <label htmlFor="message" className="sr-only">
          Message
        </label>
        <textarea
          id="message"
          ref={textareaRef}
          className={styles.textarea}
          rows={1}
          value={value}
          placeholder={
            disabled
              ? 'The server is unavailable'
              : 'Ask the agent to read, write, or build anything…'
          }
          disabled={disabled}
          onChange={(event) => {
            onChange(event.target.value);
          }}
          onKeyDown={onKeyDown}
        />

        {busy ? (
          <button type="button" className={styles.stop} onClick={onStop} title="Stop">
            <Icon name="stop" size={16} label="Stop the agent" />
          </button>
        ) : (
          <button type="submit" className={styles.send} disabled={!canSend} title="Send">
            <Icon name="arrowUp" size={18} strokeWidth={2.4} label="Send message" />
          </button>
        )}
      </div>
      <p className={styles.hint}>
        <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line · attachments go
        to <code>uploads/</code> in the workspace
      </p>
    </form>
  );
}
