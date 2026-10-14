/** Connection settings: the optional API key, kept in this browser only. */

import { useId, useState, type SubmitEvent } from 'react';

import { Icon } from '../Icon';
import styles from './SettingsPanel.module.css';

interface SettingsPanelProps {
  apiKey: string;
  onApiKeyChange: (key: string) => void;
}

export function SettingsPanel({ apiKey, onApiKeyChange }: SettingsPanelProps) {
  const [draft, setDraft] = useState(apiKey);
  const [visible, setVisible] = useState(false);
  const inputId = useId();
  const dirty = draft.trim() !== apiKey;

  const save = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    onApiKeyChange(draft.trim());
  };

  return (
    <details className={styles.settings}>
      <summary className={styles.summary}>
        <Icon name="key" size={15} />
        Settings
        {apiKey && <span className={styles.badge}>API key set</span>}
      </summary>
      <form className={styles.form} onSubmit={save}>
        <label htmlFor={inputId} className={styles.label}>
          API key
        </label>
        <div className={styles.row}>
          <input
            id={inputId}
            className={styles.input}
            type={visible ? 'text' : 'password'}
            value={draft}
            autoComplete="off"
            spellCheck={false}
            placeholder="Only if the server requires one"
            onChange={(event) => {
              setDraft(event.target.value);
            }}
          />
          <button
            type="button"
            className={styles.ghost}
            onClick={() => {
              setVisible((value) => !value);
            }}
          >
            {visible ? 'Hide' : 'Show'}
          </button>
        </div>
        <p className={styles.hint}>
          Sent as <code>X-API-Key</code>. Stored in this browser only.
        </p>
        <button type="submit" className={styles.save} disabled={!dirty}>
          Save
        </button>
      </form>
    </details>
  );
}
