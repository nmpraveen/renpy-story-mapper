# Deferred M07/M08 browser organization surfaces

M15 removes the visible AI Story Map selector, M07 bounded-selection/organization controls,
consent/review dialogs, and their reserved layout area from the packaged normal website.

Compatibility retained:

- M07/M08 payload collections, organization/assembly persistence, and bounded API contracts.
- Applied legacy assemblies and AI Story Map/detail readers for compatible older clients.
- M10 deterministic inspection/canonical fallbacks for projects without a current Narrative Map.

The retired browser presentation can be recovered from coordinator base commit
`07e9ecd1635b8963cf36bb2c98248a5f703c5718`, primarily in
`src/renpy_story_mapper/web/static/index.html`, `app.js`, and `styles.css`. Restoration requires a
future approved milestone with explicit cloud-consent, zero-background-call, compatibility, and
layout acceptance criteria. The persisted records and backend routes must not be semantically
repurposed in the meantime.
