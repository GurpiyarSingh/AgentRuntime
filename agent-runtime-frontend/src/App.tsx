/**
 * The application shell: tools on the left, chat on the right.
 *
 * Owns the app-wide state: the API key and model preference (persisted in
 * this browser), the server resources (health, tools, models) and the
 * conversation, and hands each column what it needs.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';

import { useApi } from './api/ApiContext';
import styles from './App.module.css';
import { useAttachments } from './chat/useAttachments';
import { useChat } from './chat/useChat';
import { ChatPanel } from './components/chat/ChatPanel';
import { Sidebar } from './components/sidebar/Sidebar';
import { UPLOAD_FOLDER } from './config';
import { useResource } from './hooks/useResource';
import { loadSetting, saveSetting } from './lib/storage';

interface AppProps {
  apiKey: string;
  onApiKeyChange: (key: string) => void;
}

export function App({ apiKey, onApiKeyChange }: AppProps) {
  const client = useApi();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [preferredModel, setPreferredModel] = useState(() => loadSetting('model'));

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
        onOpenSidebar={() => {
          setSidebarOpen(true);
        }}
      />
    </div>
  );
}
