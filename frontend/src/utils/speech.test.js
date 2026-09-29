/**
 * Voice input tests.
 *
 * The button this replaced faked a transcript on a timer. What these pin is
 * that nothing is faked any more: text comes only from a recognition result,
 * in the language chosen, and a browser without recognition gets no button.
 */

import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useSpeechInput } from './speech';

class FakeRecognition {
  static last = null;
  constructor() {
    FakeRecognition.last = this;
    this.start = vi.fn();
    this.stop = vi.fn(() => this.onend?.());
    this.abort = vi.fn();
  }
  say(text) {
    this.onresult?.({ results: [[{ transcript: text }]] });
    this.onend?.();
  }
}

describe('useSpeechInput', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    delete window.SpeechRecognition;
    delete window.webkitSpeechRecognition;
    FakeRecognition.last = null;
  });

  it('is unsupported, not faked, where the browser cannot recognise speech', () => {
    const { result } = renderHook(() => useSpeechInput(() => {}));
    expect(result.current.supported).toBe(false);
  });

  it('passes on exactly what was recognised', () => {
    window.webkitSpeechRecognition = FakeRecognition;
    const heard = vi.fn();
    const { result } = renderHook(() => useSpeechInput(heard));

    act(() => result.current.start());
    expect(result.current.listening).toBe(true);
    expect(heard).not.toHaveBeenCalled();

    act(() => FakeRecognition.last.say('सोने की हॉलमार्किंग कैसे जांचें'));
    expect(heard).toHaveBeenCalledWith('सोने की हॉलमार्किंग कैसे जांचें');
    expect(result.current.listening).toBe(false);
  });

  it('listens in the chosen language and remembers it', () => {
    window.SpeechRecognition = FakeRecognition;
    const { result, unmount } = renderHook(() => useSpeechInput(() => {}));

    act(() => result.current.setLanguage('ta-IN'));
    act(() => result.current.start());
    expect(FakeRecognition.last.lang).toBe('ta-IN');
    unmount();

    const again = renderHook(() => useSpeechInput(() => {}));
    expect(again.result.current.language).toBe('ta-IN');
  });

  it('reports a refused microphone instead of failing silently', () => {
    window.SpeechRecognition = FakeRecognition;
    const { result } = renderHook(() => useSpeechInput(() => {}));

    act(() => result.current.start());
    act(() => {
      FakeRecognition.last.onerror({ error: 'not-allowed' });
      FakeRecognition.last.onend();
    });
    expect(result.current.error).toMatch(/permission/i);
  });
});
