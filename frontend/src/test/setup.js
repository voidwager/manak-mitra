/**
 * Test environment setup, loaded before every suite.
 *
 * Keeps two things out of the tests themselves: the jest-dom matchers, and
 * the handful of browser APIs jsdom does not implement that this app touches
 * on mount. Without the stubs, a component fails during render for reasons
 * that have nothing to do with what is being tested.
 */

import '@testing-library/jest-dom/vitest';
import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

// Unmount between tests so a query never matches a component left over from
// the previous one.
afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

// AppContext reads this on mount to resolve the "system" theme. jsdom has no
// implementation, so without a stub every render throws.
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  });
}

// The document download path creates and revokes object URLs.
if (!URL.createObjectURL) {
  URL.createObjectURL = () => 'blob:test';
  URL.revokeObjectURL = () => {};
}
