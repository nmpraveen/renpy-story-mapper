from __future__ import annotations

from dataclasses import replace

import pytest

from renpy_story_mapper.narrative.contracts import (
    ArtifactPublication,
    AuthorityBinding,
    AuthorityReference,
    AuthoritySystem,
    BudgetLimits,
    CacheIdentity,
    ClaimClass,
    ClaimSupport,
    ConsentManifest,
    CostConfidence,
    Coverage,
    InputRevision,
    LogicalJob,
    LogicalJobKind,
    LogicalJobSpec,
    NarrativeArtifact,
    NarrativeClaim,
    PrivacyMode,
    ProviderIdentity,
    ProviderSettings,
    RunEstimate,
    StructuralContext,
    SupportKind,
    TransportBatchPlan,
)


def _authority() -> AuthorityBinding:
    return AuthorityBinding(
        source_generation="source-generation",
        source_archive_hash="archive-hash",
        canonical_schema="canonical-schema",
        canonical_hash="canonical-hash",
        scene_schema="scene-schema",
        scene_hash="scene-hash",
        correction_hash="correction-hash",
        m12_result_identities=("route-result-a",),
    )


def _revision() -> InputRevision:
    return InputRevision(_authority(), "scene-input-v1", "normalized-input-hash")


def _provider(
    *,
    adapter_version: str = "adapter-v1",
    requested_model: str = "requested-runtime-model",
    resolved_model: str = "resolved-runtime-model",
    setting_value: str = "value-a",
) -> ProviderIdentity:
    return ProviderIdentity(
        provider="approved-cloud-provider",
        adapter="structured-process-adapter",
        adapter_version=adapter_version,
        requested_model=requested_model,
        resolved_model=resolved_model,
        settings=ProviderSettings((("provider_option", setting_value),)),
    )


def _scene_spec() -> LogicalJobSpec:
    return LogicalJobSpec(
        kind=LogicalJobKind.SCENE,
        owner_id="scene-a",
        context=StructuralContext(
            chapter_id="chapter-a",
            lane_id="lane-common",
            occurrence_id="occurrence-a",
            temporal_anchor="scene-a",
        ),
        locale="en-US",
        perspective="neutral",
    )


def _evidence() -> AuthorityReference:
    return AuthorityReference(AuthoritySystem.M10, "evidence", "evidence-a", "scene-a")


def test_logical_job_identity_is_provider_batch_and_revision_independent() -> None:
    spec = _scene_spec()
    first = LogicalJob(spec, _revision())
    second = LogicalJob(
        spec,
        replace(_revision(), normalized_input_hash="reprojected-input-hash"),
    )
    batch = TransportBatchPlan(
        "transport-v1",
        _provider(),
        ((spec.job_id, first.input_revision.identity),),
    )

    assert first.spec.job_id == second.spec.job_id
    assert first.input_revision.identity != second.input_revision.identity
    assert batch.batch_id not in first.to_dict().values()
    assert "provider" not in spec.identity_dict()
    assert "batch" not in spec.identity_dict()


def test_logical_identity_covers_order_context_partition_locale_and_perspective() -> None:
    context = StructuralContext(chapter_id="chapter-a", lane_id="route-a")
    segment = LogicalJobSpec(
        LogicalJobKind.SUMMARY_SEGMENT,
        "segment-owner",
        context,
        ("artifact-a", "artifact-b"),
        locale="en-US",
        perspective="neutral",
    )

    variants = (
        replace(segment, ordered_child_artifact_ids=("artifact-b", "artifact-a")),
        replace(segment, context=replace(context, lane_id="route-b")),
        replace(
            segment,
            context=replace(context, structural_fingerprint="changed-structure"),
        ),
        replace(segment, partition_version="partition-v-next"),
        replace(segment, locale="fr-FR"),
        replace(segment, perspective="character-a"),
    )

    assert len({segment.job_id, *(variant.job_id for variant in variants)}) == 7
    with pytest.raises(ValueError, match="require ordered child"):
        replace(segment, ordered_child_artifact_ids=())
    with pytest.raises(ValueError, match="cannot own child"):
        replace(_scene_spec(), ordered_child_artifact_ids=("artifact-a",))


