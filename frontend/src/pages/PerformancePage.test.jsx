/**
 * Performance page tests.
 *
 * The point of shipping this shell is that it says what it is. A section
 * that renders invented figures to look finished is the one thing this
 * project does not do, so the tests pin that both panels are labelled
 * unbuilt and that nothing here claims otherwise.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';

const context = {
  currentUser: {
    id: 'user-sanyam',
    name: 'Sanyam Jain',
    accessLevel: 'OWNER',
  },
};

vi.mock('../state/AppContext', () => ({ useApp: () => context }));

const { PerformancePage } = await import('./PerformancePage');

describe('PerformancePage', () => {
  beforeEach(() => {
    context.currentUser = {
      id: 'user-sanyam',
      name: 'Sanyam Jain',
      accessLevel: 'OWNER',
    };
  });

  it('offers both panels, each marked as not built yet', () => {
    render(<PerformancePage />);

    expect(screen.getByText('Employee Performance')).toBeInTheDocument();
    expect(screen.getByText('Public Demand')).toBeInTheDocument();

    // One badge per panel. A shell that does not say it is a shell is worse
    // than no shell at all.
    expect(screen.getAllByText('Coming soon')).toHaveLength(2);
  });

  it('opens a panel in place, saying what it would take to build', async () => {
    const user = userEvent.setup();
    render(<PerformancePage />);

    await user.click(screen.getByText('Employee Performance'));

    // The other panel is gone: this replaces the view rather than expanding
    // beside it, which is what "opens in the big area" means.
    expect(screen.queryByText('Public Demand')).not.toBeInTheDocument();
    expect(screen.getByText(/audit trail aggregated per user/i)).toBeInTheDocument();
  });

  it('goes back to the list', async () => {
    const user = userEvent.setup();
    render(<PerformancePage />);

    await user.click(screen.getByText('Public Demand'));
    expect(screen.queryByText('Employee Performance')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /performance/i }));
    expect(screen.getByText('Employee Performance')).toBeInTheDocument();
  });

  it('is not shown to a non-administrator', () => {
    context.currentUser = { id: 'user-ananya', accessLevel: 'EMPLOYEE' };
    render(<PerformancePage />);

    expect(screen.queryByText('Employee Performance')).not.toBeInTheDocument();
    expect(screen.getByText(/available to helpdesk administrators/i)).toBeInTheDocument();
  });
});
