/**
 * The sidebar's Integrations section: each MCP server with its status and
 * tool count, and the way into the manager.
 */

import { useState } from 'react';

import { statusLabel } from '../../lib/mcpStatus';
import { Icon } from '../Icon';
import { McpDialog, type McpPane } from './McpDialog';
import styles from './McpPanel.module.css';
import { StatusDot } from './McpStatus';
import type { McpServers } from './useMcpServers';

export function McpPanel({ mcp }: { mcp: McpServers }) {
  const [pane, setPane] = useState<McpPane | undefined>();
  const [open, setOpen] = useState(false);
  const servers = mcp.data?.servers ?? [];
  const connected = servers.filter((server) => server.status === 'connected').length;

  const show = (next: McpPane | undefined) => {
    setPane(next);
    setOpen(true);
  };

  return (
    <section className={styles.panel} aria-labelledby="mcp-heading">
      <h2 id="mcp-heading" className={styles.heading}>
        <Icon name="plug" size={14} />
        Integrations
        {servers.length > 0 && (
          <span className={styles.count} title={`${connected} of ${servers.length} connected`}>
            {connected}/{servers.length}
          </span>
        )}
        <button
          type="button"
          className={styles.manage}
          onClick={() => {
            show(undefined);
          }}
        >
          Manage
        </button>
      </h2>

      {servers.length === 0 ? (
        <button
          type="button"
          className={styles.cta}
          onClick={() => {
            show(mcp.data?.can_manage ? { kind: 'add' } : undefined);
          }}
        >
          <span className={styles.ctaIcon}>
            <Icon name="plug" size={16} />
          </span>
          <span>
            <span className={styles.ctaTitle}>Connect an MCP server</span>
            <span className={styles.ctaText}>GitHub, Jira, Playwright and more</span>
          </span>
        </button>
      ) : (
        <ul className={styles.list}>
          {servers.map((server) => (
            <li key={server.name}>
              <button
                type="button"
                className={styles.row}
                onClick={() => {
                  show({ kind: 'view', name: server.name });
                }}
              >
                <StatusDot status={server.status} />
                <span className={styles.name}>{server.name}</span>
                <span className={styles.meta}>
                  {server.status === 'connected'
                    ? `${server.tools.length} ${server.tools.length === 1 ? 'tool' : 'tools'}`
                    : statusLabel(server.status)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {open && (
        <McpDialog
          mcp={mcp}
          initialPane={pane}
          onClose={() => {
            setOpen(false);
          }}
        />
      )}
    </section>
  );
}
