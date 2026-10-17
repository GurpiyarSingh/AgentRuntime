/**
 * The Agent Runtime mark: a core with a satellite on a tilted orbit, on the
 * brand gradient. The orbit is the loop (think, act, observe); the
 * satellite is the agent out doing something.
 */

import { useId } from 'react';

interface LogoProps {
  size?: number;
  className?: string | undefined;
  /** Accessible name; decorative when omitted. */
  label?: string;
}

export function Logo({ size = 32, className, label }: LogoProps) {
  const id = useId();
  const fill = `${id}-fill`;
  const shine = `${id}-shine`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      className={className}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <defs>
        <linearGradient id={fill} x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#6366f1" />
          <stop offset="0.55" stopColor="#a855f7" />
          <stop offset="1" stopColor="#22d3ee" />
        </linearGradient>
        <radialGradient id={shine} cx="0.3" cy="0.2" r="0.9">
          <stop offset="0" stopColor="#fff" stopOpacity="0.35" />
          <stop offset="0.6" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="40" height="40" rx="11" fill={`url(#${fill})`} />
      <rect width="40" height="40" rx="11" fill={`url(#${shine})`} />
      <ellipse
        cx="20"
        cy="20"
        rx="13"
        ry="6.2"
        transform="rotate(-28 20 20)"
        fill="none"
        stroke="#fff"
        strokeOpacity="0.9"
        strokeWidth="2"
      />
      <circle cx="20" cy="20" r="4.4" fill="#fff" />
      <circle cx="30.6" cy="13.2" r="2.6" fill="#fff" />
    </svg>
  );
}
