/**
 * The front door: an animated hero that says what the runtime is, and a
 * sign-in card. On a brand-new server the card instead creates the first
 * (admin) account.
 */

import { useId, useState, type ReactNode, type SubmitEvent } from 'react';

import { useApi } from '../../api/ApiContext';
import { ApiError } from '../../api/client';
import type { LoginResponse } from '../../api/types';
import { MIN_PASSWORD, passwordStrength } from '../../lib/password';
import { Logo } from '../brand/Logo';
import { OrbitVisual } from '../brand/OrbitVisual';
import { Icon, type IconName } from '../Icon';
import styles from './LoginPage.module.css';

const CAPABILITIES: { icon: IconName; text: string }[] = [
  { icon: 'fileText', text: 'Reads any document' },
  { icon: 'image', text: 'Sees images' },
  { icon: 'filePlus', text: 'Creates Word, Excel, PDF' },
  { icon: 'activity', text: 'Every step on record' },
];

interface LoginPageProps {
  mode: 'login' | 'setup';
  onSignedIn: (response: LoginResponse) => void;
  /** Shown above the form, e.g. after a session expired. */
  notice?: string | undefined;
}

const STRENGTH_LABELS = ['Too short', 'Weak', 'Fair', 'Good', 'Strong'];

function Field({
  icon,
  label,
  children,
  hint,
}: {
  icon: IconName;
  label: string;
  children: (id: string) => ReactNode;
  hint?: ReactNode;
}) {
  const id = useId();
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      <div className={styles.control}>
        <Icon name={icon} size={17} className={styles.fieldIcon} />
        {children(id)}
      </div>
      {hint}
    </div>
  );
}

