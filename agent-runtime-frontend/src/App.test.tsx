/**
 * The whole UI against a fake backend: what a user sees and can do.
 */

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ApiProvider } from './api/ApiContext';
import { ApiClient } from './api/client';
import type { AgentEvent, SessionDetail } from './api/types';
import { App } from './App';
import { createFakeServer, type FakeServerOptions } from './test/fakeServer';

const base = { run_id: 'run_1', session_id: 'sess_1', model: 'gpt-4o' };

function renderApp(options: FakeServerOptions = {}) {
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

const writeFileRun: AgentEvent[] = [
  { type: 'run_started', data: { ...base, max_steps: 8 } },
  {
    type: 'tool_call_requested',
    data: {
      ...base,
      step: 1,
      call_id: 'c1',
      tool_name: 'write_file',
      arguments: { path: 'plan.docx' },
    },
  },
  {
    type: 'tool_call_result',
    data: {
      ...base,
      step: 1,
      call_id: 'c1',
      tool_name: 'write_file',
      content: 'Created plan.docx (docx, 36.9 KB).',
      is_error: false,
      duration_s: 0.08,
      image_count: 0,
    },
  },
  { type: 'model_token', data: { ...base, step: 2, text: 'I created ' } },
  { type: 'model_token', data: { ...base, step: 2, text: '**plan.docx**.' } },
  {
    type: 'usage_updated',
    data: {
      ...base,
      step: 2,
      step_usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2, cost_usd: 0 },
      run_usage: { input_tokens: 4000, output_tokens: 722, total_tokens: 4722, cost_usd: 0.0156 },
    },
  },
  { type: 'final_answer', data: { ...base, step: 2, content: 'I created **plan.docx**.' } },
];

