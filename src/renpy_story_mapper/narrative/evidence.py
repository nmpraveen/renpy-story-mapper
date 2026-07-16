"""Deterministic prompt handles and bounded lazy traversal of the M13 claim DAG."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from renpy_story_mapper.narrative.contracts import (
    AuthorityReference,
    ClaimSupport,
    JsonValue,
    NarrativeClaim,
    SupportKind,
)

_EVIDENCE_HANDLE = re.compile(r"E[1-9][0-9]*\Z")
_CHILD_CLAIM_HANDLE = re.compile(r"C[1-9][0-9]*\Z")


class HandleBindingError(ValueError):
    """A provider handle could not be mapped to exact in-scope authority."""


class ClaimDagError(ValueError):
    """The persisted claim graph is missing, corrupt, cyclic, or out of scope."""


class ClaimDagLimitError(ClaimDagError):
    """Lazy evidence traversal exceeded an explicit result bound."""


@dataclass(frozen=True)
class PromptEvidenceHandle:
    handle: str
    reference: AuthorityReference

    def __post_init__(self) -> None:
        if _EVIDENCE_HANDLE.fullmatch(self.handle) is None:
            raise HandleBindingError(f"malformed evidence handle: {self.handle!r}")

    def to_dict(self) -> dict[str, JsonValue]:
        return {"handle": self.handle, "reference": self.reference.to_dict()}


@dataclass(frozen=True)
class PromptChildClaimHandle:
    handle: str
    claim_id: str

    def __post_init__(self) -> None:
        if _CHILD_CLAIM_HANDLE.fullmatch(self.handle) is None:
            raise HandleBindingError(f"malformed child-claim handle: {self.handle!r}")
        if not self.claim_id or self.claim_id != self.claim_id.strip():
            raise HandleBindingError("child claim IDs must be non-empty trimmed strings")

    def to_dict(self) -> dict[str, JsonValue]:
        return {"handle": self.handle, "claim_id": self.claim_id}


@dataclass(frozen=True)
class PromptHandleTable:
    """Exact Python-owned mapping between prompt-local handles and authority IDs."""

    scope_id: str
    allowed_owner_ids: tuple[str, ...]
    evidence_handles: tuple[PromptEvidenceHandle, ...] = ()
    child_claim_handles: tuple[PromptChildClaimHandle, ...] = ()

    def __post_init__(self) -> None:
        if not self.scope_id or self.scope_id != self.scope_id.strip():
            raise HandleBindingError("prompt scope ID must be a non-empty trimmed string")
        _require_unique_strings(self.allowed_owner_ids, "allowed owner ID")
        if not self.allowed_owner_ids and self.evidence_handles:
            raise HandleBindingError("evidence handles require at least one allowed owner")
        expected_evidence = tuple(
            f"E{ordinal}" for ordinal in range(1, len(self.evidence_handles) + 1)
        )
        expected_children = tuple(
            f"C{ordinal}" for ordinal in range(1, len(self.child_claim_handles) + 1)
        )
        if tuple(item.handle for item in self.evidence_handles) != expected_evidence:
            raise HandleBindingError(
                "evidence handles must be the exact contiguous E1..En sequence"
            )
        if tuple(item.handle for item in self.child_claim_handles) != expected_children:
            raise HandleBindingError("child handles must be the exact contiguous C1..Cn sequence")
        evidence = tuple(item.reference for item in self.evidence_handles)
        if len(evidence) != len(set(evidence)):
            raise HandleBindingError("duplicate authority records cannot receive two handles")
        claims = tuple(item.claim_id for item in self.child_claim_handles)
        _require_unique_strings(claims, "child claim ID")
        allowed = set(self.allowed_owner_ids)
        foreign = tuple(item for item in evidence if item.owner_id not in allowed)
        if foreign:
            raise HandleBindingError("an evidence handle references an out-of-scope owner")

    @classmethod
    def build(
        cls,
        *,
        scope_id: str,
        allowed_owner_ids: tuple[str, ...],
        evidence_references: tuple[AuthorityReference, ...] = (),
        child_claim_ids: tuple[str, ...] = (),
    ) -> PromptHandleTable:
        """Build a stable table independent of caller iteration order."""

        if len(evidence_references) != len(set(evidence_references)):
            raise HandleBindingError("duplicate authority references are not allowed")
        _require_unique_strings(child_claim_ids, "child claim ID")
        ordered_evidence = tuple(sorted(evidence_references))
        ordered_claims = tuple(sorted(child_claim_ids))
        return cls(
            scope_id=scope_id,
            allowed_owner_ids=tuple(sorted(allowed_owner_ids)),
            evidence_handles=tuple(
                PromptEvidenceHandle(f"E{ordinal}", reference)
                for ordinal, reference in enumerate(ordered_evidence, start=1)
            ),
            child_claim_handles=tuple(
                PromptChildClaimHandle(f"C{ordinal}", claim_id)
                for ordinal, claim_id in enumerate(ordered_claims, start=1)
            ),
        )

    def resolve_evidence(self, handles: tuple[str, ...]) -> tuple[AuthorityReference, ...]:
        _validate_returned_handles(handles, _EVIDENCE_HANDLE, "evidence")
        lookup = {item.handle: item.reference for item in self.evidence_handles}
        unknown = tuple(handle for handle in handles if handle not in lookup)
        if unknown:
            raise HandleBindingError(f"unknown or out-of-scope evidence handle: {unknown[0]}")
        return tuple(lookup[handle] for handle in handles)

    def resolve_child_claims(self, handles: tuple[str, ...]) -> tuple[str, ...]:
        _validate_returned_handles(handles, _CHILD_CLAIM_HANDLE, "child-claim")
        lookup = {item.handle: item.claim_id for item in self.child_claim_handles}
        unknown = tuple(handle for handle in handles if handle not in lookup)
        if unknown:
            raise HandleBindingError(f"unknown or out-of-scope child-claim handle: {unknown[0]}")
        return tuple(lookup[handle] for handle in handles)

    def resolve_support(
        self,
        *,
        evidence_handles: tuple[str, ...] = (),
        child_claim_handles: tuple[str, ...] = (),
    ) -> ClaimSupport:
        """Bind exactly one provider support class to exact persisted references."""

        if bool(evidence_handles) == bool(child_claim_handles):
            raise HandleBindingError("a claim must return exactly one non-empty support class")
        if evidence_handles:
            return ClaimSupport(
                SupportKind.DIRECT_EVIDENCE,
                direct_evidence=self.resolve_evidence(evidence_handles),
            )
        return ClaimSupport(
            SupportKind.CHILD_CLAIMS,
            child_claim_ids=self.resolve_child_claims(child_claim_handles),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "scope_id": self.scope_id,
            "allowed_owner_ids": list(self.allowed_owner_ids),
            "evidence_handles": [item.to_dict() for item in self.evidence_handles],
            "child_claim_handles": [item.to_dict() for item in self.child_claim_handles],
        }


@dataclass(frozen=True)
class ResolutionLimits:
    max_depth: int = 16
    max_claims: int = 512
    max_evidence: int = 1_024
    max_result_items: int = 1_536

    def __post_init__(self) -> None:
        for name in ("max_depth", "max_claims", "max_evidence", "max_result_items"):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class ResolvedClaimEvidence:
    root_claim_id: str
    traversed_claim_ids: tuple[str, ...]
    direct_evidence: tuple[AuthorityReference, ...]
    maximum_depth: int


type ClaimLookup = Callable[[str], NarrativeClaim | None]
type ClaimSource = Mapping[str, NarrativeClaim] | ClaimLookup
_DEFAULT_RESOLUTION_LIMITS = ResolutionLimits()


def resolve_claim_evidence(
    root_claim_id: str,
    claims: ClaimSource,
    *,
    limits: ResolutionLimits = _DEFAULT_RESOLUTION_LIMITS,
    allowed_claim_ids: frozenset[str] | None = None,
) -> ResolvedClaimEvidence:
    """Resolve one claim lazily, rejecting corrupt or unbounded transitive provenance.

    The lookup is invoked only as traversal reaches a claim.  This keeps the Detail/Evidence
    path independent of full-project materialization.
    """

    if not root_claim_id or root_claim_id != root_claim_id.strip():
        raise ClaimDagError("root claim ID must be a non-empty trimmed string")
    lookup: ClaimLookup = claims.get if isinstance(claims, Mapping) else claims

    visited: set[str] = set()
    active: set[str] = set()
    traversed: list[str] = []
    evidence: list[AuthorityReference] = []
    seen_evidence: set[AuthorityReference] = set()
    maximum_depth = 0

    def require_result_capacity() -> None:
        if len(traversed) > limits.max_claims:
            raise ClaimDagLimitError("claim traversal exceeded max_claims")
        if len(evidence) > limits.max_evidence:
            raise ClaimDagLimitError("claim traversal exceeded max_evidence")
        if len(traversed) + len(evidence) > limits.max_result_items:
            raise ClaimDagLimitError("claim traversal exceeded max_result_items")

    def walk(claim_id: str, depth: int) -> None:
        nonlocal maximum_depth
        if depth > limits.max_depth:
            raise ClaimDagLimitError("claim traversal exceeded max_depth")
        if allowed_claim_ids is not None and claim_id not in allowed_claim_ids:
            raise ClaimDagError(f"claim is outside the requested evidence scope: {claim_id}")
        if claim_id in active:
            raise ClaimDagError(f"claim DAG contains a cycle at {claim_id}")
        if claim_id in visited:
            return
        claim = lookup(claim_id)
        if claim is None:
            raise ClaimDagError(f"claim DAG references an unknown claim: {claim_id}")
        if claim.claim_id != claim_id:
            raise ClaimDagError(f"claim lookup returned corrupt identity for {claim_id}")
        active.add(claim_id)
        visited.add(claim_id)
        traversed.append(claim_id)
        maximum_depth = max(maximum_depth, depth)
        require_result_capacity()
        if claim.support.kind is SupportKind.DIRECT_EVIDENCE:
            for reference in claim.support.direct_evidence:
                if reference not in seen_evidence:
                    seen_evidence.add(reference)
                    evidence.append(reference)
                    require_result_capacity()
        else:
            for child_claim_id in claim.support.child_claim_ids:
                walk(child_claim_id, depth + 1)
        active.remove(claim_id)

    walk(root_claim_id, 0)
    return ResolvedClaimEvidence(
        root_claim_id=root_claim_id,
        traversed_claim_ids=tuple(traversed),
        direct_evidence=tuple(evidence),
        maximum_depth=maximum_depth,
    )


def _require_unique_strings(values: tuple[str, ...], label: str) -> None:
    for value in values:
        if not value or value != value.strip():
            raise HandleBindingError(f"{label} must be a non-empty trimmed string")
    if len(values) != len(set(values)):
        raise HandleBindingError(f"duplicate {label} values are not allowed")


def _validate_returned_handles(
    handles: tuple[str, ...], pattern: re.Pattern[str], label: str
) -> None:
    if not handles:
        raise HandleBindingError(f"{label} support handles cannot be empty")
    if len(handles) != len(set(handles)):
        raise HandleBindingError(f"duplicate {label} handles are not allowed")
    malformed = tuple(handle for handle in handles if pattern.fullmatch(handle) is None)
    if malformed:
        raise HandleBindingError(f"malformed {label} handle: {malformed[0]!r}")
