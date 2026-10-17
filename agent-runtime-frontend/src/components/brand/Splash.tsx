/** Full-screen placeholder while the app checks in with the server, or can't. */

import { Icon } from '../Icon';
import { Logo } from './Logo';
import styles from './Splash.module.css';

interface SplashProps {
  /** Show this failure (with a retry button) instead of the loading state. */
  error?: string;
  onRetry?: () => void;
}

export function Splash({ error, onRetry }: SplashProps) {
  return (
    <div className={styles.splash} role={error ? 'alert' : 'status'}>
      <div className={styles.mark}>
        {!error && <span className={styles.ring} />}
        <Logo size={64} />
      </div>
      {error ? (
        <>
          <p className={styles.title}>Can&apos;t reach the runtime</p>
          <p className={styles.detail}>{error}</p>
          {onRetry && (
            <button type="button" className={styles.retry} onClick={onRetry}>
              <Icon name="history" size={16} />
              Try again
            </button>
          )}
        </>
      ) : (
        <p className={styles.detail}>Starting the runtime…</p>
      )}
    </div>
  );
}
