/** Paste a Claude Desktop, Cursor or VS Code MCP config and add every server in it. */

import { useId, useState } from 'react';

import { ApiError } from '../../api/client';
import type { McpImportResult } from '../../api/types';
import { IMPORT_EXAMPLE } from '../../lib/mcpTemplates';
import { Icon } from '../Icon';
import styles from './McpDialog.module.css';

interface McpImportProps {
  onImport: (json: string, overwrite: boolean) => Promise<McpImportResult>;
  onDone: (firstName: string | undefined) => void;
  onCancel: () => void;
}

export function McpImport({ onImport, onDone, onCancel }: McpImportProps) {
  const [text, setText] = useState('');
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<McpImportResult>();
  const textId = useId();

  const submit = async () => {
    setBusy(true);
    setError('');
    setResult(undefined);
    try {
      const outcome = await onImport(text, overwrite);
      setResult(outcome);
      if (outcome.skipped.length === 0) onDone(outcome.added[0] ?? outcome.replaced[0]);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'The import failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.form}>
      <header className={styles.paneHeader}>
        <div>
          <h3 className={styles.paneTitle}>Import from JSON</h3>
          <p className={styles.paneSubtitle}>
            Paste the <code>mcpServers</code> config from Claude Desktop, Cursor or VS Code.
          </p>
        </div>
      </header>

      <label htmlFor={textId} className={styles.label}>
        Configuration
      </label>
      <textarea
        id={textId}
        className={`${styles.input ?? ''} ${styles.mono ?? ''} ${styles.code ?? ''}`}
        value={text}
        rows={14}
        spellCheck={false}
        placeholder={IMPORT_EXAMPLE}
        onChange={(event) => {
          setText(event.target.value);
        }}
      />
      <label className={styles.checkbox}>
        <input
          type="checkbox"
          checked={overwrite}
          onChange={(event) => {
            setOverwrite(event.target.checked);
          }}
        />
        Replace servers that already exist
      </label>

      {error && (
        <p className={styles.formError} role="alert">
          <Icon name="alert" size={15} />
          {error}
        </p>
      )}
      {result && result.skipped.length > 0 && (
        <p className={styles.notice} role="status">
          <Icon name="alert" size={15} />
          Added {result.added.length}, replaced {result.replaced.length}. Skipped{' '}
          {result.skipped.join(', ')}: they already exist. Tick “Replace” to overwrite them.
        </p>
      )}

      <footer className={styles.formActions}>
        <span className={styles.spacer} />
        <button type="button" className={styles.ghost} onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button
          type="button"
          className={styles.primary}
          disabled={busy || !text.trim()}
          onClick={() => void submit()}
        >
          <Icon name="upload" size={15} />
          {busy ? 'Importing…' : 'Import servers'}
        </button>
      </footer>
    </div>
  );
}
