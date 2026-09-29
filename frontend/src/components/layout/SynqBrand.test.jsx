/**
 * Brand mark tests.
 *
 * Two things are worth pinning. The choice has to survive being made in one
 * place and read in another - the picker lives in Settings and the mark it
 * changes lives in the sidebar, and they share nothing but localStorage and
 * an event. And the mark has to keep drawing something when the file behind
 * it does not load, because a brand that renders as a broken-image icon is
 * the worst of the available failures.
 */

import { render, screen, act } from '@testing-library/react';
import { fireEvent } from '@testing-library/dom';
import { beforeEach, describe, expect, it } from 'vitest';

import {
  SynqBrand,
  BRAND_VARIANTS,
  DEFAULT_BRAND_VARIANT,
  useBrandVariant
} from './SynqBrand';

const Harness = () => {
  const [variant, choose] = useBrandVariant();
  return (
    <div>
      <span data-testid="current">{variant}</span>
      <button onClick={() => choose('lockup')}>lockup</button>
      <button onClick={() => choose('wordmark')}>wordmark</button>
      <button onClick={() => choose('nonsense')}>nonsense</button>
    </div>
  );
};

describe('SynqBrand', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('draws the lockup by default', () => {
    render(<SynqBrand />);
    expect(screen.getByAltText('SYNQ')).toHaveAttribute('src', '/synq-logo.svg');
    expect(screen.getByText('Synthetic Yield for')).toBeTruthy();
  });

  it('adds the tagline for the lockup, as text', () => {
    render(<SynqBrand variant="lockup" />);
    // Text, not artwork: a traced tagline cannot stay crisp when it is
    // scaled down to sidebar size, and this one has to be readable there.
    expect(screen.getByText('Synthetic Yield for')).toBeTruthy();
    expect(screen.getByText('Neural Quantization')).toBeTruthy();
  });

  it('draws the same mark at the same size in both variants', () => {
    // Only the tagline comes and goes. A SYNQ that changed size when the
    // tagline appeared would read as two different logos.
    const { unmount } = render(<SynqBrand variant="wordmark" />);
    const plain = screen.getByAltText('SYNQ').style.height;
    expect(screen.queryByText('Synthetic Yield for')).toBeNull();
    unmount();

    render(<SynqBrand variant="lockup" />);
    expect(screen.getByAltText('SYNQ').style.height).toBe(plain);
    expect(plain).toBe(BRAND_VARIANTS.wordmark.height + 'px');
  });

  it('falls back to the drawn wordmark when the file will not load', () => {
    render(<SynqBrand variant="wordmark" />);
    fireEvent.error(screen.getByAltText('SYNQ'));
    expect(screen.queryByRole('img', { name: 'SYNQ' })).toBeTruthy();
    expect(screen.queryByAltText('SYNQ')).toBeNull();
  });

  it('ignores a variant it does not have', () => {
    render(<SynqBrand variant="does-not-exist" />);
    // Falls back to the default rather than rendering nothing.
    expect(screen.getByAltText('SYNQ')).toBeTruthy();
    expect(screen.getByText('Synthetic Yield for')).toBeTruthy();
  });
});

describe('useBrandVariant', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('starts on the default', () => {
    render(<Harness />);
    expect(screen.getByTestId('current')).toHaveTextContent(
      DEFAULT_BRAND_VARIANT
    );
  });

  it('remembers the choice', () => {
    // Deliberately the variant that is not the default: choosing the
    // default proves nothing, since that is where it started.
    const { unmount } = render(<Harness />);
    act(() => screen.getByText('wordmark').click());
    expect(screen.getByTestId('current')).toHaveTextContent('wordmark');

    unmount();
    render(<Harness />);
    expect(screen.getByTestId('current')).toHaveTextContent('wordmark');
  });

  it('tells every listener at once, not just the one that changed it', () => {
    // The picker and the sidebar are separate trees. A `storage` event only
    // fires in other tabs, so without the custom event the sidebar would
    // keep drawing the old mark until a reload.
    render(
      <div>
        <Harness />
        <Harness />
      </div>
    );
    const [picker] = screen.getAllByText('wordmark');
    act(() => picker.click());

    for (const node of screen.getAllByTestId('current')) {
      expect(node).toHaveTextContent('wordmark');
    }
  });

  it('refuses a variant that does not exist', () => {
    render(<Harness />);
    act(() => screen.getByText('nonsense').click());
    expect(screen.getByTestId('current')).toHaveTextContent(
      DEFAULT_BRAND_VARIANT
    );
  });

  it('still works when localStorage is unavailable', () => {
    const getItem = window.localStorage.getItem;
    window.localStorage.getItem = () => {
      throw new Error('site data blocked');
    };
    try {
      render(<Harness />);
      expect(screen.getByTestId('current')).toHaveTextContent(
        DEFAULT_BRAND_VARIANT
      );
    } finally {
      window.localStorage.getItem = getItem;
    }
  });
});
