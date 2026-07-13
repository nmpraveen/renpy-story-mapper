# M08 evaluation fixtures

This directory is safe to commit. `technical-baseline.json` and `validated-ai.json` contain only
synthetic identifiers and synthetic interpretations derived from the checked-in M05 fixture. The
manifest contains no external story text, walkthrough text, recovered source, archive, or absolute
path.

External inputs are represented only by path/fingerprint slots. Their window ID sets are also
unresolved slots. A local scope builder must materialize a separate resolved manifest with exact
deterministic node IDs, evidence IDs, boundary context, and the canonical ID-set SHA-256 before the
evaluation runner will accept it. Resolved external manifests and artifacts are local run outputs
and must not be committed.

The four MsDenvers entries deliberately select separate windows inside
`route_scope_13004aa8febf656c5f04`. The parent currently contains 13,937 evidence records and is not
an acceptable evaluation window. Each resolved window is capped at 24 nodes and 256 evidence
records and must be a strict subset of the parent.
