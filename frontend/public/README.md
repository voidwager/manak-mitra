# Static assets

Served from the site root: `public/synq-logo.svg` is fetched as
`/synq-logo.svg`, and is copied into the image by the frontend build stage.

## synq-logo.svg (or .png)

The SYNQ wordmark shown at the top of the sidebar.

The sidebar tries `.svg` first and falls back to `.png`, so either format
works — save it under one of those two names and nothing else needs to
change. If neither file is present the sidebar renders the word "SYNQ"
instead, because a brand that appears as a broken-image icon is worse than
one rendered as text.

The mark is white, so it is inverted automatically under the light theme
rather than kept as a second file that has to stay in step with the first.
