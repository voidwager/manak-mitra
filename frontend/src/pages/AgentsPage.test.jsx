/**
 * Agents page tests.
 *
 * Two claims used to be hardcoded here and were both false in the general
 * case: every agent showed a green "Online" pill, and every card carried an
 * "On-Premise" badge regardless of where inference actually ran. Both are
 * now derived, and these tests fail if either reverts to a constant.
 */

import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const context = {
  agents: [],
  activeAgent: null,
  selectAgent: vi.fn(),
  setActiveTab: vi.fn(),
  setActiveModal: vi.fn(),
  deleteAgent: vi.fn(),
  currentUser: { id: 'user-sanyam', accessLevel: 'OWNER' },
  health: { inference: { onPremise: false } },
};

vi.mock('../state/AppContext', () => ({
  useApp: () => context,
}));

const { AgentsPage } = await import('./AgentsPage');

const READY_AGENT = {
  id: 'lab-locator',
  name: 'Lab Locator',
  description: 'Finds BIS-recognised labs by state.',
  icon: 'FileText',
  model: 'qwen/qwen3.8-27b',
  status: 'Ready',
  statusDetail: 'Everything this agent declares is available.',
  capabilities: [
    { label: 'Conversational answers', available: true, detail: 'Runs on qwen.' },
    {
      label: 'Document retrieval with citations',
      available: true,
      detail: 'Searches Laboratories.',
    },
  ],
  specialisations: ['Recognised labs by state'],
  tools: ['Document Search'],
  retrievalEnabled: true,
  folderScope: ['Laboratories'],
  isSystem: true,
  createdById: null,
};

const LIMITED_AGENT = {
  ...READY_AGENT,
  id: 'doc-vision',
  name: 'Mark & Label Reader',
  status: 'Limited',
  statusDetail: '1 of its declared capabilities cannot run yet.',
  capabilities: [
    { label: 'Conversational answers', available: true, detail: 'Runs on qwen.' },
    {
      label: 'Vision: Image Analyzer',
      available: false,
      detail: 'Needs a vision model. Multimodal support is not implemented yet.',
    },
  ],
  specialisations: ['OCR Text Extraction'],
  folderScope: [],
};

beforeEach(() => {
  context.agents = [];
  context.activeAgent = null;
  context.health = { inference: { onPremise: false } };
  context.isGuest = false;
});

describe('AgentsPage', () => {
  it('renders the derived status rather than a constant', () => {
    context.agents = [READY_AGENT, LIMITED_AGENT];
    render(<AgentsPage />);

    expect(screen.getByText('Ready')).toBeInTheDocument();
    expect(screen.getByText('Limited')).toBeInTheDocument();
    // The old hardcoded pill.
    expect(screen.queryByText('Online')).not.toBeInTheDocument();
  });

  it('shows an unavailable capability with its reason instead of hiding it', () => {
    context.agents = [LIMITED_AGENT];
    render(<AgentsPage />);

    const capability = screen.getByText('Vision: Image Analyzer');
    expect(capability).toBeInTheDocument();
    // The reason travels in the row's tooltip.
    expect(capability.closest('.cap-row')).toHaveClass('off');
    expect(capability.closest('.cap-row')).toHaveAttribute(
      'title',
      expect.stringContaining('vision model'),
    );
  });

  it('separates stated focus areas from real capabilities', () => {
    context.agents = [LIMITED_AGENT];
    render(<AgentsPage />);

    // "OCR Text Extraction" is the author's intent and must not appear as
    // something the agent can do.
    expect(screen.getByText(/Focus areas/i)).toBeInTheDocument();
    expect(screen.getByText('OCR Text Extraction')).toHaveClass('cap-tag');
  });

  it('reports where inference runs instead of always claiming on-premise', () => {
    context.agents = [READY_AGENT];
    context.health = { inference: { onPremise: false } };
    const { unmount } = render(<AgentsPage />);

    expect(screen.getByText('External model')).toBeInTheDocument();
    expect(screen.queryByText('On-Premise')).not.toBeInTheDocument();
    unmount();

    context.health = { inference: { onPremise: true } };
    render(<AgentsPage />);
    expect(screen.getByText('On-Premise')).toBeInTheDocument();
  });

  it('states the agent retrieval scope on the card', () => {
    context.agents = [READY_AGENT];
    render(<AgentsPage />);
    expect(screen.getByText('Searches Laboratories')).toBeInTheDocument();
  });

  it('says plainly when an agent does not search at all', () => {
    context.agents = [{ ...READY_AGENT, retrievalEnabled: false }];
    render(<AgentsPage />);
    expect(
      screen.getByText('Does not search the knowledge base'),
    ).toBeInTheDocument();
  });

  it('offers staff a way to create an agent', () => {
    render(<AgentsPage />);
    expect(screen.getByText('Create Agent')).toBeInTheDocument();
  });

  it('does not offer a visitor something the server will refuse', () => {
    // POST /agents is 403 for a visitor, because an agent is listed for
    // every user. A button that always fails reads as a broken site.
    context.isGuest = true;
    render(<AgentsPage />);
    expect(screen.queryByText('Create Agent')).not.toBeInTheDocument();
  });
});
