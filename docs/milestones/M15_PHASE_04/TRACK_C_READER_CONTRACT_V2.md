# Phase 04 Track C/D reader contract v2 extension

Status: Frozen additive integration contract

Effective schema/version: `story-map-v2-reader-contract-v2`

Base contract: `story-map-v2-reader-contract-v1` at exact commit
`cea5cf03145a2395be6571f9f8a91c7a6020c504`.

Machine-readable extension schema:
`src/renpy_story_mapper/story_map_v2/schemas/story_map_reader_contract_v2.schema.json`

Public synthetic extension fixture:
`tests/fixtures/story_map_v2/phase04_reader_contract_v2.json`

## Only v2 delta

The successful locate response retains every v1 field and adds required
`location.branch_id: string | null`.

- For a selection whose page resource is a branch, `branch_id` is the exact opaque resource ID to
  send as `branch-page.branch_id`.
- For a section-only selection, `branch_id` is `null`.
- `location.page_cursor` is bound to the identified resource. When `branch_id` is non-null it is a
  branch-page cursor; otherwise it is a section-page cursor.
- The client must not derive `branch_id` from `selection_id`, `shell_id`, or `item_id`.

All v1 routes, limits, envelopes, revision/cursor behavior, ownership, safety rules, and the
separate Track B mutation-routing boundary remain unchanged. Implementations advertise and return
the v2 schema string once they implement this extension. The v1 files remain durable rejected-seam
history rather than being rewritten.

