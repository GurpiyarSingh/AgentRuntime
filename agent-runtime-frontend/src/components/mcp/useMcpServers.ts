/**
 * The MCP servers and everything that can be done to them.
 *
 * Polls while any server is still connecting (a first `npx` start can take
 * a minute), and calls `onToolsChanged` after every change, so the tool
 * list the agent sees refreshes too.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { ApiError, type ApiClient } from '../../api/client';
import type {
  McpImportResult,
  McpServer,
  McpServerConfig,
  McpServersResponse,
  McpTestResult,
} from '../../api/types';

const POLL_MS = 2500;

export interface McpServers {
  data: McpServersResponse | undefined;
  error: string;
  reload: () => Promise<void>;
  create: (name: string, config: McpServerConfig) => Promise<McpServer>;
  update: (name: string, config: McpServerConfig) => Promise<McpServer>;
  setEnabled: (name: string, enabled: boolean) => Promise<void>;
  reconnect: (name: string) => Promise<void>;
  remove: (name: string) => Promise<void>;
  test: (config: McpServerConfig, name?: string) => Promise<McpTestResult>;
  importJson: (json: string, overwrite: boolean) => Promise<McpImportResult>;
}

export function useMcpServers(
  client: ApiClient,
  enabled: boolean,
  onToolsChanged: () => void,
): McpServers {
  const [data, setData] = useState<McpServersResponse>();
  const [error, setError] = useState('');
  // Read inside callbacks without re-creating them on every render.
  const changedRef = useRef(onToolsChanged);
  useEffect(() => {
    changedRef.current = onToolsChanged;
  }, [onToolsChanged]);

  const reload = useCallback(async () => {
    try {
      setData(await client.mcpServers());
      setError('');
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Could not load MCP servers.');
    }
  }, [client]);

  useEffect(() => {
    if (!enabled) return;
    let live = true;
    client.mcpServers().then(
      (loaded) => {
        if (live) setData(loaded);
      },
      (reason: unknown) => {
        if (live) {
          setError(reason instanceof ApiError ? reason.message : 'Could not load MCP servers.');
        }
      },
    );
    return () => {
      live = false;
    };
  }, [enabled, client]);

  // While a server is connecting, check back until it settles, then refresh
  // the tool list so its tools appear.
  const connecting = data?.servers.some((server) => server.status === 'connecting') ?? false;
  useEffect(() => {
    if (!enabled || !connecting) return;
    const timer = window.setInterval(() => {
      void reload().then(() => {
        changedRef.current();
      });
    }, POLL_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [enabled, connecting, reload]);

  const after = useCallback(
    async <T>(action: Promise<T>): Promise<T> => {
      const result = await action;
      await reload();
      changedRef.current();
      return result;
    },
    [reload],
  );

  return {
    data,
    error,
    reload,
    create: (name, config) => after(client.createMcpServer(name, config)),
    update: (name, config) => after(client.updateMcpServer(name, config)),
    setEnabled: async (name, on) => {
      await after(client.setMcpServerEnabled(name, on));
    },
    reconnect: async (name) => {
      await after(client.reconnectMcpServer(name));
    },
    remove: (name) => after(client.deleteMcpServer(name)),
    test: (config, name) => client.testMcpServer(config, name),
    importJson: (json, overwrite) => after(client.importMcpServers(json, overwrite)),
  };
}