describe('App', () => {
  it('lists every tool in the sidebar, expandable to its parameters', async () => {
    const { user } = renderApp();
    const sidebar = screen.getByRole('complementary', { name: 'Tools and settings' });

    const readFile = await within(sidebar).findByRole('button', { name: /read_file/ });
    expect(within(sidebar).getByRole('button', { name: /write_file/ })).toBeInTheDocument();
    expect(within(sidebar).getByText('Connected')).toBeInTheDocument();

    await user.click(readFile);
    expect(readFile).toHaveAttribute('aria-expanded', 'true');
    expect(within(sidebar).getByText('start_line')).toBeInTheDocument();
    expect(within(sidebar).getByText('required')).toBeInTheDocument();
    expect(within(sidebar).getByText('default 1')).toBeInTheDocument();
  });

  it('asks for an API key when the server requires one', async () => {
    renderApp({ toolsStatus: 401 });
    expect(await screen.findByText(/needs an API key/)).toBeInTheDocument();
  });

  it('streams a reply with its tool calls, usage and a download button', async () => {
    const { server, user } = renderApp({ chats: [writeFileRun] });

    await user.type(screen.getByLabelText('Message'), 'Write a plan{Enter}');

    expect(await screen.findByText('plan.docx', { selector: 'strong' })).toBeInTheDocument();
    expect(screen.getByText('Write a plan')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Download plan\.docx/ })).toBeInTheDocument();
    expect(screen.getByText(/4,722 tokens · \$0\.0156/)).toBeInTheDocument();

    // The sidebar counts tool use in this conversation.
    expect(screen.getByTitle('Used 1 times in this conversation')).toHaveTextContent('1×');

    const chatRequest = server.requests.find((r) => r.url.endsWith('/v1/chat/stream'));
    expect(chatRequest?.body).toEqual({ message: 'Write a plan', model: 'gpt-4o' });
  });

  it('continues the same session on the next message', async () => {
    const { server, user } = renderApp({
      chats: [
        writeFileRun,
        [{ type: 'final_answer', data: { ...base, step: 1, content: 'Again.' } }],
      ],
    });

    await user.type(screen.getByLabelText('Message'), 'first{Enter}');
    await screen.findByText(/4,722 tokens/);
    await user.type(screen.getByLabelText('Message'), 'second{Enter}');
    await screen.findByText('Again.');

    const bodies = server.requests
      .filter((r) => r.url.endsWith('/v1/chat/stream'))
      .map((r) => r.body);
    expect(bodies[1]).toMatchObject({ message: 'second', session_id: 'sess_1' });
  });

  it('shows a request error on the reply', async () => {
    const { user } = renderApp({ chats: [{ status: 503, detail: 'OPENAI_API_KEY is not set.' }] });
    await user.type(screen.getByLabelText('Message'), 'hi{Enter}');
    expect(await screen.findByRole('alert')).toHaveTextContent('OPENAI_API_KEY is not set.');
  });

  it('stops a running reply', async () => {
    const { user } = renderApp({
      chats: [
        { hangAfter: [{ type: 'model_token', data: { ...base, step: 1, text: 'Partial reply' } }] },
      ],
    });

    await user.type(screen.getByLabelText('Message'), 'long task{Enter}');
    await screen.findByText('Partial reply');
    await user.click(screen.getByRole('button', { name: 'Stop the agent' }));

    expect(await screen.findByText(/Stopped\. This reply was not saved/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send message' })).toBeInTheDocument();
  });

  it('uploads an attachment and tells the agent its path', async () => {
    const { server, user } = renderApp({
      chats: [[{ type: 'final_answer', data: { ...base, step: 1, content: 'Read it.' } }]],
    });
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input) throw new Error('file input missing');

    await user.upload(input, new File(['%PDF'], 'report.pdf', { type: 'application/pdf' }));
    await waitFor(() => {
      expect(screen.queryByText('uploading…')).not.toBeInTheDocument();
    });
    await user.type(screen.getByLabelText('Message'), 'Summarise it{Enter}');
    await screen.findByText('Read it.');

    const chat = server.requests.find((r) => r.url.endsWith('/v1/chat/stream'));
    expect((chat?.body as { message: string }).message).toContain('- uploads/report.pdf');
  });

  it('starts a new conversation', async () => {
    const { server, user } = renderApp({
      chats: [
        writeFileRun,
        [{ type: 'final_answer', data: { ...base, step: 1, content: 'Fresh.' } }],
      ],
    });

    await user.type(screen.getByLabelText('Message'), 'first{Enter}');
    await screen.findByText(/4,722 tokens/);
    await user.click(screen.getByRole('button', { name: /New chat/ }));
    expect(screen.queryByText('first')).not.toBeInTheDocument();

    await user.type(screen.getByLabelText('Message'), 'second{Enter}');
    await screen.findByText('Fresh.');
    const last = server.requests.filter((r) => r.url.endsWith('/v1/chat/stream')).at(-1);
    expect(last?.body).not.toHaveProperty('session_id');
  });

  it('warns when the server is unreachable and disables the composer', async () => {
    renderApp({ offline: true });
    // The sidebar reports it too (tools couldn't load); the chat banner is the one to act on.
    const chat = screen.getByRole('main');
    expect(await within(chat).findByText(/Cannot reach the agent server/)).toBeInTheDocument();
    expect(screen.getByLabelText('Message')).toBeDisabled();
  });

  it('browses for a workspace folder, shows its path and runs the agent there', async () => {
    const { server, user } = renderApp({ chats: [writeFileRun] });
    const sidebar = screen.getByRole('complementary', { name: 'Tools and settings' });
    expect(await within(sidebar).findByText('/tmp/ws')).toBeInTheDocument();

    await user.click(within(sidebar).getByRole('button', { name: 'Browse…' }));
    const dialog = screen.getByRole('dialog', { name: 'Choose a folder' });
    await user.click(await within(dialog).findByRole('button', { name: 'Up one folder' }));
    await user.click(await within(dialog).findByRole('button', { name: /project/ }));
    await waitFor(() => {
      expect(within(dialog).getByRole('button', { name: 'Use this folder' })).toBeEnabled();
    });
    await user.click(within(dialog).getByRole('button', { name: 'Use this folder' }));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(within(sidebar).getByText('/tmp/project')).toBeInTheDocument();
    expect(window.localStorage.getItem('agent-runtime:workspace')).toBe('/tmp/project');

    await user.type(screen.getByLabelText('Message'), 'make a plan{Enter}');
    await screen.findByText(/4,722 tokens/);
    const chat = server.requests.find((r) => r.url.endsWith('/v1/chat/stream'));
    expect(chat?.body).toMatchObject({ workspace: '/tmp/project' });

    await user.click(screen.getByRole('button', { name: /Download plan\.docx/ }));
    const download = server.requests.find((r) => r.url.includes('/v1/files/plan.docx'));
    expect(download?.url).toContain('workspace=%2Ftmp%2Fproject');

    await user.click(within(sidebar).getByRole('button', { name: 'Use default' }));
    expect(within(sidebar).getByText('/tmp/ws')).toBeInTheDocument();
  });

  it('lists stored conversations, reopens one, and continues it', async () => {
    const stored: SessionDetail = {
      id: 'sess_old',
      title: 'Quarterly plan',
      model: 'gpt-4o',
      workspace: '/tmp/project',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      run_count: 1,
      usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2, cost_usd: 0.01 },
      runs: [
        {
          id: 'run_old',
          status: 'completed',
          user_message: 'Draft the plan',
          model: 'gpt-4o',
          workspace: '/tmp/project',
          answer: 'Here is the plan.',
          error: null,
          steps_used: 1,
          tool_call_count: 0,
          usage: { input_tokens: 1, output_tokens: 1, total_tokens: 2, cost_usd: 0.01 },
          started_at: new Date().toISOString(),
          finished_at: null,
          duration_s: 1,
          events: [
            {
              type: 'final_answer',
              data: { ...base, session_id: 'sess_old', step: 1, content: 'Here is the plan.' },
              created_at: new Date().toISOString(),
            },
          ],
        },
      ],
    };
    const { server, user } = renderApp({ sessions: [stored], chats: [writeFileRun] });
    const sidebar = screen.getByRole('complementary', { name: 'Tools and settings' });

    await user.click(await within(sidebar).findByRole('button', { name: /^Quarterly plan/ }));

    const chat = screen.getByRole('main');
    expect(await within(chat).findByText('Draft the plan')).toBeInTheDocument();
    expect(within(chat).getByText('Here is the plan.')).toBeInTheDocument();
    // The conversation's folder comes back with it.
    expect(within(sidebar).getByText('/tmp/project')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Message'), 'more{Enter}');
    await screen.findByText(/4,722 tokens/);
    const sent = server.requests.find((r) => r.url.endsWith('/v1/chat/stream'));
    expect(sent?.body).toMatchObject({ session_id: 'sess_old', workspace: '/tmp/project' });

    // (The scripted reply came back as another session; reopen this one.)
    await user.click(within(sidebar).getByRole('button', { name: /^Quarterly plan/ }));
    await within(chat).findByText('Draft the plan');
    await user.click(within(sidebar).getByRole('button', { name: 'Delete “Quarterly plan”' }));
    await user.click(within(sidebar).getByRole('button', { name: 'Delete' }));
    expect(await within(sidebar).findByText(/No conversations yet/)).toBeInTheDocument();
    // Deleting the open conversation clears the chat.
    expect(within(chat).queryByText('Draft the plan')).not.toBeInTheDocument();
  });

  it('hides conversations when the server keeps no history', async () => {
    renderApp();
    const sidebar = screen.getByRole('complementary', { name: 'Tools and settings' });
    await within(sidebar).findByText('Connected');
    expect(within(sidebar).queryByText('Conversations')).not.toBeInTheDocument();
  });
});
