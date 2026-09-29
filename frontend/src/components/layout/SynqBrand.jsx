import React, { useCallback, useEffect, useState } from 'react';
import { SynqWordmark } from './SynqWordmark';

/**
 * The brand mark, in whichever form has been chosen.
 *
 * Both variants draw the same traced wordmark. The lockup adds the tagline
 * under it - and sets that tagline as live text rather than as more traced
 * artwork, which is the one decision here worth explaining.
 *
 * The tagline in the original export is a rasterised trace: hairline strokes
 * about one unit wide. Scaled up it is fine, and at a hundred-odd pixels it
 * looks exactly like the artwork. Scaled down to the ~60px a sidebar can
 * give it, those strokes land on fractions of a pixel, and no amount of
 * cleaning up the mask fixes that - a half-pixel stroke is grey, because
 * that is what a half-covered pixel is. It read as smeared for the same
 * reason a downscaled photo of text does.
 *
 * Text does not have that problem. The browser hints and snaps it to the
 * pixel grid at whatever size it is asked for, so it is crisp at 8px and
 * still crisp at 80px. It also inherits colour, which means the tagline
 * needs no inversion on the light theme, and it stays selectable and
 * readable to a screen reader.
 *
 * The cost is that it is set in the interface font rather than the brand's.
 * Against a tagline that was previously illegible, that is a trade worth
 * making - and Plus Jakarta Sans, tracked out and in caps, sits close to
 * the geometric sans of the original.
 */
export const BRAND_VARIANTS = {
  wordmark: {
    id: 'wordmark',
    label: 'Wordmark',
    height: 37,
    tagline: null,
    description: 'The mark on its own.'
  },
  lockup: {
    id: 'lockup',
    label: 'Lockup',
    height: 37,
    // Two lines, because one would be half again as wide as the mark it
    // sits under. The break falls where the sentence does.
    tagline: ['Synthetic Yield for', 'Neural Quantization'],
    description: 'With the tagline underneath.'
  }
};

/*
 * The lockup leads. The tagline is what the name stands for, and a
 * prototype being shown to people who have not seen it before should say
 * so on the way in rather than making them ask.
 */
export const DEFAULT_BRAND_VARIANT = 'lockup';

/*
 * The mark itself. Traced from the brand artwork, filled white, and
 * inverted by CSS on the light theme - currentColor cannot cross an <img>
 * boundary, so the fill is explicit and the theme swap happens outside the
 * file.
 */
const LOGO_SRC = '/synq-logo.svg';

const STORAGE_KEY = 'synq.brandVariant';
const CHANGE_EVENT = 'synq:brand-variant';

const readStored = () => {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return BRAND_VARIANTS[saved] ? saved : DEFAULT_BRAND_VARIANT;
  } catch {
    // Private windows and blocked site data both throw on access rather
    // than returning null. The default is a fine answer either way.
    return DEFAULT_BRAND_VARIANT;
  }
};

/**
 * Kept in localStorage rather than in the settings record on the server.
 *
 * It is a per-eye preference about a logo, not configuration: it changes
 * nothing another user or the backend can observe, and putting it in the
 * settings table would mean a column, a schema, and a migration for it.
 *
 * The custom event is what keeps the sidebar and the settings page in step.
 * A `storage` event only fires in *other* tabs, so a picker and a sidebar in
 * the same document would otherwise never hear each other.
 */
export const useBrandVariant = () => {
  const [variant, setVariant] = useState(readStored);

  useEffect(() => {
    const sync = () => setVariant(readStored());
    window.addEventListener(CHANGE_EVENT, sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener(CHANGE_EVENT, sync);
      window.removeEventListener('storage', sync);
    };
  }, []);

  const chooseVariant = useCallback((next) => {
    if (!BRAND_VARIANTS[next]) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Not persisting is survivable; not switching is not. Fall through.
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
    setVariant(next);
  }, []);

  return [variant, chooseVariant];
};

/**
 * Renders one variant, falling back to the inline drawn wordmark if the
 * file is missing - a bad checkout, a build that dropped public/. A brand
 * that renders as a broken-image icon is worse than one drawn in code.
 */
export const SynqBrand = ({ variant = DEFAULT_BRAND_VARIANT, className = '' }) => {
  const spec = BRAND_VARIANTS[variant] || BRAND_VARIANTS[DEFAULT_BRAND_VARIANT];
  const [failed, setFailed] = useState(false);

  return (
    <span className={'brand-mark ' + className}>
      {failed ? (
        <SynqWordmark height={spec.height} className="brand-wordmark" />
      ) : (
        <img
          src={LOGO_SRC}
          alt="SYNQ"
          className="brand-logo"
          style={{ height: spec.height + 'px' }}
          onError={() => setFailed(true)}
        />
      )}

      {spec.tagline && (
        /*
         * aria-hidden because the image above is already labelled "SYNQ"
         * and the full name is on the <title> of the page. Read out, this
         * would be a second announcement of the same brand.
         */
        <span className="brand-tagline" aria-hidden="true">
          {spec.tagline.map((line) => (
            <span className="brand-tagline-line" key={line}>
              {line}
            </span>
          ))}
        </span>
      )}

      <style>{`
        .brand-mark {
          display: inline-flex;
          flex-direction: column;
          align-items: center;
          min-width: 0;
        }

        .brand-logo {
          /* Height is set per variant, inline, and width follows from the
             aspect ratio: the mark is 4.32:1, so sizing on width would
             either crush the letters or push the header out of a 260px
             panel. */
          width: auto;
          max-width: 100%;
          object-fit: contain;
          display: block;
        }

        .brand-wordmark {
          color: var(--text-primary);
        }

        /* The file is filled white, which vanishes on a light background.
           Inverting it keeps one asset instead of a second file that has to
           be kept in step with the first. Scoped to the image: the drawn
           fallback and the tagline both take the current text colour and are
           already right in either theme. */
        :root[data-theme='light'] img.brand-logo {
          filter: invert(1);
        }

        @media (prefers-color-scheme: light) {
          :root:not([data-theme='dark']) img.brand-logo {
            filter: invert(1);
          }
        }

        /* Tracked out and in caps, which is how the original is set. The
           negative right margin takes back the trailing space letter-spacing
           adds after the last character, so the line centres on the mark
           rather than sitting a fraction left of it. */
        .brand-tagline {
          display: block;
          margin-top: 7px;
          font-size: 8.5px;
          font-weight: 500;
          line-height: 1.5;
          letter-spacing: 0.155em;
          text-transform: uppercase;
          text-align: center;
          white-space: nowrap;
          color: var(--text-secondary);
        }

        .brand-tagline-line {
          display: block;
          margin-right: -0.155em;
        }
      `}</style>
    </span>
  );
};

export default SynqBrand;