def test_input_revision_binds_every_authority_and_normalized_input() -> None:
    first = _revision()
    variants = (
        replace(first, authority=replace(first.authority, canonical_hash="changed")),
        replace(first, authority=replace(first.authority, scene_hash="changed")),
        replace(
            first,
            authority=replace(first.authority, m12_result_identities=("route-result-b",)),
        ),
        replace(first, projection_schema="scene-input-v2"),
        replace(first, normalized_input_hash="changed"),
    )

    assert len({first.identity, *(variant.identity for variant in variants)}) == 6


def test_cache_key_binds_schema_provider_models_settings_and_normalized_input() -> None:
    spec = _scene_spec()
    revision = _revision()
    cache = CacheIdentity(
        spec.job_id,
        revision.identity,
        revision.normalized_input_hash,
        "scene-prompt-v1",
        "scene-response-v1",
        _provider(),
    )
    variants = (
        replace(cache, prompt_template_version="scene-prompt-v2"),
        replace(cache, response_schema_version="scene-response-v2"),
        replace(cache, provider=_provider(adapter_version="adapter-v2")),
        replace(cache, provider=_provider(requested_model="different-requested-model")),
        replace(cache, provider=_provider(resolved_model="different-resolved-model")),
        replace(cache, provider=_provider(setting_value="value-b")),
        replace(cache, normalized_input_hash="different-input"),
    )

    assert len({cache.key, *(variant.key for variant in variants)}) == 8
    same_settings_different_order = ProviderSettings((
        ("z_option", True),
        ("a_option", 1),
    ))
    reversed_settings = ProviderSettings(tuple(reversed(same_settings_different_order.values)))
    assert same_settings_different_order.to_dict() == reversed_settings.to_dict()
    with pytest.raises(ValueError, match="credentials"):
        ProviderSettings((("api_key", "must-not-persist"),))


def test_claim_contract_enforces_leaf_evidence_and_ancestor_child_claims() -> None:
    leaf_support = ClaimSupport(SupportKind.DIRECT_EVIDENCE, (_evidence(),))
    leaf = NarrativeClaim(
        "scene-job",
        LogicalJobKind.SCENE,
        0,
        ClaimClass.FACTUAL,
        "A supported scene fact.",
        leaf_support,
    )
    ancestor = NarrativeClaim(
        "chapter-job",
        LogicalJobKind.CHAPTER,
        0,
        ClaimClass.FACTUAL,
        "A supported chapter fact.",
        ClaimSupport(SupportKind.CHILD_CLAIMS, child_claim_ids=(leaf.claim_id,)),
    )

    assert ancestor.to_dict()["support"] == {
        "kind": "child_claims",
        "direct_evidence": [],
        "child_claim_ids": [leaf.claim_id],
    }
    with pytest.raises(ValueError, match="scene claims require direct evidence"):
        replace(leaf, support=ancestor.support)
    with pytest.raises(ValueError, match="chapter claims require child"):
        replace(ancestor, support=leaf.support)
    with pytest.raises(ValueError, match="only direct evidence"):
        ClaimSupport(
            SupportKind.DIRECT_EVIDENCE,
            (_evidence(),),
            (leaf.claim_id,),
        )


