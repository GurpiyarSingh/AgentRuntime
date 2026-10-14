/** The sidebar's list of every tool the agent can call. */

import type { Tool } from '../../api/types';
import type { Resource } from '../../hooks/useResource';
import { ToolItem } from './ToolItem';
import styles from './ToolList.module.css';

interface ToolListProps {
  tools: Resource<Tool[]>;
  /** Calls per tool name in the current conversation. */
  usage: ReadonlyMap<string, number>;
}

export function ToolList({ tools, usage }: ToolListProps) {
  if (tools.loading && !tools.data) {
    return (
      <ul className={styles.skeleton} aria-busy="true" aria-label="Loading tools">
        {[0, 1, 2, 3].map((n) => (
          <li key={n} />
        ))}
      </ul>
    );
  }

  if (tools.error) {
    const needsKey = tools.error.status === 401;
    return (
      <div className={styles.error} role="alert">
        <p>
          {needsKey
            ? 'The server needs an API key. Add it under Settings below.'
            : `Couldn't load tools: ${tools.error.message}`}
        </p>
        <button type="button" className={styles.retry} onClick={tools.reload}>
          Retry
        </button>
      </div>
    );
  }

  const list = tools.data ?? [];
  if (list.length === 0) return <p className={styles.empty}>No tools are enabled.</p>;

  return (
    <ul className={styles.list}>
      {list.map((tool) => (
        <ToolItem key={tool.name} tool={tool} uses={usage.get(tool.name) ?? 0} />
      ))}
    </ul>
  );
}