export function LoginPage({ mode, onSignedIn, notice }: LoginPageProps) {
  const client = useApi();
  const setup = mode === 'setup';
  const [displayName, setDisplayName] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [reveal, setReveal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  // Bumped on each failure, so the card shakes again even for the same error.
  const [attempt, setAttempt] = useState(0);
  const strength = passwordStrength(password);

  const fail = (message: string) => {
    setError(message);
    setAttempt((n) => n + 1);
  };

  const submit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    if (setup) {
      if (password.length < MIN_PASSWORD) {
        fail(`Use at least ${MIN_PASSWORD} characters for the password.`);
        return;
      }
      if (password !== confirm) {
        fail("The passwords don't match.");
        return;
      }
    }
    setBusy(true);
    setError('');
    try {
      const response = setup
        ? await client.setup({ username, password, display_name: displayName })
        : await client.login(username, password);
      onSignedIn(response);
    } catch (reason) {
      fail(reason instanceof ApiError ? reason.message : 'Something went wrong. Try again.');
      setBusy(false);
    }
  };

  return (
    <div className={styles.page}>
      <section className={styles.hero} aria-label="About Agent Runtime">
        <div className={styles.aurora} aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className={styles.grid} aria-hidden="true" />

        <div className={styles.heroInner}>
          <div className={styles.brand}>
            <Logo size={34} />
            <span className={styles.brandName}>Agent Runtime</span>
            <span className={styles.brandTag}>
              <span className={styles.liveDot} />
              Online
            </span>
          </div>

          <OrbitVisual className={styles.orbit} />

          <div className={styles.pitch}>
            <h2 className={styles.headline}>
              One runtime.
              <br />
              <span className="gradient-text">Limitless capability.</span>
            </h2>
            <p className={styles.tagline}>
              An autonomous agent that reads, writes, sees and builds across your files, and shows
              its work at every step.
            </p>
            <ul className={styles.capabilities}>
              {CAPABILITIES.map((capability) => (
                <li key={capability.text}>
                  <Icon name={capability.icon} size={15} />
                  {capability.text}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <main className={styles.panel}>
        <form
          key={attempt}
          className={`${styles.card ?? ''} ${attempt > 0 ? (styles.shake ?? '') : ''}`}
          onSubmit={(event) => void submit(event)}
          aria-labelledby="auth-title"
          noValidate
        >
          <span className={styles.eyebrow}>
            <Icon name={setup ? 'sparkles' : 'shield'} size={14} />
            {setup ? 'First-time setup' : 'Secure sign-in'}
          </span>
          <h1 id="auth-title" className={styles.title}>
            {setup ? 'Create your admin account' : 'Welcome back'}
          </h1>
          <p className={styles.subtitle}>
            {setup ? (
              <>
                You&apos;re the first one here, so this account becomes the admin. Add teammates
                later with <code>agent-runtime users add</code>.
              </>
            ) : (
              'Sign in to pick up where your agent left off.'
            )}
          </p>

          {notice && !error && (
            <p className={styles.notice} role="status">
              <Icon name="history" size={15} />
              {notice}
            </p>
          )}
          {error && (
            <p className={styles.error} role="alert">
              <Icon name="alert" size={15} />
              {error}
            </p>
          )}

          {setup && (
            <Field icon="sparkles" label="Your name (optional)">
              {(id) => (
                <input
                  id={id}
                  className={styles.input}
                  value={displayName}
                  autoComplete="name"
                  maxLength={100}
                  placeholder="Ada Lovelace"
                  onChange={(event) => {
                    setDisplayName(event.target.value);
                  }}
                />
              )}
            </Field>
          )}

          <Field icon="user" label="Username">
            {(id) => (
              <input
                id={id}
                className={styles.input}
                value={username}
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                required
                autoFocus={!setup}
                placeholder={setup ? 'admin' : 'Your username'}
                onChange={(event) => {
                  setUsername(event.target.value);
                }}
              />
            )}
          </Field>

          <Field
            icon="lock"
            label="Password"
            hint={
              setup && password ? (
                <div className={styles.strength} data-score={strength}>
                  <span className={styles.meter}>
                    {[1, 2, 3, 4].map((step) => (
                      <span key={step} data-on={strength >= step} />
                    ))}
                  </span>
                  <span>{STRENGTH_LABELS[strength]}</span>
                </div>
              ) : undefined
            }
          >
            {(id) => (
              <>
                <input
                  id={id}
                  className={styles.input}
                  type={reveal ? 'text' : 'password'}
                  value={password}
                  autoComplete={setup ? 'new-password' : 'current-password'}
                  required
                  placeholder={setup ? `At least ${MIN_PASSWORD} characters` : '••••••••'}
                  onChange={(event) => {
                    setPassword(event.target.value);
                  }}
                />
                <button
                  type="button"
                  className={styles.reveal}
                  onClick={() => {
                    setReveal((value) => !value);
                  }}
                >
                  <Icon
                    name={reveal ? 'eyeOff' : 'eye'}
                    size={17}
                    label={reveal ? 'Hide password' : 'Show password'}
                  />
                </button>
              </>
            )}
          </Field>

          {setup && (
            <Field icon="lock" label="Confirm password">
              {(id) => (
                <input
                  id={id}
                  className={styles.input}
                  type={reveal ? 'text' : 'password'}
                  value={confirm}
                  autoComplete="new-password"
                  required
                  placeholder="Type it again"
                  onChange={(event) => {
                    setConfirm(event.target.value);
                  }}
                />
              )}
            </Field>
          )}

          <button
            type="submit"
            className={styles.submit}
            disabled={busy || !username.trim() || !password}
          >
            {busy ? (
              <>
                <Icon name="spinner" size={18} className={styles.spinner} />
                {setup ? 'Creating account…' : 'Signing in…'}
              </>
            ) : (
              <>
                {setup ? 'Create account & continue' : 'Sign in'}
                <Icon name="arrowRight" size={18} />
              </>
            )}
          </button>
        </form>

        <p className={styles.footnote}>
          <Icon name="shield" size={14} />
          Passwords are hashed with scrypt · your conversations are private to you
        </p>
      </main>
    </div>
  );
}
