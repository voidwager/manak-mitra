/**
 * Whether the "Generate Report" button is offered.
 *
 * The gate has to agree with `app.services.reports.is_reportable`: offering
 * the button and then having the server refuse is worse than not offering it.
 */

import { describe, expect, it } from 'vitest';
import { isReportable } from './reports';

const reply = (over = {}) => ({ sender: 'assistant', text: '', ...over });

describe('isReportable', () => {
  it('offers a report for a short answer that cites a document', () => {
    // The length rule alone would throw this away, and it is exactly the
    // kind of answer a report should carry.
    expect(
      isReportable(reply({ text: '2.5 mm/s RMS [1].', sources: [{ title: 'SOP.pdf' }] })),
    ).toBe(true);
  });

  it('accepts the singular source field as well as the list', () => {
    expect(isReportable(reply({ text: 'Short.', source: { title: 'SOP.pdf' } }))).toBe(true);
  });

  it('offers a report for a long uncited analysis', () => {
    expect(isReportable(reply({ text: 'x'.repeat(250) }))).toBe(true);
  });

  it('does not offer one for a pleasantry', () => {
    expect(isReportable(reply({ text: 'Sure thing!' }))).toBe(false);
  });

  it('never offers one on a user message', () => {
    expect(isReportable({ sender: 'user', text: 'x'.repeat(250) })).toBe(false);
  });

  it('waits until the reply has finished streaming', () => {
    expect(
      isReportable(reply({ text: 'x'.repeat(250), streaming: true })),
    ).toBe(false);
  });

  it('handles a missing message without throwing', () => {
    expect(isReportable(null)).toBe(false);
    expect(isReportable(undefined)).toBe(false);
  });
});
