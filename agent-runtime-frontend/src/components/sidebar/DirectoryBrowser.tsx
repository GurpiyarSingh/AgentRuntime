/**
 * A folder picker for the server's disk.
 *
 * A browser can't reveal real filesystem paths (and the agent's tools run on
 * the server anyway), so this browses folders through `GET /v1/directories`.
 * A path can also be pasted into the box and opened with Enter.
 */

import { useCallback, useEffect, useId, useRef, useState, type SubmitEvent } from 'react';
import { createPortal } from 'react-dom';

import { useApi } from '../../api/ApiContext';
import { useResource } from '../../hooks/useResource';
import { Icon } from '../Icon';
import styles from './DirectoryBrowser.module.css';

interface DirectoryBrowserProps {
  /** Folder to open first; the top-level locations if empty. */
  initialPath: string;
  onSelect: (path: string) => void;
  onClose: () => void;
}

export function DirectoryBrowser({ initialPath, onSelect, onClose }: DirectoryBrowserProps) {
  const client = useApi();
  const [path, setPath] = useState(initialPath);
  const [draft, setDraft] = useState(initialPath);
  const titleId = useId();
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(
    (signal: AbortSignal) => client.directories(path || undefined, signal),
    [client, path],
  );
  const listing = useResource(load);
  // The listing on screen belongs to `path` only once it has loaded.
  const shown = listing.loading ? undefined : listing.data;
  const current = shown?.path ?? null;

  const open = (next: string) => {
    setPath(next);
    setDraft(next);
  };

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const submit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    open(draft.trim());
  };

  return createPortal(
    <div
      className={styles.backdrop}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            // Handled here, so the sidebar drawer behind stays open.
            event.stopPropagation();
            onClose();
          }
        }}
      >
        <header className={styles.header}>
          <h2 id={titleId} className={styles.title}>
            <Icon name="folder" size={17} />
            Choose a folder
          </h2>
          <button type="button" className={styles.iconButton} onClick={onClose}>
            <Icon name="x" label="Close" />
          </button>
        </header>

        <form className={styles.pathRow} onSubmit={submit}>
          <button
            type="button"
            className={styles.iconButton}
            disabled={!path}
            onClick={() => {
              open(shown?.parent ?? '');
            }}
          >
            <Icon name="up" label="Up one folder" />
          </button>
          <input
            ref={inputRef}
            className={styles.pathInput}
            value={draft}
            spellCheck={false}
            autoComplete="off"
            aria-label="Folder path"
            placeholder="Paste a folder path, or pick one below"
            onChange={(event) => {
              setDraft(event.target.value);
            }}
          />
          <button type="submit" className={styles.secondary}>
            Go
          </button>
        </form>

        <div className={styles.list} aria-busy={listing.loading}>
          {listing.error && !listing.loading ? (
            <p className={styles.error} role="alert">
              <Icon name="alert" size={15} />
              {listing.error.message}
            </p>
          ) : !shown ? (
            <p className={styles.empty}>Loading…</p>
          ) : shown.directories.length === 0 ? (
            <p className={styles.empty}>No folders inside.</p>
          ) : (
            <ul className={styles.entries}>
              {shown.directories.map((entry) => (
                <li key={entry.path}>
                  <button
                    type="button"
                    className={styles.entry}
                    title={entry.path}
                    onClick={() => {
                      open(entry.path);
                    }}
                  >
                    <Icon name="folder" size={16} />
                    <span className={styles.entryName}>{entry.name}</span>
                    <Icon name="chevron" size={14} className={styles.chevron} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {shown?.truncated && <p className={styles.empty}>Some folders are not shown.</p>}
        </div>

        <footer className={styles.footer}>
          <span className={styles.selected} title={current ?? undefined}>
            {current ?? 'Open a folder to choose it'}
          </span>
          <button type="button" className={styles.secondary} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.primary}
            disabled={!current}
            onClick={() => {
              if (current) onSelect(current);
            }}
          >
            Use this folder
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
