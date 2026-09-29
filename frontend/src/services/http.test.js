/**
 * HTTP client tests.
 *
 * The filename parser is the interesting part: it reads a header the server
 * builds from a user-supplied document name, so it has to cope with quotes,
 * semicolons and non-ASCII without producing a filename the browser will
 * mangle - or worse, one that escapes the directory the user chose.
 */

import { describe, expect, it } from 'vitest';
import { filenameFromDisposition } from './http';

describe('filenameFromDisposition', () => {
  it('prefers the RFC 5987 encoded form, which survives non-ASCII', () => {
    const header =
      "attachment; filename=\"CRS_Registration_Guide.txt\"; filename*=UTF-8''CRS%20Registration%20Guide.txt";
    expect(filenameFromDisposition(header)).toBe('CRS Registration Guide.txt');
  });

  it('decodes percent-encoded non-ASCII names', () => {
    const header = "attachment; filename*=UTF-8''Rapport%20d%C3%A9taill%C3%A9.pdf";
    expect(filenameFromDisposition(header)).toBe('Rapport détaillé.pdf');
  });

  it('falls back to the plain quoted form when there is no encoded one', () => {
    expect(filenameFromDisposition('attachment; filename="report.pdf"')).toBe(
      'report.pdf',
    );
  });

  it('returns empty string rather than throwing on a missing header', () => {
    expect(filenameFromDisposition(null)).toBe('');
    expect(filenameFromDisposition('')).toBe('');
    expect(filenameFromDisposition('attachment')).toBe('');
  });

  it('does not choke on a malformed percent sequence', () => {
    // A name the server could not encode cleanly must degrade to the plain
    // form rather than blow up the download.
    const header = "attachment; filename=\"safe.txt\"; filename*=UTF-8''%E0%A4";
    expect(filenameFromDisposition(header)).toBe('safe.txt');
  });
});
