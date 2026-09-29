/**
 * Assistant reply rendering.
 *
 * Hand-rolled markdown is a classic way to ship subtle bugs, so the subset
 * this supports is pinned here - including the case that prompted it: a
 * reply arriving full of literal asterisks because only `### ` was handled.
 *
 * The last group matters most. Model output is untrusted, and this renderer
 * builds React elements rather than HTML precisely so a reply cannot inject
 * markup. If someone ever reaches for dangerouslySetInnerHTML, those tests
 * fail.
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MessageContent } from './MessageContent';

describe('MessageContent inline formatting', () => {
  it('renders bold instead of leaving asterisks in the text', () => {
    render(<MessageContent text="**Acceptable Limit**" />);

    const bold = screen.getByText('Acceptable Limit');
    expect(bold.tagName).toBe('STRONG');
    expect(document.body.textContent).not.toContain('**');
  });

  it('renders italic', () => {
    render(<MessageContent text="*Note: this is guidance.*" />);
    expect(screen.getByText('Note: this is guidance.').tagName).toBe('EM');
  });

  it('renders underscore emphasis', () => {
    render(<MessageContent text="__bold__ and _italic_" />);
    expect(screen.getByText('bold').tagName).toBe('STRONG');
    expect(screen.getByText('italic').tagName).toBe('EM');
  });

  it('renders inline code without interpreting its contents', () => {
    render(<MessageContent text="Set `MODEL_PROVIDER=local` first" />);
    const code = screen.getByText('MODEL_PROVIDER=local');
    expect(code.tagName).toBe('CODE');
  });

  it('handles bold nested inside a list item', () => {
    render(<MessageContent text="* **2.5 to 3.2 mm/s RMS:** schedule a check" />);

    expect(screen.getByRole('listitem')).toBeInTheDocument();
    expect(screen.getByText('2.5 to 3.2 mm/s RMS:').tagName).toBe('STRONG');
    expect(document.body.textContent).not.toContain('**');
  });
});

describe('MessageContent block structure', () => {
  it('renders an unordered list', () => {
    render(<MessageContent text={'- first\n- second\n- third'} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
    expect(screen.getByRole('list').tagName).toBe('UL');
  });

  it('renders an ordered list', () => {
    render(<MessageContent text={'1. isolate\n2. drain\n3. inspect'} />);
    expect(screen.getByRole('list').tagName).toBe('OL');
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
  });

  it('keeps consecutive lists of different kinds apart', () => {
    render(<MessageContent text={'- bullet\n1. numbered'} />);
    const lists = screen.getAllByRole('list');
    expect(lists.map((l) => l.tagName)).toEqual(['UL', 'OL']);
  });

  it('keeps a numbered list together across blank lines', () => {
    // Closing the list on the first blank restarts numbering, so "1., 2., 3."
    // renders as three separate lists that each begin at 1.
    render(<MessageContent text={'1. isolate\n\n2. drain\n\n3. inspect'} />);

    expect(screen.getAllByRole('list')).toHaveLength(1);
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
  });

  it('treats a plain line under an item as part of that item', () => {
    // Models habitually put the heading on the marker line and the detail
    // beneath it. Treating the detail as a new paragraph splits the list.
    render(
      <MessageContent
        text={
          '1. **Acceptable Limit**\nMust not exceed 2.5 mm/s RMS.\n\n' +
          '2. **Action Above Limit**\nStop selling the article.'
        }
      />,
    );

    expect(screen.getAllByRole('list')).toHaveLength(1);
    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain('Must not exceed 2.5 mm/s RMS.');
    expect(items[1].textContent).toContain('Stop selling the article.');
  });

  it('ends a list when ordinary prose follows a blank line', () => {
    render(<MessageContent text={'- one\n- two\n\nA closing remark.'} />);

    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByText('A closing remark.').tagName).toBe('P');
  });

  it('renders headings at every level it supports', () => {
    render(<MessageContent text={'# One\n\n## Two\n\n### Three'} />);
    expect(screen.getByText('One').tagName).toBe('H4');
    expect(screen.getByText('Two').tagName).toBe('H5');
    expect(screen.getByText('Three').tagName).toBe('H6');
  });

  it('splits paragraphs on blank lines and keeps single newlines as breaks', () => {
    const { container } = render(
      <MessageContent text={'first line\nsame paragraph\n\nsecond paragraph'} />,
    );
    expect(container.querySelectorAll('p')).toHaveLength(2);
    expect(container.querySelectorAll('br')).toHaveLength(1);
  });

  it('renders a fenced code block verbatim', () => {
    render(
      <MessageContent text={'```\nMODEL_PROVIDER=local\n**not bold**\n```'} />,
    );
    const pre = document.querySelector('pre');
    expect(pre).toBeInTheDocument();
    // Nothing inside a fence is interpreted.
    expect(pre.textContent).toContain('**not bold**');
  });

  it('renders an unterminated fence, because a streamed reply is often mid-block', () => {
    render(<MessageContent text={'```\nstill streaming'} />);
    expect(document.querySelector('pre').textContent).toBe('still streaming');
  });

  it('renders empty and missing text without throwing', () => {
    expect(() => render(<MessageContent text="" />)).not.toThrow();
    expect(() => render(<MessageContent text={undefined} />)).not.toThrow();
  });
});

describe('MessageContent citation markers', () => {
  it('turns [2] into a control that opens that source', async () => {
    const onCitationClick = vi.fn();
    render(
      <MessageContent
        text="must not exceed 2.5 mm/s RMS [2]."
        onCitationClick={onCitationClick}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /Open source 2/i }));
    expect(onCitationClick).toHaveBeenCalledWith(2);
  });

  it('handles a grouped marker like [1, 3]', async () => {
    const onCitationClick = vi.fn();
    render(<MessageContent text="see [1, 3]" onCitationClick={onCitationClick} />);

    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(2);

    await userEvent.click(buttons[1]);
    expect(onCitationClick).toHaveBeenCalledWith(3);
  });

  it('leaves a non-citation bracket alone', () => {
    render(<MessageContent text="array[index] notation" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(document.body.textContent).toContain('array[index] notation');
  });
});

describe('MessageContent safety', () => {
  it('renders HTML in a reply as text, never as markup', () => {
    render(
      <MessageContent text={'<img src=x onerror="alert(1)"> and <b>tags</b>'} />,
    );

    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector('b')).toBeNull();
    expect(document.body.textContent).toContain('<img src=x onerror="alert(1)">');
  });

  it('does not execute a script tag in model output', () => {
    render(<MessageContent text={'<script>window.__pwned = true</script>'} />);
    expect(document.querySelector('script')).toBeNull();
    expect(window.__pwned).toBeUndefined();
  });

  it('does not hang on pathological asterisk input', () => {
    // A regex built from `.*?` alternatives could backtrack for ever here.
    const started = Date.now();
    render(<MessageContent text={'*'.repeat(2000)} />);
    expect(Date.now() - started).toBeLessThan(2000);
  });
});
