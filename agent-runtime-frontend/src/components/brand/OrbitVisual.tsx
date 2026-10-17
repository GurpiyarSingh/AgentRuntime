/**
 * The runtime at the centre, its capabilities in orbit: the login page's
 * hero. Pure CSS animation (rings turn, chips stay upright); decorative,
 * so hidden from assistive technology, and still under reduced motion.
 */

import type { CSSProperties } from 'react';

import type { Tone } from '../../lib/toolMeta';
import { Icon, type IconName } from '../Icon';
import { Logo } from './Logo';
import styles from './OrbitVisual.module.css';

interface Satellite {
  icon: IconName;
  tone: Tone;
  angle: number;
}

interface Ring {
  /** Diameter as a fraction of the visual. */
  scale: number;
  /** Seconds per turn; negative turns the other way. */
  period: number;
  satellites: Satellite[];
}

const RINGS: Ring[] = [
  {
    scale: 0.44,
    period: 40,
    satellites: [
      { icon: 'fileText', tone: 'blue', angle: 20 },
      { icon: 'image', tone: 'pink', angle: 200 },
    ],
  },
  {
    scale: 0.7,
    period: -64,
    satellites: [
      { icon: 'table', tone: 'green', angle: 70 },
      { icon: 'code', tone: 'violet', angle: 190 },
      { icon: 'search', tone: 'cyan', angle: 310 },
    ],
  },
  {
    scale: 0.96,
    period: 96,
    satellites: [
      { icon: 'terminal', tone: 'amber', angle: 0 },
      { icon: 'globe', tone: 'blue', angle: 95 },
      { icon: 'filePlus', tone: 'green', angle: 165 },
      { icon: 'bolt', tone: 'pink', angle: 250 },
    ],
  },
];

const SPARKS = [
  { x: 12, y: 18, delay: 0 },
  { x: 86, y: 12, delay: 1.2 },
  { x: 92, y: 64, delay: 2.1 },
  { x: 8, y: 78, delay: 0.6 },
  { x: 48, y: 4, delay: 1.8 },
  { x: 62, y: 94, delay: 2.6 },
  { x: 28, y: 52, delay: 3.1 },
  { x: 74, y: 36, delay: 0.9 },
];

export function OrbitVisual({ className }: { className?: string | undefined }) {
  return (
    <div className={`${styles.orbit ?? ''} ${className ?? ''}`} aria-hidden="true">
      <div className={styles.halo} />
      {SPARKS.map((spark, index) => (
        <span
          key={index}
          className={styles.spark}
          style={{ left: `${spark.x}%`, top: `${spark.y}%`, animationDelay: `${spark.delay}s` }}
        />
      ))}

      {RINGS.map((ring, index) => (
        <div
          key={index}
          className={styles.ring}
          style={
            {
              '--scale': ring.scale,
              '--period': `${Math.abs(ring.period)}s`,
              '--direction': ring.period < 0 ? 'reverse' : 'normal',
              '--counter': ring.period < 0 ? 'normal' : 'reverse',
            } as CSSProperties
          }
        >
          {ring.satellites.map((satellite) => (
            <span
              key={satellite.angle}
              className={styles.slot}
              style={{ '--angle': `${satellite.angle}deg` } as CSSProperties}
            >
              <span className={styles.satellite} data-tone={satellite.tone}>
                <Icon name={satellite.icon} size={20} />
              </span>
            </span>
          ))}
        </div>
      ))}

      <div className={styles.core}>
        <span className={styles.pulse} />
        <span className={styles.pulse} style={{ animationDelay: '1.6s' }} />
        <Logo size={84} className={styles.logo} />
      </div>
    </div>
  );
}
