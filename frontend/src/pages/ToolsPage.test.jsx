/**
 * Tools page tests.
 *
 * Before Phase 11 every enabled tool read "Active for Agents", including
 * ones with no implementation behind them. These tests pin the three states
 * apart, because collapsing them is exactly the regression that would put a
 * false claim back on the page.
 *
 * The fixtures below are the wire shape the API actually returns, and that
 * is load-bearing. An earlier version of this file modelled a switched-off
 * tool as `executable: true` - which the backend never sends, because a
 * tool an operator has switched off is by definition not callable. The
 * tests passed against a response that could not occur, and the page
 * shipped with its switch gated on the wrong field: turning a tool off
 * disabled its own control, and nothing here noticed.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const toggleToolState = vi.fn();

let tools = [];

vi.mock('../state/AppContext', () => ({
  useApp: () => ({ tools, toggleToolState }),
}));

const { ToolsPage } = await import('./ToolsPage');

const CALLABLE = {
  id: 'calculator',
  name: 'Calculator',
  category: 'Utility',
  description: 'Evaluate an arithmetic expression exactly.',
  enabled: true,
  implemented: true,
  executable: true,
  unavailableReason: '',
  wireName: 'calculator',
};

// Built, but the operator switched it off - so it is not callable, and the
// API says so. `executable: false` here is the whole point of the fixture.
const SWITCHED_OFF = {
  ...CALLABLE,
  id: 'doc-search',
  name: 'Document Search',
  enabled: false,
  implemented: true,
  executable: false,
  unavailableReason: 'Switched off by an operator.',
};

const NOT_IMPLEMENTED = {
  id: 'img-analyzer',
  name: 'Image Analyzer',
  category: 'Vision',
  description: 'Vision analysis of equipment photos.',
  enabled: true,
  implemented: false,
  executable: false,
  unavailableReason: 'Needs the image pipeline, which is not built yet (Phase 13).',
  wireName: '',
};

beforeEach(() => {
  tools = [];
  toggleToolState.mockClear();
});

describe('ToolsPage', () => {
  it('reports a working, enabled tool as callable', () => {
    tools = [CALLABLE];
    render(<ToolsPage />);

    expect(screen.getByText('Callable by agents')).toBeInTheDocument();
    // The name the model sees is shown, so a trace entry can be matched back.
    expect(screen.getByText('calculator')).toBeInTheDocument();
  });

  it('distinguishes switched off from not implemented', () => {
    tools = [SWITCHED_OFF, NOT_IMPLEMENTED];
    render(<ToolsPage />);

    expect(screen.getByText('Switched off')).toBeInTheDocument();
    expect(screen.getByText('Not available yet')).toBeInTheDocument();
    expect(screen.queryByText('Callable by agents')).not.toBeInTheDocument();
  });

  it('never claims a tool with no implementation is active', () => {
    // The regression this whole page was fixed for: `enabled: true` on a
    // tool that cannot run used to read "Active for Agents".
    tools = [NOT_IMPLEMENTED];
    render(<ToolsPage />);

    expect(screen.queryByText(/Active for Agents/i)).not.toBeInTheDocument();
    expect(screen.queryByText('Callable by agents')).not.toBeInTheDocument();
    expect(
      screen.getByText(/Needs the image pipeline/i),
    ).toBeInTheDocument();
  });

  it('does not let you toggle a tool that cannot run', async () => {
    tools = [NOT_IMPLEMENTED];
    render(<ToolsPage />);

    const toggle = screen.getByRole('button', {
      name: /image pipeline/i,
    });
    expect(toggle).toBeDisabled();

    await userEvent.click(toggle, { pointerEventsCheck: 0 });
    expect(toggleToolState).not.toHaveBeenCalled();
  });

  it('lets you switch a tool back on after switching it off', async () => {
    // The bug this page shipped with. A switched-off tool is not callable,
    // the switch was gated on callability, so off was a one-way door.
    tools = [SWITCHED_OFF];
    render(<ToolsPage />);

    const toggle = screen.getByRole('button', {
      name: /Let agents call this tool/i,
    });
    expect(toggle).toBeEnabled();

    await userEvent.click(toggle);
    expect(toggleToolState).toHaveBeenCalledWith('doc-search');
  });

  it('does not mistake a switched-off tool for an unbuilt one', () => {
    // "Not available yet" means the feature does not exist. Saying that
    // about a switch the operator just flipped tells them their own action
    // was a missing feature.
    tools = [SWITCHED_OFF];
    render(<ToolsPage />);

    expect(screen.getByText('Switched off')).toBeInTheDocument();
    expect(screen.queryByText('Not available yet')).not.toBeInTheDocument();
  });

  it('toggles a tool that can run', async () => {
    tools = [CALLABLE];
    render(<ToolsPage />);

    await userEvent.click(
      screen.getByRole('button', { name: /Stop agents calling this tool/i }),
    );
    expect(toggleToolState).toHaveBeenCalledWith('calculator');
  });
});
