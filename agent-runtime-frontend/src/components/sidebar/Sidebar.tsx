/**
 * The left column: identity and status, the workspace folder, stored
 * conversations, the tool list, and (at the bottom) the signed-in account,
 * theme, and connection settings.
 */

import type { Health, SessionSummary, Tool, User } from '../../api/types';
import type { Resource } from '../../hooks/useResource';
import { useTheme, type ThemeChoice } from '../../lib/theme';
import { Logo } from '../brand/Logo';
import { Icon, type IconName } from '../Icon';
import { SessionList } from './SessionList';
import { SettingsPanel } from './SettingsPanel';
import styles from './Sidebar.module.css';
import { ToolList } from './ToolList';
import { WorkspacePanel } from './WorkspacePanel';

interface SidebarProps {
  health: Resource<Health>;
  tools: Resource<Tool[]>;
  toolUsage: ReadonlyMap<string, number>;
  apiKey: string;
  onApiKeyChange: (key: string) => void;
  /** The folder the agent works in; empty for the server's default. */
  workspace: string;
  onWorkspaceChange: (path: string) => void;
  /** True while a run is streaming. */
  busy: boolean;
  /** The signed-in account; undefined when the server has no sign-in. */
  user?: User | undefined;
  onSignOut?: (() => void) | undefined;
  sessions: Resource<SessionSummary[]>;
  activeSessionId: string | null;
  onOpenSession: (id: string) => Promise<void>;
  onRenameSession: (id: string, title: string) => Promise<void>;
  onDeleteSession: (id: string) => Promise<void>;
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

const THEMES: { value: ThemeChoice; icon: IconName; label: string }[] = [
  { value: 'system', icon: 'monitor', label: 'Match system theme' },
  { value: 'light', icon: 'sun', label: 'Light theme' },
  { value: 'dark', icon: 'moon', label: 'Dark theme' },
];

function ThemeSwitch() {
  const [theme, setTheme] = useTheme();
  return (
    <div className={styles.themes} role="group" aria-label="Theme">
      {THEMES.map((option) => (
        <button
          key={option.value}
          type="button"
          className={styles.theme}
          aria-pressed={theme === option.value}
          title={option.label}
          onClick={() => {
            setTheme(option.value);
          }}
        >
          <Icon name={option.icon} size={14} label={option.label} />
        </button>
      ))}
    </div>
  );
}

function initials(user: User): string {
  const name = user.display_name || user.username;
  const parts = name.split(/[\s._@-]+/).filter(Boolean);
  const letters =
    parts.length > 1 ? `${parts[0]?.[0] ?? ''}${parts[1]?.[0] ?? ''}` : name.slice(0, 2);
  return letters.toUpperCase();
}

export function Sidebar({
  health,
  tools,
  toolUsage,
  apiKey,
  onApiKeyChange,
  workspace,
  onWorkspaceChange,
  busy,
  user,
  onSignOut,
  sessions,
  activeSessionId,
  onOpenSession,
  onRenameSession,
  onDeleteSession,
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
          <Logo size={34} className={styles.logo} />
          <div>
            <h1 className={styles.title}>Agent Runtime</h1>
            <Status health={health} />
          </div>
        </div>
        <button type="button" className={styles.close} onClick={onClose}>
          <Icon name="x" label="Close tools panel" />
        </button>
      </header>

      <div className={styles.scroll}>
        <WorkspacePanel
          health={health}
          workspace={workspace}
          onWorkspaceChange={onWorkspaceChange}
          busy={busy}
        />

        {health.data?.history && (
          <section className={styles.section} aria-labelledby="sessions-heading">
            <h2 id="sessions-heading" className={styles.sectionTitle}>
              <Icon name="history" size={14} />
              Conversations
              {sessions.data && <span className={styles.count}>{sessions.data.length}</span>}
            </h2>
            <SessionList
              sessions={sessions}
              activeId={activeSessionId}
              busy={busy}
              onOpen={onOpenSession}
              onRename={onRenameSession}
              onDelete={onDeleteSession}
            />
          </section>
        )}

        <section className={styles.section} aria-labelledby="tools-heading">
          <h2 id="tools-heading" className={styles.sectionTitle}>
            <Icon name="tool" size={14} />
            Tools
            {tools.data && <span className={styles.count}>{tools.data.length}</span>}
          </h2>
          <ToolList tools={tools} usage={toolUsage} />
        </section>
      </div>

      <footer className={styles.footer}>
        {/* The API key matters only without sign-in; a signed-in browser uses its token. */}
        {!user && <SettingsPanel apiKey={apiKey} onApiKeyChange={onApiKeyChange} />}
        <div className={styles.account}>
          {user ? (
            <>
              <span className={styles.avatar} aria-hidden="true">
                {initials(user)}
              </span>
              <span className={styles.who}>
                <span className={styles.name}>{user.display_name || user.username}</span>
                <span className={styles.role}>
                  {user.is_admin ? 'Admin' : 'Member'} · @{user.username}
                </span>
              </span>
            </>
          ) : (
            <>
              <span className={`${styles.avatar ?? ''} ${styles.avatarLocal ?? ''}`}>
                <Icon name="terminal" size={16} />
              </span>
              <span className={styles.who}>
                <span className={styles.name}>Local mode</span>
                <span className={styles.role}>No sign-in on this server</span>
              </span>
            </>
          )}
          <ThemeSwitch />
          {onSignOut && (
            <button type="button" className={styles.signOut} onClick={onSignOut} title="Sign out">
              <Icon name="logout" size={16} label="Sign out" />
            </button>
          )}
        </div>
      </footer>
    </aside>
  );
}
