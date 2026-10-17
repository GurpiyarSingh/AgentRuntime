/**
 * Managing MCP servers in the web app, against a fake backend: what an
 * admin can do, what everyone else sees, and that new tools reach the
 * agent's tool list.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ApiProvider } from './api/ApiContext';
import { ApiClient } from './api/client';
import { App } from './App';
import { toolMeta } from './lib/toolMeta';
import { createFakeServer, mcpServer, type FakeServerOptions } from './test/fakeServer';

function renderApp(options: FakeServerOptions) {
  const server = createFakeServer(options);
  const client = new ApiClient({ baseUrl: '', fetch: server.fetch });
  const user = userEvent.setup();
  render(
    <ApiProvider client={client}>
      <App apiKey="" onApiKeyChange={() => undefined} />
    </ApiProvider>,
  );
  return { server, user };
}

const sidebar = () => screen.getByRole('complementary', { name: 'Tools and settings' });
const integrations = () =>
  within(sidebar())
    .getByRole('heading', { name: /Integrations/ })
    .closest('section') as HTMLElement;

describe('MCP servers', () => {
  it('lists servers in the sidebar and groups their tools', async () => {
    renderApp({ mcp: { servers: [mcpServer('github')] } });

    expect(await within(sidebar()).findByText('Integrations')).toBeInTheDocument();
    const panel = integrations();
    expect(await within(panel).findByText('github')).toBeInTheDocument();
    expect(within(panel).getByText('1 tool')).toBeInTheDocument();
    // The agent's tool list has a group for the server.
    expect(await within(sidebar()).findByRole('heading', { name: /github/ })).toBeInTheDocument();
    expect(within(sidebar()).getByText('Built-in')).toBeInTheDocument();
  });

  it('adds a server from a template, after testing it', async () => {
    const { server, user } = renderApp({ mcp: { servers: [] } });

    await user.click(
      await within(sidebar()).findByRole('button', { name: /Connect an MCP server/ }),
    );
    const dialog = screen.getByRole('dialog', { name: 'MCP servers' });
    await user.click(within(dialog).getByRole('button', { name: 'Fetch' }));
    expect(within(dialog).getByLabelText('Command')).toHaveValue('uvx');
    expect(within(dialog).getByText(/Needs uv \(uvx\)/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Test connection' }));
    expect(await within(dialog).findByText(/Connected to fake-mcp 1.0/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Add server' }));
    expect(await within(dialog).findByRole('heading', { name: 'fetch' })).toBeInTheDocument();
    const created = server.requests.find(
      (r) => r.url.endsWith('/v1/mcp/servers') && r.method === 'POST',
    );
    expect(created?.body).toMatchObject({
      name: 'fetch',
      config: { type: 'stdio', command: 'uvx', args: ['mcp-server-fetch'], url: null },
    });
    // Its tools reach the agent's tool list.
    await waitFor(() => {
      expect(within(sidebar()).getByRole('heading', { name: /fetch/ })).toBeInTheDocument();
    });
  });

  it('checks the form before sending it', async () => {
    const { server, user } = renderApp({ mcp: { servers: [] } });

    await user.click(
      await within(sidebar()).findByRole('button', { name: /Connect an MCP server/ }),
    );
    const dialog = screen.getByRole('dialog', { name: 'MCP servers' });
    await user.type(within(dialog).getByLabelText('Name'), 'bad name');
    await user.click(within(dialog).getByRole('button', { name: 'Add server' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent(/Name: 1-32 letters/);

    await user.clear(within(dialog).getByLabelText('Name'));
    await user.type(within(dialog).getByLabelText('Name'), 'remote');
    await user.click(within(dialog).getByRole('radio', { name: 'HTTP' }));
    await user.click(within(dialog).getByRole('button', { name: 'Add server' }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent(/server URL/);
    expect(server.requests.some((r) => r.method === 'POST' && r.url.includes('/v1/mcp/'))).toBe(
      false,
    );
  });

  it('disables, edits and deletes a server', async () => {
    const { server, user } = renderApp({ mcp: { servers: [mcpServer('github')] } });

    await user.click(await within(sidebar()).findByRole('button', { name: 'Manage' }));
    const dialog = screen.getByRole('dialog', { name: 'MCP servers' });
    expect(within(dialog).getByText('github__search')).toBeInTheDocument();

    await user.click(within(dialog).getByRole('switch', { name: 'Disable github' }));
    expect(await within(dialog).findAllByText('Disabled')).not.toHaveLength(0);
    const patch = server.requests.find((r) => r.method === 'PATCH');
    expect(patch?.body).toEqual({ enabled: false });

    await user.click(within(dialog).getByRole('button', { name: 'Edit' }));
    await user.click(within(dialog).getByRole('button', { name: /Add environment variable/ }));
    await user.type(within(dialog).getByLabelText('Environment variables name 1'), 'TOKEN');
    await user.type(within(dialog).getByLabelText('Environment variables value 1'), 'abc');
    await user.click(within(dialog).getByRole('button', { name: 'Save changes' }));
    await within(dialog).findByRole('heading', { name: 'github' });
    const put = server.requests.find((r) => r.method === 'PUT');
    expect(put?.body).toMatchObject({ env: { TOKEN: 'abc' } });

    await user.click(within(dialog).getByRole('button', { name: 'Delete server' }));
    await user.click(within(dialog).getByRole('button', { name: 'Delete github' }));
    expect(await within(dialog).findByText('Connect your tools')).toBeInTheDocument();
  });

  it('imports servers from pasted JSON', async () => {
    const { user } = renderApp({ mcp: { servers: [mcpServer('github')] } });

    await user.click(await within(sidebar()).findByRole('button', { name: 'Manage' }));
    const dialog = screen.getByRole('dialog', { name: 'MCP servers' });
    await user.click(within(dialog).getByRole('button', { name: 'Import' }));
    const box = within(dialog).getByLabelText('Configuration');
    await user.click(box);
    await user.paste('{"mcpServers": {"memory": {"command": "npx", "args": ["-y", "x"]}}}');
    await user.click(within(dialog).getByRole('button', { name: 'Import servers' }));

    expect(await within(dialog).findByRole('heading', { name: 'memory' })).toBeInTheDocument();
    expect(within(integrations()).getByText('memory')).toBeInTheDocument();
  });

  it('lets non-admins look but not change', async () => {
    const { user } = renderApp({ mcp: { servers: [mcpServer('github')], canManage: false } });

    await user.click(await within(sidebar()).findByRole('button', { name: 'Manage' }));
    const dialog = screen.getByRole('dialog', { name: 'MCP servers' });
    expect(within(dialog).getByText('github__search')).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: 'New server' })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole('switch')).not.toBeInTheDocument();
  });

  it('hides integrations when the server has MCP turned off', async () => {
    renderApp({});
    await within(sidebar()).findByText('Connected');
    expect(within(sidebar()).queryByText('Integrations')).not.toBeInTheDocument();
  });
});

describe('toolMeta', () => {
  it('labels MCP tools by server', () => {
    expect(toolMeta('github__create_issue')).toEqual({
      icon: 'plug',
      tone: 'cyan',
      label: 'github · create_issue',
    });
    expect(toolMeta('read_file').label).toBe('Read file');
  });
});
