import React from 'react';

/**
 * The SYNQ wordmark, inline.
 *
 * Inline rather than an <img> for one reason that matters: `currentColor`
 * does not cross an <img> boundary. An SVG loaded through a src attribute is
 * its own document and resolves currentColor against its own defaults - so
 * the mark would render black and disappear against the black build, and
 * inverting it in CSS would only move the problem to the light theme.
 *
 * Inlined, it inherits `color` from whatever it sits in. White on black,
 * black on white, one definition, no second asset to keep in step.
 *
 * The letterforms are drawn as stroked centre-lines rather than filled
 * outlines. The mark is a constant-width angular ribbon, which is exactly
 * what a miter-joined stroke produces, and it keeps this to a dozen
 * coordinates instead of several hundred.
 */
export const SynqWordmark = ({ height = 22, className = '' }) => (
  <svg
    className={className}
    height={height}
    viewBox="0 0 392 120"
    role="img"
    aria-label="SYNQ"
    style={{ display: 'block', width: 'auto' }}
  >
    <g
      fill="none"
      stroke="currentColor"
      strokeWidth="19"
      strokeLinecap="butt"
      strokeLinejoin="miter"
      strokeMiterlimit="12"
    >
      {/* S: top bar, down-left, middle bar, down-right, bottom bar. */}
      <path d="M92 20 H36 L18 38 V50 H74 L92 68 V80 L74 98 H14" />

      {/* Y: two diagonals into a stem. */}
      <path d="M118 20 L155 63 L192 20" />
      <path d="M155 63 V98" />

      {/* N: up, diagonal, up. */}
      <path d="M220 98 V20 L276 98 V20" />

      {/* Q: ring, plus the tail cutting out through the lower right. */}
      <circle cx="337" cy="59" r="38" />
      <path d="M352 76 L384 108" />
    </g>
  </svg>
);

export default SynqWordmark;
