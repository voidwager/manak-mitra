/**
 * Documents page tests.
 *
 * The indexing states are the point. "Ready for indexing", "No extractable
 * text" and "Indexing failed" all mean the document is not searchable, but
 * only one is worth retrying and only one is the user's to fix - collapsing
 * them into a single grey badge is how someone ends up wondering why the
 * assistant cannot find their SOP.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const context = {
  documents: [],
  uploadDocFile: vi.fn(),
  indexDocument: vi.fn(),
  downloadDocFile: vi.fn(),
  deleteDocFile: vi.fn(),
  openDocPreview: vi.fn(),
  openDocSettings: vi.fn(),
  currentUser: {
    id: 'user-sanyam',
    name: 'Sanyam Jain',
    accessLevel: 'OWNER',
    scopeLabel: 'Full access',
    assignedFolders: ['All Units'],
  },
  health: {
    retrieval: { mode: 'lexical', summary: 'Keyword retrieval (BM25) only' },
  },
};

vi.mock('../state/AppContext', () => ({ useApp: () => context }));

const { DocumentsPage } = await import('./DocumentsPage');

const base = {
  id: 'doc-1',
  name: 'Centrifugal Pump Inspection SOP.pdf',
  type: 'PDF',
  size: '8.8 KB',
  date: '2026-09-01',
  folder: 'CDU-II',
  ownerId: 'user-sanyam',
  isConfidentialOwnerOnly: false,
  section: '4.2',
  chunks: 17,
  status: 'Indexed',
  indexError: '',
  hasStoredFile: true,
  isSemanticallyIndexed: false,
};

beforeEach(() => {
  context.documents = [];
});

describe('DocumentsPage indexing states', () => {
  it('shows chunk count for an indexed document', () => {
    context.documents = [base];
    render(<DocumentsPage />);
    expect(screen.getByText(/Indexed \(17 chunks\)/)).toBeInTheDocument();
  });

  it('does not claim semantic search when none was performed', () => {
    context.documents = [base];
    render(<DocumentsPage />);
    expect(screen.queryByText(/semantic/i)).not.toBeInTheDocument();
  });

  it('says so when a document is semantically indexed', () => {
    context.documents = [{ ...base, isSemanticallyIndexed: true }];
    render(<DocumentsPage />);
    expect(screen.getByText(/Indexed \(17 chunks, semantic\)/)).toBeInTheDocument();
  });

  it('distinguishes unsupported from failed, with the reason', () => {
    context.documents = [
      {
        ...base,
        id: 'doc-img',
        status: 'No extractable text',
        chunks: 0,
        indexError: 'Images carry no text layer. Reading one needs OCR.',
      },
      {
        ...base,
        id: 'doc-bad',
        status: 'Indexing failed',
        chunks: 0,
        indexError: 'Could not open the PDF.',
      },
    ];
    render(<DocumentsPage />);

    expect(screen.getByText('No extractable text')).toBeInTheDocument();
    expect(screen.getByText('Indexing failed')).toBeInTheDocument();
    expect(screen.getByText(/needs OCR/i)).toBeInTheDocument();
    expect(screen.getByText(/Could not open the PDF/i)).toBeInTheDocument();
  });

  it('files a personal upload under Private, not with the shared folders', () => {
    // `visibility` is derived by the server. The badge reads it rather than
    // comparing folder names here, so the label cannot claim privacy about
    // something the API would hand to somebody else.
    context.documents = [
      { ...base, folder: 'Personal Uploads', visibility: 'personal' },
    ];
    render(<DocumentsPage />);

    expect(screen.getByText('Private')).toBeInTheDocument();
    const tag = screen.getByText('My files').closest('.folder-tag');
    expect(tag).toHaveClass('personal');
    // The claim that matters: administrators are not an exception.
    expect(tag).toHaveAttribute(
      'title',
      expect.stringContaining('administrators included'),
    );
  });

  it('marks a restricted document as owner-clearance only', () => {
    context.documents = [
      { ...base, folder: 'Executive Confidential', visibility: 'restricted' },
    ];
    render(<DocumentsPage />);

    const tag = screen.getByText('Confidential').closest('.folder-tag');
    expect(tag).toHaveClass('restricted');
    expect(tag).toHaveAttribute('title', expect.stringContaining('owner clearance'));
  });

  it('lists a chat-scoped file apart from the knowledge base', () => {
    // It is a personal document with a conversation attached, and it must
    // not be filed as an ordinary personal one - it is searchable in that
    // chat alone, which is a different promise.
    context.documents = [
      {
        ...base,
        folder: 'Personal Uploads',
        visibility: 'personal',
        conversationId: 'conv-1',
      },
    ];
    render(<DocumentsPage />);

    const tag = screen.getByText('Chat files').closest('.folder-tag');
    expect(tag).toHaveClass('chat');
    expect(tag).toHaveAttribute('title', expect.stringContaining('that conversation only'));
    expect(screen.queryByText('My files')).not.toBeInTheDocument();
  });

  it('splits documents into Private and Public, Private first', () => {
    context.documents = [
      { ...base, id: 'a', name: 'Shared SOP.pdf', folder: 'CDU-II', visibility: 'shared' },
      { ...base, id: 'b', name: 'Audit.pdf', folder: 'Executive Confidential', visibility: 'restricted' },
      { ...base, id: 'c', name: 'My notes.pdf', folder: 'Personal Uploads', visibility: 'personal' },
    ];
    render(<DocumentsPage />);

    const sections = screen
      .getAllByRole('row')
      .filter((row) => row.className.includes('scope-section-row'))
      .map((row) => row.textContent);

    expect(sections).toHaveLength(2);
    expect(sections[0]).toContain('Private');
    expect(sections[1]).toContain('Public');

    // Private holds both the personal file and the restricted one; they are
    // separate scopes under one heading, not one merged permission.
    expect(screen.getByText('My files')).toBeInTheDocument();
    expect(screen.getByText('Confidential')).toBeInTheDocument();
    expect(screen.getByText('CDU-II')).toBeInTheDocument();

    // Every document is still listed.
    expect(screen.getByText('My notes.pdf')).toBeInTheDocument();
    expect(screen.getByText('Shared SOP.pdf')).toBeInTheDocument();
    expect(screen.getByText('Audit.pdf')).toBeInTheDocument();
  });

  it('collapsing a folder hides its documents but keeps the header', async () => {
    const user = userEvent.setup();
    context.documents = [
      { ...base, id: 'c', name: 'My notes.pdf', folder: 'Personal Uploads', visibility: 'personal' },
    ];
    render(<DocumentsPage />);

    expect(screen.getByText('My notes.pdf')).toBeInTheDocument();

    await user.click(screen.getByText('My files'));

    expect(screen.queryByText('My notes.pdf')).not.toBeInTheDocument();
    expect(screen.getByText('My files')).toBeInTheDocument();
  });

  it('a search result is never hidden behind a collapsed folder', async () => {
    // Otherwise a hit inside a folder the user collapsed earlier reads as
    // "no results", which is the search quietly lying about the corpus.
    const user = userEvent.setup();
    context.documents = [
      { ...base, id: 'c', name: 'Wear ring clearance.pdf', folder: 'Personal Uploads', visibility: 'personal' },
    ];
    render(<DocumentsPage />);

    await user.click(screen.getByText('My files'));
    expect(screen.queryByText('Wear ring clearance.pdf')).not.toBeInTheDocument();

    await user.type(
      screen.getByPlaceholderText(/search authorized documents/i),
      'wear ring',
    );

    expect(screen.getByText('Wear ring clearance.pdf')).toBeInTheDocument();
  });

  it('offers no index or download action for a catalogue-only row', () => {
    context.documents = [
      { ...base, hasStoredFile: false, status: 'Ready for indexing', chunks: 0 },
    ];
    render(<DocumentsPage />);

    expect(
      screen.queryByRole('button', { name: /Index document/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Download document/i }),
    ).not.toBeInTheDocument();
  });

  it('reports the retrieval mode from health rather than asserting it', () => {
    context.documents = [base];
    render(<DocumentsPage />);
    expect(screen.getByText('Keyword retrieval (BM25) only')).toBeInTheDocument();
  });
});
