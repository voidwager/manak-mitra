import React from 'react';

/**
 * Render an assistant reply.
 *
 * Models answer in Markdown whether or not you ask them to. The previous
 * renderer handled `### ` headings and passed everything else through
 * verbatim, so a normal answer arrived full of literal asterisks -
 * `**Acceptable Limit**`, `* **2.5 to 3.2 mm/s RMS:**` - which reads as
 * broken software rather than as a technical answer.
 *
 * This handles the subset a chat model actually emits: headings, ordered and
 * unordered lists, bold, italic, inline code, fenced code blocks, and the
 * `[1]` citation markers the grounded prompt asks for.
 *
 * Hand-rolled rather than `react-markdown` for two reasons. The bundle is
 * small and this project keeps its dependencies few; and more importantly
 * everything below builds React *elements* and never HTML, so a reply
 * containing `<img onerror=...>` renders as those characters and cannot
 * become markup. There is no `dangerouslySetInnerHTML` anywhere in this
 * file, and there should never be one.
 */

// Inline spans, in precedence order. Code first, so its contents are not
// re-parsed; citations last, since they are the narrowest pattern.
// Every alternative uses a negated character class rather than `.*?`, which
// keeps matching linear - a pathological reply cannot hang the browser.
const INLINE = new RegExp(
  [
    '(`[^`\\n]+`)', // `code`
    '(\\*\\*[^*\\n]+\\*\\*)', // **bold**
    '(__[^_\\n]+__)', // __bold__
    '(\\*[^*\\n]+\\*)', // *italic*
    '(_[^_\\n]+_)', // _italic_
    '(\\[\\d+(?:\\s*,\\s*\\d+)*\\])', // [1] or [1, 2]
  ].join('|'),
  'g',
);

const CITATION = /^\[(\d+(?:\s*,\s*\d+)*)\]$/;

/**
 * Turn one line of text into React nodes.
 *
 * `depth` guards the recursion into bold/italic contents; two levels is
 * more nesting than any real answer uses.
 */
function renderInline(text, onCitationClick, depth = 0) {
  if (!text) return null;
  if (depth > 2) return text;

  const nodes = [];
  let lastIndex = 0;
  let key = 0;

  // `matchAll` needs the regex reset between calls, since it is a shared
  // module-level object with the global flag.
  INLINE.lastIndex = 0;
  for (const match of text.matchAll(INLINE)) {
    const token = match[0];
    const start = match.index;

    if (start > lastIndex) nodes.push(text.slice(lastIndex, start));
    lastIndex = start + token.length;

    const citation = CITATION.exec(token);
    if (citation) {
      const numbers = citation[1].split(',').map((n) => Number(n.trim()));
      nodes.push(
        <sup key={`c${key++}`} className="msg-citation-group">
          {numbers.map((n, i) => (
            <button
              key={n}
              type="button"
              className="msg-citation"
              // The marker refers to the nth passage the server retrieved,
              // which is the nth source card below. Clicking opens it.
              onClick={() => onCitationClick?.(n)}
              title={`Open source ${n}`}
              // Without this the accessible name is the bare digit, which
              // tells a screen-reader user nothing about what it does.
              aria-label={`Open source ${n}`}
            >
              {n}
              {i < numbers.length - 1 ? ',' : ''}
            </button>
          ))}
        </sup>,
      );
      continue;
    }

    if (token.startsWith('`')) {
      nodes.push(
        <code key={`k${key++}`} className="msg-code">
          {token.slice(1, -1)}
        </code>,
      );
      continue;
    }

    if (token.startsWith('**') || token.startsWith('__')) {
      nodes.push(
        <strong key={`b${key++}`}>
          {renderInline(token.slice(2, -2), onCitationClick, depth + 1)}
        </strong>,
      );
      continue;
    }

    // Single * or _
    nodes.push(
      <em key={`i${key++}`}>
        {renderInline(token.slice(1, -1), onCitationClick, depth + 1)}
      </em>,
    );
  }

  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes.length ? nodes : text;
}