def test_claim_identity_binds_accepted_content_and_direct_support() -> None:
    original = NarrativeClaim(
        "scene-job",
        LogicalJobKind.SCENE,
        0,
        ClaimClass.FACTUAL,
        "First accepted wording.",
        ClaimSupport(SupportKind.DIRECT_EVIDENCE, (_evidence(),)),
    )
    regenerated = replace(original, text="Different accepted wording.")
    different_support = replace(
        original,
        support=ClaimSupport(
            SupportKind.DIRECT_EVIDENCE,
            (
                AuthorityReference(
                    AuthoritySystem.M10,
                    "evidence",
                    "evidence-two",
                    "scene-owner",
                ),
            ),
        ),
    )

    assert original.claim_id != regenerated.claim_id
    assert original.claim_id != different_support.claim_id
    assert original.claim_id == replace(original).claim_id


def test_partial_artifact_retains_valid_claims_and_explicit_coverage_warning() -> None:
    claim = NarrativeClaim(
        "segment-job",
        LogicalJobKind.SUMMARY_SEGMENT,
        0,
        ClaimClass.FACTUAL,
        "A retained supported claim.",
        ClaimSupport(SupportKind.CHILD_CLAIMS, child_claim_ids=("child-claim",)),
    )
    coverage = Coverage(
        expected_child_ids=("artifact-a", "artifact-b"),
        available_child_ids=("artifact-a",),
        missing_child_ids=("artifact-b",),
        valid_claim_count=1,
        invalid_claim_count=1,
    )
    artifact = NarrativeArtifact(
        "segment-job",
        "input-revision",
        LogicalJobKind.SUMMARY_SEGMENT,
        ArtifactPublication.PARTIAL,
        "Deterministic fallback title",
        "The valid portion remains available.",
        (claim,),
        coverage,
        warnings=("50% child coverage; one claim omitted",),
        used_deterministic_title=True,
    )

    assert artifact.coverage.child_coverage_basis_points == 5_000
    assert artifact.normalized_dict()["used_deterministic_title"] is True
    assert artifact.normalized_dict()["title_class"] == "deterministic_fallback"
    assert artifact.normalized_dict()["summary_class"] == "interpretive"
    assert artifact.artifact_id == replace(artifact).artifact_id
    with pytest.raises(ValueError, match="coverage warning"):
        replace(artifact, warnings=())
    with pytest.raises(ValueError, match="complete artifacts"):
        replace(artifact, publication=ArtifactPublication.COMPLETE)


def test_cloud_consent_is_manifest_bound_and_disabled_by_default() -> None:
    estimate = RunEstimate(
        logical_job_count=12,
        provider_call_count=3,
        input_tokens=4_000,
        output_tokens=1_000,
        estimated_cost_micros=None,
        cost_confidence=CostConfidence.UNAVAILABLE,
    )
    limits = BudgetLimits(
        max_provider_calls=4,
        max_input_tokens=5_000,
        max_output_tokens=2_000,
        max_total_tokens=7_000,
        timeout_seconds=120,
        max_concurrency=2,
        max_cost_micros=None,
    )
    manifest = ConsentManifest(
        run_id="run-a",
        provider=_provider(),
        selected_scope_ids=("chapter-a", "route-a"),
        privacy_mode=PrivacyMode.FACT_ONLY,
        includes_m12_material=True,
        estimate=estimate,
        limits=limits,
    )

    assert manifest.consent_granted is False
    assert manifest.to_dict()["estimate"] == estimate.to_dict()
    assert manifest.to_dict()["limits"] == limits.to_dict()
    assert replace(manifest, consent_granted=True).manifest_id != manifest.manifest_id
    assert replace(manifest, selected_scope_ids=("chapter-a",)).manifest_id != manifest.manifest_id


def test_transport_batch_is_operational_and_does_not_redefine_logical_identity() -> None:
    job_id = _scene_spec().job_id
    first = TransportBatchPlan(
        "transport-v1",
        _provider(),
        ((job_id, _revision().identity),),
    )
    second = replace(first, provider=_provider(resolved_model="another-resolved-model"))

    assert first.batch_id != second.batch_id
    assert first.items[0][0] == second.items[0][0] == job_id
    with pytest.raises(ValueError, match="unique"):
        replace(first, items=(first.items[0], first.items[0]))
