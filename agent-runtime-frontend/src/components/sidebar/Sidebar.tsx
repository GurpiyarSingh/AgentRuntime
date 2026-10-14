/** The left column: identity and status, the tool list, and settings. */

import type { Health, Tool } from '../../api/types';
import type { Resource } from '../../hooks/useResource';
import { Icon } from '../Icon';
import { SettingsPanel } from './SettingsPanel';
import styles from './Sidebar.module.css';
import { ToolList } from './ToolList';

interface SidebarProps {
  health: Resource<Health>;
  tools: Resource<Tool[]>;
  toolUsage: ReadonlyMap<string, number>;
  apiKey: string;
  onApiKeyChange: (key: string) => void;
  /** Narrow screens show the sidebar as a drawer. */
  open: boolean;
  onClose: () => void;
}

function Status({ health }: { health: Resource<Health> }) {
  if (health.loading && !health.data) {
    return <span className={styles.statusPending}>Connecting…</span>;
  }
  if (health.error || !health.data) return <span className={styles.statusDown}>Offline</span>;
  return (
    <span className={styles.statusUp}>
      Connected
      {health.data.workspace.read_only && <span className={styles.readOnly}>read-only</span>}
    </span>
  );
}

export function Sidebar({
  health,
  tools,
  toolUsage,
  apiKey,
  onApiKeyChange,
  open,
  onClose,
}: SidebarProps) {
  return (
    <aside
      id="sidebar"
      className={open ? `${styles.sidebar ?? ''} ${styles.open ?? ''}` : styles.sidebar}
      aria-label="Tools and settings"
    >
      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.logo} aria-hidden="true">
            A
          </span>
          <div>
            <h1 className={styles.title}>Agent Runtime</h1>
            <Status health={health} />
          </div>
        </div>
        <button type="button" className={styles.close} onClick={onClose}>
          <Icon name="x" label="Close tools panel" />
        </button>
      </header>

      <section className={styles.section} aria-labelledby="tools-heading">
        <h2 id="tools-heading" className={styles.sectionTitle}>
          <Icon name="tool" size={15} />
          Tools
          {tools.data && <span className={styles.count}>{tools.data.length}</span>}
        </h2>
        <ToolList tools={tools} usage={toolUsage} />
      </section>

      <SettingsPanel apiKey={apiKey} onApiKeyChange={onApiKeyChange} />
    </aside>
  );
}