const HEADING = /^(#{1,4})\s+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const ORDERED = /^\s*(\d+)[.)]\s+(.*)$/;
const FENCE = /^\s*```/;

/**
 * Group lines into blocks, then render each.
 *
 * Done as a single pass rather than by splitting on blank lines, because a
 * list is a block whether or not its items are separated by them - and
 * models are inconsistent about that.
 */
function renderBlocks(text, onCitationClick) {
  const lines = (text || '').replace(/\r\n/g, '\n').split('\n');
  const blocks = [];

  let paragraph = [];
  let list = null; // { ordered, items: [] }
  let fence = null; // { lines: [] }

  // A blank line does not end a list on its own - models routinely space
  // items out, and closing on the first blank restarts the numbering, so
  // "1., 2., 3." renders as three separate lists each beginning at 1. The
  // list only closes once a blank is followed by something that is not
  // another item of the same kind.
  let blankInsideList = false;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const content = paragraph;
    paragraph = [];
    blocks.push(
      <p key={`p${blocks.length}`} className="msg-paragraph">
        {content.map((line, i) => (
          <React.Fragment key={i}>
            {renderInline(line, onCitationClick)}
            {i < content.length - 1 && <br />}
          </React.Fragment>
        ))}
      </p>,
    );
  };

  const flushList = () => {
    if (!list) return;
    const { ordered, items } = list;
    list = null;
    const Tag = ordered ? 'ol' : 'ul';
    blocks.push(
      <Tag key={`l${blocks.length}`} className="msg-list">
        {items.map((item, i) => (
          <li key={i}>
            {/* An item can carry continuation lines, so it breaks like a
                paragraph rather than collapsing to one run of text. */}
            {item.split('\n').map((line, lineIndex, all) => (
              <React.Fragment key={lineIndex}>
                {renderInline(line, onCitationClick)}
                {lineIndex < all.length - 1 && <br />}
              </React.Fragment>
            ))}
          </li>
        ))}
      </Tag>,
    );
  };

  const flushAll = () => {
    flushParagraph();
    flushList();
  };

  for (const line of lines) {
    // Fenced code runs verbatim until it closes, so nothing inside it is
    // interpreted as markdown.
    if (fence) {
      if (FENCE.test(line)) {
        blocks.push(
          <pre key={`f${blocks.length}`} className="msg-pre">
            <code>{fence.lines.join('\n')}</code>
          </pre>,
        );
        fence = null;
      } else {
        fence.lines.push(line);
      }
      continue;
    }

    if (FENCE.test(line)) {
      flushAll();
      fence = { lines: [] };
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      // Hold the list open; the next line decides whether it continues.
      if (list) blankInsideList = true;
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flushAll();
      const level = Math.min(heading[1].length + 3, 6); // # -> h4, deeper -> h5/h6
      const Tag = `h${level}`;
      blocks.push(
        <Tag key={`h${blocks.length}`} className="msg-heading">
          {renderInline(heading[2], onCitationClick)}
        </Tag>,
      );
      continue;
    }

    const ordered = ORDERED.exec(line);
    if (ordered) {
      flushParagraph();
      if (!list || !list.ordered) {
        flushList();
        list = { ordered: true, items: [] };
      }
      list.items.push(ordered[2]);
      blankInsideList = false;
      continue;
    }

    const bullet = BULLET.exec(line);
    if (bullet) {
      flushParagraph();
      if (!list || list.ordered) {
        flushList();
        list = { ordered: false, items: [] };
      }
      list.items.push(bullet[1]);
      blankInsideList = false;
      continue;
    }

    // A plain line directly under an item belongs to that item. Models
    // habitually put the heading on the marker line and the detail beneath
    // it; treating that as a new paragraph splits the list in two.
    if (list && !blankInsideList && !paragraph.length && list.items.length) {
      list.items[list.items.length - 1] += `\n${line}`;
      continue;
    }

    flushList();
    blankInsideList = false;
    paragraph.push(line);
  }

  // An unterminated fence still has to render - a streamed reply is
  // routinely mid-block when the last token arrives.
  if (fence) {
    blocks.push(
      <pre key={`f${blocks.length}`} className="msg-pre">
        <code>{fence.lines.join('\n')}</code>
      </pre>,
    );
  }
  flushAll();

  return blocks;
}

export const MessageContent = ({ text, onCitationClick }) => (
  <>{renderBlocks(text, onCitationClick)}</>
);

export default MessageContent;
