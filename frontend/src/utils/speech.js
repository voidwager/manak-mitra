import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Voice input through the browser's own speech recognition.
 *
 * This replaced a button that waited two seconds and typed a canned English
 * sentence into the box. That is the kind of feature this project refuses to
 * ship: it looks like it works in a demo and does nothing for a user. Real
 * recognition exists in Chromium browsers (Chrome, Edge, Android) and Safari,
 * and it covers the Indian languages below - which, for a helpdesk whose
 * users may not type English comfortably, is most of the point.
 *
 * Where the browser has no recognition at all, `supported` is false and the
 * caller hides the button rather than showing one that cannot work.
 *
 * Audio goes to the browser vendor's recognition service, not to this
 * server - stated in the button's tooltip so nobody assumes otherwise.
 */

export const VOICE_LANGUAGES = [
  { code: 'en-IN', label: 'English' },
  { code: 'hi-IN', label: 'हिन्दी' },
  { code: 'mr-IN', label: 'मराठी' },
  { code: 'bn-IN', label: 'বাংলা' },
  { code: 'ta-IN', label: 'தமிழ்' },
  { code: 'te-IN', label: 'తెలుగు' },
  { code: 'gu-IN', label: 'ગુજરાતી' },
  { code: 'kn-IN', label: 'ಕನ್ನಡ' },
  { code: 'ml-IN', label: 'മലയാളം' },
  { code: 'pa-IN', label: 'ਪੰਜਾਬੀ' },
];

const STORAGE_KEY = 'manak.voiceLanguage';

const recognitionClass = () =>
  typeof window === 'undefined'
    ? null
    : window.SpeechRecognition || window.webkitSpeechRecognition || null;

const readLanguage = () => {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (VOICE_LANGUAGES.some((l) => l.code === saved)) return saved;
  } catch {
    // Blocked site data: fall through to the default.
  }
  return 'en-IN';
};

/**
 * @param {(text: string) => void} onText  called with the final transcript
 */
export const useSpeechInput = (onText) => {
  const Recognition = recognitionClass();
  const [listening, setListening] = useState(false);
  const [language, setLanguageState] = useState(readLanguage);
  const [error, setError] = useState(null);
  const recognitionRef = useRef(null);
  const onTextRef = useRef(onText);
  onTextRef.current = onText;

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  const start = useCallback(() => {
    if (!Recognition) return;
    setError(null);
    const recognition = new Recognition();
    recognition.lang = language;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      const text = Array.from(event.results)
        .map((result) => result[0]?.transcript || '')
        .join(' ')
        .trim();
      if (text) onTextRef.current(text);
    };
    recognition.onerror = (event) => {
      // "no-speech" and "aborted" are ordinary endings, not failures.
      if (event.error && !['no-speech', 'aborted'].includes(event.error)) {
        setError(
          event.error === 'not-allowed'
            ? 'Microphone permission was refused.'
            : `Voice input stopped: ${event.error}.`,
        );
      }
    };
    recognition.onend = () => setListening(false);

    recognitionRef.current = recognition;
    setListening(true);
    recognition.start();
  }, [Recognition, language]);

  const setLanguage = useCallback((code) => {
    setLanguageState(code);
    try {
      window.localStorage.setItem(STORAGE_KEY, code);
    } catch {
      // Not remembering is fine.
    }
  }, []);

  useEffect(() => () => recognitionRef.current?.abort(), []);

  return {
    supported: Boolean(Recognition),
    listening,
    language,
    setLanguage,
    error,
    start,
    stop,
  };
};
