# public/

Served from the site root: `public/manak-mitra-logo.svg` is fetched as
`/manak-mitra-logo.svg`, and is copied into the image by the frontend build stage.

## manak-mitra-logo.svg

The Manak Mitra mark shown at the top of the sidebar: a seal with a tick,
beside the name. Filled white; the light theme inverts it in CSS
(`src/components/layout/BrandMark.jsx`).

If the file is missing, the sidebar draws the same mark inline
(`src/components/layout/Wordmark.jsx`), so a bad checkout never shows a
broken-image icon.
