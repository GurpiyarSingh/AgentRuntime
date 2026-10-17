/**
 * The front door, against a fake backend: first-run setup, signing in and
 * out, and servers without sign-in.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, vi } from 'vitest';

import { passwordStrength } from './lib/password';
import { Root } from './Root';
import { createFakeServer, type FakeServerOptions } from './test/fakeServer';

function renderRoot(options: FakeServerOptions = {}) {
  const server = createFakeServer(options);
  vi.stubGlobal('fetch', server.fetch);
  const user = userEvent.setup();
  render(<Root />);
  return { server, user };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const sidebar = () => screen.getByRole('complementary', { name: 'Tools and settings' });

describe('Root', () => {
  it('goes straight to the app when the server has no sign-in', async () => {
    renderRoot();
    const panel = await screen.findByRole('complementary', { name: 'Tools and settings' });
    expect(await within(panel).findByText('Connected')).toBeInTheDocument();
    expect(within(sidebar()).getByText('Local mode')).toBeInTheDocument();
  });

  it('creates the admin account on a brand-new server', async () => {
    const { server, user } = renderRoot({ accounts: {} });

    expect(
      await screen.findByRole('heading', { name: 'Create your admin account' }),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText('Username'), 'ada');
    await user.type(screen.getByLabelText('Password'), 'analytical engine');
    await user.type(screen.getByLabelText('Confirm password'), 'analytical engine');
    await user.click(screen.getByRole('button', { name: /Create account/ }));

    expect(await within(sidebar()).findByText('Ada Lovelace')).toBeInTheDocument();
    expect(window.localStorage.getItem('agent-runtime:token')).toBe('tok_ada_0');
    // Later requests carry the token.
    const tools = server.requests.filter((r) => r.url.endsWith('/v1/tools')).at(-1);
    expect(tools?.headers.get('Authorization')).toBe('Bearer tok_ada_0');
  });

  it('refuses mismatched passwords during setup', async () => {
    const { user } = renderRoot({ accounts: {} });

    await user.type(await screen.findByLabelText('Username'), 'ada');
    await user.type(screen.getByLabelText('Password'), 'analytical engine');
    await user.type(screen.getByLabelText('Confirm password'), 'something else');
    await user.click(screen.getByRole('button', { name: /Create account/ }));

    expect(await screen.findByRole('alert')).toHaveTextContent("The passwords don't match.");
  });

  it('signs in, shows wrong passwords, and signs out', async () => {
    const { user } = renderRoot({ accounts: { grace: 'compiler1952' } });

    await user.type(await screen.findByLabelText('Username'), 'grace');
    await user.type(screen.getByLabelText('Password'), 'nope');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong username or password.');

    await user.clear(screen.getByLabelText('Password'));
    await user.type(screen.getByLabelText('Password'), 'compiler1952');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await within(sidebar()).findByText('grace')).toBeInTheDocument();

    await user.click(within(sidebar()).getByRole('button', { name: 'Sign out' }));
    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument();
    expect(window.localStorage.getItem('agent-runtime:token')).toBeNull();
  });

  it('remembers a sign-in, and drops a token the server no longer accepts', async () => {
    window.localStorage.setItem('agent-runtime:token', 'tok_stale');
    renderRoot({ accounts: { grace: 'compiler1952' } });

    expect(await screen.findByRole('heading', { name: 'Welcome back' })).toBeInTheDocument();
    expect(window.localStorage.getItem('agent-runtime:token')).toBeNull();
  });

  it('shows a retry screen when the server is unreachable', async () => {
    renderRoot({ offline: true });
    expect(await screen.findByText("Can't reach the runtime")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});

describe('passwordStrength', () => {
  it('scores length, case mix and digits or symbols', () => {
    expect(passwordStrength('')).toBe(0);
    expect(passwordStrength('short')).toBe(0);
    expect(passwordStrength('abcdefgh')).toBe(1);
    expect(passwordStrength('abcdefghijkl')).toBe(2);
    expect(passwordStrength('Abcdefghijk1')).toBe(4);
  });
});
