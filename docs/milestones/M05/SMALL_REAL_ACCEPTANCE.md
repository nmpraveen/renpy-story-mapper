# M05 Small Real-Script Acceptance

The user gave fresh explicit permission to send `script small new.rpy` through the locked M05
ChatGPT path. The Dropbox source was fingerprinted, copied to a Windows temporary directory, and
never modified or written beside.

## Before AI

- SHA-256: `d3a4e0a305c6c8a8d84ff5bd99845a4035f0bde7ce953699af71d607806d7f71`
- Size: 9,994 bytes
- LastWriteTimeUtc: `2026-03-27T22:21:22.0000000Z`
- 49 graph nodes, 51 graph edges, three scenes, 30 beats, and 36 transitions
- two choice beats containing five options
- nine deterministic effects, seven state variables, and two unresolved records
- deterministic authority SHA-256:
  `55b48b9e3202e50186aab7f96b3c22f7cd10c262a26b769413e3cf50a7910374`

The pre-AI map shows three technical Level-1 containers: `splashscreen`, `start`, and
`language_selector`. This is accurate but requires the reader to interpret label names and inspect
their structural groups.

## AI organization

The fresh run explicitly used `gpt-5.6-luna`, High reasoning, and disabled fast mode. Four provider
calls completed in 89.302 seconds with 49,398 input and 4,154 output tokens. The validated review
draft contained one arc, four AI events, and 14 evidence-backed claims. It did not change the
deterministic authority hash.

After explicit approval inside the disposable project, the accepted view contains one readable
arc, **Language setup and tutorial onboarding**. It contains four AI-organized events:

1. Language Selection
2. Language-selection condition
3. State updates before tutorial prompt
4. Tutorial prompt and mechanics explanation

Six isolated technical beats remain visible as deterministic fallback events instead of being
guessed away. The accepted map contains nine locally derived event edges. All five choice options,
nine effects, exact source evidence, and two unresolved records remain in the unchanged
deterministic foundation.

An immediate rerun used four cache hits, made zero provider calls, and completed in 54 ms. Opening
and navigating the accepted project invoked no provider and remained under the 240-item rendering
cap with 19 rendered items.

## After-source check

The Dropbox source retained the identical SHA-256, 9,994-byte size, and LastWriteTimeUtc after the
run. The original was not changed.

## How to compare the views

Open the retained temporary project in the app and use the left navigator:

- **Accepted overview** shows the AI-organized arc.
- **Technical map / unorganized scopes** shows the deterministic pre-AI structure.
- **Level 2** expands the accepted arc into events and fallback nodes.
- **Level 3** and the **Evidence** tab expose exact text and physical source lines.
- The pending cached draft opens the AI review dialog, where each group can be approved, rejected,
  or discarded before applying.

The repository screenshots provide the same comparison under `screenshots/small-real/`.
`SMALL_REAL_ACCEPTANCE.json` retains the exact machine-readable metrics.

One harness caveat was identified and resolved correctly: Qt's headless `offscreen` platform saw
zero installed fonts and rendered missing-glyph boxes. The Windows runtime plugin saw 340 font
families including Segoe UI and produced readable captures. Windows is the sole release authority.
