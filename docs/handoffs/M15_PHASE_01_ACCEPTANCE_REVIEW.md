# M15.1 Story Map V2 — Phase 01 acceptance review

Date: 2026-07-24

Decision: **accept the Phase 01 product direction and proceed to a separately coordinated Phase 02
core rewrite.** M15.1 remains `Revise` and incomplete.

## What passed

- The disposable prototype is materially closer to the requested product than the rejected wide
  engineering graph: one readable vertical Day 1 story, local choices, exact arm captions,
  rejoins, state changes, and selectable witness paths.
- The four 100%/200% screenshots are readable and show no clipping, overlap, horizontal sprawl,
  `START START` clutter, atom IDs, or routing-only cards.
- The cloud experiment closed at 20 calls with complete accounting and unchanged protected inputs.
- Full Day 1 was usable with all three hosted models. Sol led quality, Terra was the strongest
  observed quality/speed balance, and Luna remained acceptable for rough practical mapping.
- The local Qwen supplement produced four schema-valid maps. Medium, large, and full passed the
  deterministic path checker, making it credible as an optional private/refusal fallback.

## Correction to the Phase 01 recommendation

The frozen Phase 01 report's ~2.5k normal Luna target is too conservative to become a product rule.
The four tested sizes contained different story material and structural density, and each cell was
sampled once. Luna's ~5.3k result was semantically strong but quarantined for experiment tool use;
its ~8k result mistranscribed source ranges; and its larger complete ~10.7k Day 1 result passed.
That does not demonstrate a 2.5k context limit.

Phase 02 will therefore start with natural coherent boundaries around ~8k raw-story tokens, split
branch-heavy material nearer ~5k, and retain ~10.7k as the current validated ceiling. The new
validator will stop asking AI to reproduce exact mechanics or exact source ranges where Python can
own them. This avoids turning 100k story tokens into roughly 41 tiny calls.

Luna remains the initial low-cost mapper, but it is not declared the proven cheapest complete
pipeline because reliable end-to-end prices are unavailable. Phase 02 must measure real workflow
calls. Terra remains the planned infrequent whole-story synthesizer and the mapper alternative if
Luna's real total quality/call economics are worse.

The no-default-auditor choice remains appropriate for simplicity, but the Phase 01 audit tested
only one clean candidate. It does not prove that selective review can never help.

Other non-blocking limits: Terra's 16k/24k synthetic extensions demonstrate transport/JSON capacity,
not comprehension of an equally complex story; the measured latency/tokens include Codex harness
overhead; and the independent rereview predates the final packaging/local-supplement edits. The
later final manifests match the current artifacts, so these limits do not overturn the prototype or
cloud/local conclusions, but Phase 02 must measure its own supported workflow instead of treating
Phase 01 estimates as production guarantees.

## Local fallback policy

- Cloud is primary.
- Local processing is enabled once per run/project, never silently.
- It activates only for an explicit cloud content/safety refusal, or when the user deliberately
  selects local/private processing.
- A refused cloud chunk keeps identical boundaries when sent locally.
- A deliberate local-only run targets ~8k, splits branch-heavy material nearer ~5k, and stays under
  the currently validated ~10.7k raw-story ceiling.
- Python inserts exact captions, order, conditions, effects, rejoins, destinations, and routes.
  AI supplies narrative meaning and branch-outcome summaries.
- Local is not used for timeouts, rate limits, bad JSON, identity failures, ordinary quality
  defects, or retry loops.
- LM Studio/model installation, startup, download, and loading remain manual.
- Local whole-story synthesis remains unapproved because Phase 01 tested only the mapping role.

## Git and milestone decision

PR #26 must not be merged. Its remote head is a historical failing-first checkpoint and was 133
commits behind the local integration head. Pushing now would publish a very large stack containing
the rejected Stage H/Stage E implementation before its replacement exists. Keep those commits
local and auditable. PR #26 was converted to draft and given an explicit rewrite-in-progress body;
update its remote head only after Phase 02 has an integrated accepted replacement and passing
exact-head checks.

The detailed next-task prompt is
[`M15_PHASE_02_STORY_MAP_V2_CORE_REWRITE.md`](M15_PHASE_02_STORY_MAP_V2_CORE_REWRITE.md).
