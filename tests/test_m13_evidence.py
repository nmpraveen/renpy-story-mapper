from __future__ import annotations

from dataclasses import replace

import pytest

from renpy_story_mapper.narrative.contracts import (
    AuthorityReference,
    AuthoritySystem,
    ClaimClass,
    ClaimSupport,
    LogicalJobKind,
    NarrativeClaim,
    SupportKind,
)
from renpy_story_mapper.narrative.evidence import (
    ClaimDagError,
    ClaimDagLimitError,
    HandleBindingError,
    PromptChildClaimHandle,
    PromptEvidenceHandle,
    PromptHandleTable,
    ResolutionLimits,
    resolve_claim_evidence,
)


def _reference(record_id: str, owner_id: str = "scene-a") -> AuthorityReference:
    return AuthorityReference(AuthoritySystem.M10, "evidence", record_id, owner_id)


def _leaf(
    *, job_id: str, ordinal: int, reference: AuthorityReference
) -> NarrativeClaim:
    return NarrativeClaim(
        job_id,
        LogicalJobKind.SCENE,
        ordinal,
        ClaimClass.FACTUAL,
        f"Supported leaf {ordinal}.",
        ClaimSupport(SupportKind.DIRECT_EVIDENCE, (reference,)),
    )


def _ancestor(
    *,
    job_id: str,
    ordinal: int,
    children: tuple[str, ...],
    kind: LogicalJobKind = LogicalJobKind.SUMMARY_SEGMENT,
) -> NarrativeClaim:
    return NarrativeClaim(
        job_id,
        kind,
        ordinal,
        ClaimClass.FACTUAL,
        f"Supported ancestor {ordinal}.",
        ClaimSupport(SupportKind.CHILD_CLAIMS, child_claim_ids=children),
    )


def test_handle_tables_are_deterministic_and_bind_exact_authority() -> None:
    first = PromptHandleTable.build(
        scope_id="scene-scope",
        allowed_owner_ids=("scene-b", "scene-a"),
        evidence_references=(_reference("evidence-b", "scene-b"), _reference("evidence-a")),
        child_claim_ids=("claim-b", "claim-a"),
    )
    second = PromptHandleTable.build(
        scope_id="scene-scope",
        allowed_owner_ids=("scene-a", "scene-b"),
        evidence_references=tuple(
            reversed((_reference("evidence-b", "scene-b"), _reference("evidence-a")))
        ),
        child_claim_ids=("claim-a", "claim-b"),
    )

    assert first == second
    assert tuple(item.handle for item in first.evidence_handles) == ("E1", "E2")
    assert tuple(item.handle for item in first.child_claim_handles) == ("C1", "C2")
    assert first.resolve_evidence(("E2", "E1")) == tuple(
        item.reference for item in reversed(first.evidence_handles)
    )
    assert first.resolve_child_claims(("C1",)) == ("claim-a",)


def test_handles_reject_duplicate_malformed_unknown_and_out_of_scope_values() -> None:
    reference = _reference("evidence-a")
    table = PromptHandleTable.build(
        scope_id="scene-scope",
        allowed_owner_ids=("scene-a",),
        evidence_references=(reference,),
        child_claim_ids=("claim-a",),
    )

    with pytest.raises(HandleBindingError, match="duplicate authority"):
        PromptHandleTable.build(
            scope_id="scene-scope",
            allowed_owner_ids=("scene-a",),
            evidence_references=(reference, reference),
        )
    with pytest.raises(HandleBindingError, match="out-of-scope owner"):
        PromptHandleTable.build(
            scope_id="scene-scope",
            allowed_owner_ids=("scene-a",),
            evidence_references=(_reference("evidence-b", "scene-b"),),
        )
    with pytest.raises(HandleBindingError, match="duplicate evidence handles"):
        table.resolve_evidence(("E1", "E1"))
    with pytest.raises(HandleBindingError, match="malformed evidence"):
        table.resolve_evidence(("C1",))
    with pytest.raises(HandleBindingError, match="unknown or out-of-scope evidence"):
        table.resolve_evidence(("E2",))
    with pytest.raises(HandleBindingError, match="unknown or out-of-scope child"):
        table.resolve_child_claims(("C2",))
    with pytest.raises(HandleBindingError, match="contiguous E1"):
        PromptHandleTable(
            "scene-scope",
            ("scene-a",),
            (PromptEvidenceHandle("E2", reference),),
        )
    with pytest.raises(HandleBindingError, match="malformed child"):
        PromptChildClaimHandle("C0", "claim-a")


def test_support_binding_accepts_exactly_one_handle_class() -> None:
    table = PromptHandleTable.build(
        scope_id="scope",
        allowed_owner_ids=("scene-a",),
        evidence_references=(_reference("evidence-a"),),
        child_claim_ids=("claim-a",),
    )

    assert table.resolve_support(evidence_handles=("E1",)).direct_evidence == (
        _reference("evidence-a"),
    )
    assert table.resolve_support(child_claim_handles=("C1",)).child_claim_ids == ("claim-a",)
    with pytest.raises(HandleBindingError, match="exactly one"):
        table.resolve_support()
    with pytest.raises(HandleBindingError, match="exactly one"):
        table.resolve_support(evidence_handles=("E1",), child_claim_handles=("C1",))


