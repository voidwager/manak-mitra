import React from 'react';

/**
 * The Manak Mitra mark, inline.
 *
 * Inline rather than an <img> for one reason that matters: `currentColor`
 * does not cross an <img> boundary. An SVG loaded through a src attribute is
 * its own document and resolves currentColor against its own defaults - so
 * the mark would render black and disappear against the dark theme, and
 * inverting it in CSS would only move the problem to the light theme.
 *
 * Inlined, it inherits `color` from whatever it sits in. This is the
 * fallback for when the file in public/ does not load, and draws the same
 * seal-and-tick as that file.
 */
export const Wordmark = ({ height = 22, className = '' }) => (
  <svg
    className={className}
    height={height}
    viewBox="0 0 430 100"
    role="img"
    aria-label="Manak Mitra"
    style={{ display: 'block', width: 'auto' }}
  >
    <g
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* A seal: the round form of a certification mark. */}
      <circle cx="50" cy="50" r="40" strokeWidth="7" />
      <circle cx="50" cy="50" r="29" strokeWidth="2.5" strokeDasharray="3 5" />
      {/* The tick: conformity. */}
      <path d="M33 51 L45 63 L68 37" strokeWidth="8" />
    </g>
    <text
      x="108"
      y="66"
      fill="currentColor"
      fontFamily="'Plus Jakarta Sans', 'Segoe UI', Arial, sans-serif"
      fontSize="46"
      fontWeight="700"
      letterSpacing="-0.5"
    >
      Manak Mitra
    </text>
  </svg>
);

export default Wordmark;
