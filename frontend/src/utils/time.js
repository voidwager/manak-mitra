/**
 * Chat bubble clock labels.
 *
 * The API sends `createdAt` as a timezone-aware UTC instant. It deliberately
 * does not send a rendered string: a server in one timezone cannot know what
 * time it is where the reader is sitting, and the previous version of this
 * shipped a pre-rendered "10:24 AM" that was the server's local clock for
 * live messages and a literal hardcoded constant for seeded ones - which is
 * how a single thread ended up showing 1:43 AM, 2:05 AM and 10:24 AM at once.
 *
 * Formatting happens here instead, in the viewer's own locale and timezone.
 */

/**
 * "10:24 AM" in the viewer's locale.
 *
 * Returns an empty string rather than a guess when the instant is missing or
 * unparseable. A blank space above a bubble is honest; an invented time is
 * not, and this product cannot afford to display numbers it made up.
 */
export function formatClock(value) {
  if (!value) return '';

  const when = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(when.getTime())) return '';

  const label = when.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

  // Some locales render the meridiem lowercase ("2:05 am"); the interface sets
  // it uppercase everywhere else. Only the trailing am/pm is touched, so a
  // 24-hour locale - which has no meridiem at all - passes through unchanged.
  return label.replace(/\b([ap])\.?m\.?$/i, (match) => match.toUpperCase());
}

/** "12 September 2026, 10:24" - used where a bubble needs the full instant. */
export function formatDateTime(value) {
  if (!value) return '';

  const when = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(when.getTime())) return '';

  return when.toLocaleString([], {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

export default formatClock;