def test_lazy_claim_dag_resolution_returns_direct_evidence_without_flattening() -> None:
    leaf_a = _leaf(job_id="scene-job-a", ordinal=0, reference=_reference("evidence-a"))
    leaf_b = _leaf(job_id="scene-job-b", ordinal=0, reference=_reference("evidence-b", "scene-b"))
    segment = _ancestor(
        job_id="segment-job",
        ordinal=0,
        children=(leaf_a.claim_id, leaf_b.claim_id),
    )
    chapter = _ancestor(
        job_id="chapter-job",
        ordinal=0,
        children=(segment.claim_id,),
        kind=LogicalJobKind.CHAPTER,
    )
    claims = {item.claim_id: item for item in (leaf_a, leaf_b, segment, chapter)}
    requested: list[str] = []

    def lookup(claim_id: str) -> NarrativeClaim | None:
        requested.append(claim_id)
        return claims.get(claim_id)

    resolved = resolve_claim_evidence(chapter.claim_id, lookup)

    assert requested == list(resolved.traversed_claim_ids)
    assert resolved.traversed_claim_ids == (
        chapter.claim_id,
        segment.claim_id,
        leaf_a.claim_id,
        leaf_b.claim_id,
    )
    assert resolved.direct_evidence == (
        _reference("evidence-a"),
        _reference("evidence-b", "scene-b"),
    )
    assert resolved.maximum_depth == 2
    assert chapter.to_dict()["support"]["direct_evidence"] == []
    assert segment.to_dict()["support"]["direct_evidence"] == []


def test_claim_dag_deduplicates_shared_leaf_evidence_but_not_claim_identity() -> None:
    leaf = _leaf(job_id="scene-job", ordinal=0, reference=_reference("evidence-a"))
    left = _ancestor(job_id="segment-left", ordinal=0, children=(leaf.claim_id,))
    right = _ancestor(job_id="segment-right", ordinal=0, children=(leaf.claim_id,))
    root = _ancestor(
        job_id="chapter-job",
        ordinal=0,
        children=(left.claim_id, right.claim_id),
        kind=LogicalJobKind.CHAPTER,
    )
    claims = {item.claim_id: item for item in (leaf, left, right, root)}

    resolved = resolve_claim_evidence(root.claim_id, claims)

    assert len(resolved.traversed_claim_ids) == 4
    assert resolved.direct_evidence == (_reference("evidence-a"),)


def test_claim_dag_rejects_cycles_unknown_children_and_out_of_scope_claims() -> None:
    seed_a = _ancestor(job_id="segment-a", ordinal=0, children=("placeholder-a",))
    seed_b = _ancestor(job_id="segment-b", ordinal=0, children=("placeholder-b",))
    claim_a = replace(
        seed_a,
        support=ClaimSupport(SupportKind.CHILD_CLAIMS, child_claim_ids=(seed_b.claim_id,)),
    )
    claim_b = replace(
        seed_b,
        support=ClaimSupport(SupportKind.CHILD_CLAIMS, child_claim_ids=(seed_a.claim_id,)),
    )
    cyclic = {claim_a.claim_id: claim_a, claim_b.claim_id: claim_b}

    with pytest.raises(ClaimDagError, match="cycle"):
        resolve_claim_evidence(claim_a.claim_id, cyclic)
    unknown = _ancestor(job_id="segment-unknown", ordinal=0, children=("missing-claim",))
    with pytest.raises(ClaimDagError, match="unknown claim"):
        resolve_claim_evidence(unknown.claim_id, {unknown.claim_id: unknown})
    leaf = _leaf(job_id="scene-job", ordinal=0, reference=_reference("evidence-a"))
    root = _ancestor(job_id="segment-root", ordinal=0, children=(leaf.claim_id,))
    with pytest.raises(ClaimDagError, match="outside"):
        resolve_claim_evidence(
            root.claim_id,
            {root.claim_id: root, leaf.claim_id: leaf},
            allowed_claim_ids=frozenset({root.claim_id}),
        )


@pytest.mark.parametrize(
    ("limits", "message"),
    (
        (ResolutionLimits(max_depth=1), "max_depth"),
        (ResolutionLimits(max_claims=2), "max_claims"),
        (ResolutionLimits(max_evidence=1), "max_evidence"),
        (ResolutionLimits(max_result_items=3), "max_result_items"),
    ),
)
def test_claim_dag_enforces_depth_claim_evidence_and_total_result_limits(
    limits: ResolutionLimits, message: str
) -> None:
    leaf_a = _leaf(job_id="scene-a", ordinal=0, reference=_reference("evidence-a"))
    leaf_b = _leaf(job_id="scene-b", ordinal=0, reference=_reference("evidence-b", "scene-b"))
    segment = _ancestor(
        job_id="segment-job",
        ordinal=0,
        children=(leaf_a.claim_id, leaf_b.claim_id),
    )
    root = _ancestor(
        job_id="chapter-job",
        ordinal=0,
        children=(segment.claim_id,),
        kind=LogicalJobKind.CHAPTER,
    )
    claims = {item.claim_id: item for item in (leaf_a, leaf_b, segment, root)}

    with pytest.raises(ClaimDagLimitError, match=message):
        resolve_claim_evidence(root.claim_id, claims, limits=limits)
