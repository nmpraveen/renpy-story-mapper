# Deferred M12 route-solver browser surface

M15 removes the visible route panel, destination picker, solve action, and “How do I reach this?”
journey from the packaged normal website. This is a presentation retirement, not a backend or
data deletion.

Still supported:

- M12 preparation, solve, persistence, cache identity, stored-result APIs, and readers.
- Existing stored M12 result records.
- M13 citations with `navigation.mode="m12_result"`, which continue to open the exact stored result
  and then its Detail/Evidence authority.

The former browser surface can be recovered from coordinator base commit
`07e9ecd1635b8963cf36bb2c98248a5f703c5718`, primarily in
`src/renpy_story_mapper/web/static/index.html`, `app.js`, and `styles.css`. Any restoration must be
an explicitly scoped future milestone and must not displace the Narrative Map default or issue
solve/destination requests during ordinary open, navigation, search, or selection.
