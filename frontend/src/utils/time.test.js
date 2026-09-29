/**
 * Chat bubble clock labels.
 *
 * The bug this pins down: a single thread could display 1:43 AM, 2:05 AM and
 * 10:24 AM at the same time. Two causes, both covered here by consequence -
 * the API used to send a *rendered* string built from the server's naive local
 * clock, and the UI fell back to a hardcoded '10:24 AM' whenever that string
 * was empty (a new streaming bubble, or a seeded row).
 *
 * So the rule under test is: format a real instant, or return nothing. Never
 * substitute a plausible-looking time. This product displays numbers people
 * act on; an invented clock reading is the same class of error as an invented
 * citation.
 *
 * The assertions stay behavioural rather than comparing against a second copy
 * of the formatter's own regex - a test that re-implements the code under test
 * only proves the two copies match.
 */

import { describe, expect, it } from 'vitest';
import { formatClock, formatDateTime } from './time';

/** The hour/minute the viewer should see, in either 12- or 24-hour form. */
const expectedClockPattern = (when) => {
  const minutes = String(when.getMinutes()).padStart(2, '0');
  const h24 = when.getHours();
  const h12 = ((h24 + 11) % 12) + 1;
  return new RegExp(`(^|\\D)(${h24}|${h12}):${minutes}(\\D|$)`);
};

describe('formatClock', () => {
  it('renders an ISO instant in the local timezone of whoever is reading', () => {
    const when = new Date(2026, 8, 12, 14, 5, 0);
    expect(formatClock(when.toISOString())).toMatch(expectedClockPattern(when));
  });

  it('accepts a Date as well as a string', () => {
    const when = new Date(2026, 8, 12, 9, 30, 0);
    expect(formatClock(when)).toBe(formatClock(when.toISOString()));
  });

  it('reads a naive-looking UTC instant as UTC, not as local time', () => {
    // The API stamps a 'Z' precisely so this cannot drift. Without it the
    // browser would read the server's UTC instant as local and render a time
    // hours away from the truth.
    const withOffset = formatClock('2026-09-12T14:05:00Z');
    const asUtc = new Date(Date.UTC(2026, 8, 12, 14, 5, 0));
    expect(withOffset).toMatch(expectedClockPattern(asUtc));
  });

  it('uppercases the meridiem so it matches the rest of the interface', () => {
    const out = formatClock(new Date(2026, 8, 12, 14, 5, 0).toISOString());
    expect(out).not.toMatch(/[ap]\.?m\.?$/); // lowercase am/pm must not survive
  });

  it.each([undefined, null, '', 'not-a-date'])(
    'returns an empty string rather than inventing a time for %p',
    (value) => {
      expect(formatClock(value)).toBe('');
    },
  );

  it('never falls back to the hardcoded 10:24 AM the UI used to print', () => {
    expect(formatClock(undefined)).not.toContain('10:24');
    expect(formatClock('')).not.toContain('10:24');
    expect(formatClock(null)).not.toContain('10:24');
  });
});

describe('formatDateTime', () => {
  it('includes the date as well as the time', () => {
    const out = formatDateTime(new Date(2026, 8, 12, 14, 5, 0));
    expect(out).toMatch(/2026/);
    expect(out).not.toBe('');
  });

  it('returns an empty string for a missing instant', () => {
    expect(formatDateTime(null)).toBe('');
  });
});
