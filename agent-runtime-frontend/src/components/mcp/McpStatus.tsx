/** A server's connection status, as a dot or a labelled pill. */

import type { McpStatus } from '../../api/types';
import { statusLabel } from '../../lib/mcpStatus';
import styles from './McpDialog.module.css';

export function StatusDot({ status }: { status: McpStatus }) {
  return <span className={styles.dot} data-status={status} title={statusLabel(status)} />;
}

export function StatusPill({ status }: { status: McpStatus }) {
  return (
    <span className={styles.pill} data-status={status}>
      <span className={styles.dot} data-status={status} />
      {statusLabel(status)}
    </span>
  );
}
