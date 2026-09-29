/**
 * The waiting state.
 *
 * The behaviour worth protecting is not the animation - it is that every
 * stage after the first names something the server actually reported. A
 * progress indicator that scripts "Analysing / Cross-referencing / Verifying"
 * on a timer is a lie, and this product's whole claim is that its activity
 * trace is derived from the running system rather than asserted.
 *
 * So these tests check what is *said*, not how it moves.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PreparingState } from './PreparingState';

describe('PreparingState', () => {
  it('opens with a generic line, because nothing has happened yet', () => {
    render(<PreparingState stage={null} steps={null} />);
    expect(screen.getByText('Getting your answer ready')).toBeInTheDocument();
  });

  it('names the real tool the server reported running', () => {
    render(
      <PreparingState
        stage={{ key: 'tool:read_document', label: 'Running read_document' }}
        steps={null}
      />,
    );
    expect(screen.getByText('Running read_document')).toBeInTheDocument();
  });

  it('shows the real passage and document counts', () => {
    render(
      <PreparingState
        stage={{ key: 'sources', label: 'Reading 5 passages from 2 documents' }}
        steps={null}
      />,
    );
    expect(screen.getByText('Reading 5 passages from 2 documents')).toBeInTheDocument();
  });

  it('surfaces the most recent pipeline steps, not the bookkeeping ones', () => {
    render(
      <PreparingState
        stage={{ key: 'sources', label: 'Reading 5 passages from 2 documents' }}
        steps={[
          { label: 'Task received', status: 'done' },
          { label: 'Message stored in conversation history', status: 'done' },
          { label: 'SI-1: Engaged the Maintenance Intelligence specialist.', status: 'done' },
          { label: 'Retrieved 5 passage(s) from 2 document(s)', status: 'done' },
        ]}
      />,
    );

    // The interesting tail is shown...
    expect(screen.getByText(/Engaged the Maintenance Intelligence/)).toBeInTheDocument();
    expect(screen.getByText(/Retrieved 5 passage/)).toBeInTheDocument();
    // ...and the noise is not.
    expect(screen.queryByText('Task received')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Message stored in conversation history'),
    ).not.toBeInTheDocument();
  });

  it('renders without steps at all', () => {
    const { container } = render(<PreparingState stage={null} steps={undefined} />);
    expect(container.querySelector('.preparing-steps')).toBeNull();
    expect(container.querySelector('.preparing-skeleton')).not.toBeNull();
  });

  it('announces itself politely to assistive technology', () => {
    render(<PreparingState stage={null} steps={null} />);
    const status = screen.getByRole('status');
    expect(status).toHaveAttribute('aria-live', 'polite');
  });

  it('remounts the label per stage so the transition replays', () => {
    // The key is what makes one phrase hand over to the next instead of
    // swapping in place; a changed label with a stale key would not animate.
    const { container, rerender } = render(
      <PreparingState stage={{ key: 'start', label: 'Getting your answer ready' }} steps={null} />,
    );
    const first = container.querySelector('.preparing-label');

    rerender(
      <PreparingState stage={{ key: 'sources', label: 'Reading 5 passages from 2 documents' }} steps={null} />,
    );
    const second = container.querySelector('.preparing-label');

    expect(second).not.toBe(first);
    expect(second.textContent).toBe('Reading 5 passages from 2 documents');
  });
});
