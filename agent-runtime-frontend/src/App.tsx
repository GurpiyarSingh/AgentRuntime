/**
 * The application shell: the sidebar (workspace, conversations, tools, you)
 * on the left, the conversation on the right.
 *
 * Owns the app-wide state: model preference and workspace folder (persisted
 * in this browser), the server resources (health, tools, models, stored
 * sessions) and the conversation, and hands each column what it needs.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { useApi } from './api/ApiContext';
import type { User } from './api/types';
import styles from './App.module.css';
import { turnsFromSession } from './chat/history';
import { useAttachments } from './chat/useAttachments';
import { useChat } from './chat/useChat';
import { ChatPanel } from './components/chat/ChatPanel';
import { useMcpServers } from './components/mcp/useMcpServers';
import { Sidebar } from './components/sidebar/Sidebar';
import { UPLOAD_FOLDER } from './config';
import { useResource } from './hooks/useResource';
import { loadSetting, saveSetting } from './lib/storage';

interface AppProps {
  apiKey: string;
  onApiKeyChange: (key: string) => void;
  /** The signed-in account; undefined when the server has no sign-in. */
  user?: User | undefined;
  onSignOut?: (() => void) | undefined;
}

export function App({ apiKey, onApiKeyChange, user, onSignOut }: AppProps) {
  const client = useApi();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [preferredModel, setPreferredModel] = useState(() => loadSetting('model'));
  const [workspace, setWorkspace] = useState(() => {
    const saved = loadSetting('workspace');
    client.setWorkspace(saved); // Before any request, so the first chat already uses it.
    return saved;
  });

  const loadHealth = useCallback((signal: AbortSignal) => client.health(signal), [client]);
  const loadTools = useCallback((signal: AbortSignal) => client.tools(signal), [client]);
  const loadModels = useCallback((signal: AbortSignal) => client.models(signal), [client]);
  // Keyed on the API key: entering or changing it refetches everything.
  const health = useResource(loadHealth, apiKey);
  const tools = useResource(loadTools, apiKey);
  const models = useResource(loadModels, apiKey);

  const chat = useChat(client);
  const attachments = useAttachments(client, UPLOAD_FOLDER);

  // A remembered model the server no longer offers falls back to its default.
  const available = models.data?.models.map((m) => m.id) ?? [];
  const model = available.includes(preferredModel)
    ? preferredModel
    : (models.data?.default ?? preferredModel);

  const changeModel = (id: string) => {
    setPreferredModel(id);
    saveSetting('model', id);
  };

  const changeWorkspace = (path: string) => {
    client.setWorkspace(path);
    setWorkspace(path);
    saveSetting('workspace', path);
    // Attachments were uploaded into the previous folder.
    attachments.clear();
  };

  // Stored conversations, when the server has a database. Refetched whenever a
  // run starts or ends, so the list shows new sessions and fresh totals.
  const historyEnabled = health.data?.history === true;
  const loadSessions = useCallback(
    (signal: AbortSignal) => (historyEnabled ? client.sessions(signal) : Promise.resolve([])),
    [client, historyEnabled],
  );
  const sessions = useResource(
    loadSessions,
    `${apiKey}|${user?.id ?? ''}|${String(chat.state.busy)}`,
  );
  // MCP servers: any change, or a server finishing connecting, refreshes the
  // tool list, so the sidebar shows what the agent can use right now.
  const mcpEnabled = health.data?.mcp === true;
  const mcp = useMcpServers(client, mcpEnabled, tools.reload);

  const title = sessions.data?.find((session) => session.id === chat.state.sessionId)?.title;

  const openSession = async (id: string) => {
    const detail = await client.session(id);
    chat.load(detail.id, turnsFromSession(detail));
    attachments.clear();
    // Continue in the folder the conversation was working in.
    if (health.data?.workspace.selectable) {
      const folder = detail.workspace ?? '';
      changeWorkspace(folder === health.data.workspace.path ? '' : folder);
    }
    setSidebarOpen(false);
  };

  const renameSession = async (id: string, title: string) => {
    await client.renameSession(id, title);
    sessions.reload();
  };

  const deleteSession = async (id: string) => {
    await client.deleteSession(id);
    if (id === chat.state.sessionId) {
      chat.reset();
      attachments.clear();
    }
    sessions.reload();
  };

  const toolUsage = useMemo(() => {
    const counts = new Map<string, number>();
    for (const turn of chat.state.turns) {
      if (turn.role !== 'assistant') continue;
      for (const part of turn.parts) {
        if (part.kind === 'tool') {
          counts.set(part.call.toolName, (counts.get(part.call.toolName) ?? 0) + 1);
        }
      }
    }
    return counts;
  }, [chat.state.turns]);

  // Escape closes the drawer on narrow screens.
  useEffect(() => {
    if (!sidebarOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setSidebarOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
    };
  }, [sidebarOpen]);

  return (
    <div className={styles.app}>
      <Sidebar
        health={health}
        tools={tools}
        toolUsage={toolUsage}
        apiKey={apiKey}
        onApiKeyChange={onApiKeyChange}
        workspace={workspace}
        onWorkspaceChange={changeWorkspace}
        busy={chat.state.busy}
        user={user}
        onSignOut={onSignOut}
        sessions={sessions}
        mcp={mcpEnabled ? mcp : undefined}
        activeSessionId={chat.state.sessionId}
        onOpenSession={openSession}
        onRenameSession={renameSession}
        onDeleteSession={deleteSession}
        open={sidebarOpen}
        onClose={() => {
          setSidebarOpen(false);
        }}
      />
      {sidebarOpen && (
        <div
          className={styles.scrim}
          aria-hidden="true"
          onClick={() => {
            setSidebarOpen(false);
          }}
        />
      )}
      <ChatPanel
        chat={chat}
        attachments={attachments}
        health={health}
        models={models}
        model={model}
        onModelChange={changeModel}
        title={title}
        onOpenSidebar={() => {
          setSidebarOpen(true);
        }}
      />
    </div>
  );
}
