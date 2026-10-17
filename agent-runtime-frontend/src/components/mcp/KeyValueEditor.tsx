/** Rows of name = value, for environment variables and HTTP headers. */

import { MCP_MASK } from '../../api/types';
import { Icon } from '../Icon';
import styles from './McpDialog.module.css';

export interface Pair {
  key: string;
  value: string;
}

interface KeyValueEditorProps {
  label: string;
  hint?: string;
  pairs: Pair[];
  onChange: (pairs: Pair[]) => void;
  keyPlaceholder: string;
  valuePlaceholder: string;
}

export function KeyValueEditor({
  label,
  hint,
  pairs,
  onChange,
  keyPlaceholder,
  valuePlaceholder,
}: KeyValueEditorProps) {
  const set = (index: number, patch: Partial<Pair>) => {
    onChange(pairs.map((pair, i) => (i === index ? { ...pair, ...patch } : pair)));
  };

  return (
    <fieldset className={styles.fieldset}>
      <legend className={styles.label}>{label}</legend>
      {hint && <p className={styles.hint}>{hint}</p>}
      {pairs.map((pair, index) => (
        <div key={index} className={styles.pairRow}>
          <input
            className={`${styles.input ?? ''} ${styles.mono ?? ''}`}
            value={pair.key}
            placeholder={keyPlaceholder}
            aria-label={`${label} name ${index + 1}`}
            spellCheck={false}
            onChange={(event) => {
              set(index, { key: event.target.value });
            }}
          />
          <input
            className={`${styles.input ?? ''} ${styles.mono ?? ''}`}
            value={pair.value}
            placeholder={valuePlaceholder}
            aria-label={`${label} value ${index + 1}`}
            spellCheck={false}
            title={pair.value === MCP_MASK ? 'Saved; leave as is to keep it' : undefined}
            onFocus={(event) => {
              if (pair.value === MCP_MASK) event.target.select();
            }}
            onChange={(event) => {
              set(index, { value: event.target.value });
            }}
          />
          <button
            type="button"
            className={styles.iconButton}
            onClick={() => {
              onChange(pairs.filter((_, i) => i !== index));
            }}
          >
            <Icon name="x" size={14} label={`Remove ${pair.key || 'row'}`} />
          </button>
        </div>
      ))}
      <button
        type="button"
        className={styles.addRow}
        onClick={() => {
          onChange([...pairs, { key: '', value: '' }]);
        }}
      >
        <Icon name="plus" size={14} />
        Add {label.toLowerCase().replace(/s$/, '')}
      </button>
    </fieldset>
  );
}
