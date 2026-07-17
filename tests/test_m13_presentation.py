from __future__ import annotations

from pathlib import Path

import pytest

from renpy_story_mapper.narrative.authority import load_narrative_authority
from renpy_story_mapper.narrative.contracts import (
    ArtifactPublication,
    AuthorityReference,
    AuthoritySystem,
    CacheIdentity,
    ClaimClass,
    ClaimPolarity,
    ClaimSemantics,
    ClaimSupport,
    Coverage,
    LogicalJobKind,
    NarrativeArtifact,
    NarrativeClaim,
    ProviderIdentity,
    ProviderSettings,
    SupportKind,
)
from renpy_story_mapper.narrative.preparation import prepare_scene_jobs
from renpy_story_mapper.narrative.presentation import (
    narrative_artifact_detail,
    narrative_claim_citations,
    narrative_snapshot,
)
from renpy_story_mapper.narrative.projection import NarrativeInputMode
from renpy_story_mapper.project import Project, create_ingested_project

FIXTURE = Path(__file__).parent / "fixtures" / "m12" / "route_targets.rpy"


def _project(tmp_path: Path) -> Project:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    return create_ingested_project(tmp_path / "m13-presentation.rsmproj", source)


def _provider() -> ProviderIdentity:
    return ProviderIdentity(
        provider="approved-cloud",
        adapter="structured-adapter",
        adapter_version="adapter-v1",
        requested_model="selected-model",
        resolved_model="selected-model",
        settings=ProviderSettings(),
    )


def _publish_one(project: Project) -> tuple[NarrativeArtifact, NarrativeClaim]:
    authority = load_narrative_authority(project, include_m12=False)
    prepared = prepare_scene_jobs(authority, mode=NarrativeInputMode.FACT_ONLY)[0]
    evidence = next(
        item.reference
        for item in prepared.handles.evidence_handles
        if item.reference.authority is AuthoritySystem.M10
        and item.reference.record_kind == "evidence"
    )
    claim = NarrativeClaim(
        logical_job_id=prepared.job.spec.job_id,
        job_kind=prepared.job.spec.kind,
        ordinal=0,
        claim_class=ClaimClass.FACTUAL,
        text="The scene contains this evidenced story event.",
        support=ClaimSupport(SupportKind.DIRECT_EVIDENCE, direct_evidence=(evidence,)),
        semantics=ClaimSemantics(
            subject="scene",
            predicate="contains",
            polarity=ClaimPolarity.POSITIVE,
            normalized_value="story event",
        ),
    )
    artifact = NarrativeArtifact(
        logical_job_id=prepared.job.spec.job_id,
        input_revision_id=prepared.job.input_revision.identity,
        job_kind=prepared.job.spec.kind,
        publication=ArtifactPublication.COMPLETE,
        title="Narrative scene title",
        summary="A concise evidenced scene summary.",
        claims=(claim,),
        coverage=Coverage(valid_claim_count=1),
    )
    cache = CacheIdentity(
        logical_job_id=prepared.job.spec.job_id,
        input_revision_id=prepared.job.input_revision.identity,
        normalized_input_hash=prepared.job.input_revision.normalized_input_hash,
        prompt_template_version="prompt-v1",
        response_schema_version="response-v1",
        provider=_provider(),
    )
    project.m13_persistence().publish_validated(
        job_id=prepared.job.spec.job_id,
        job={**prepared.job.to_dict(), "status": "succeeded"},
        claims={claim.claim_id: claim.to_dict()},
        claim_edges={},
        artifact_id=artifact.artifact_id,
        artifact=artifact.normalized_dict(),
        cache_identity=cache.to_dict(),
        authority_binding=authority.binding.to_dict(),
    )
    return artifact, claim


def test_snapshot_is_current_bounded_and_cloud_disabled_by_default(tmp_path: Path) -> None:
    with _project(tmp_path) as project:
        artifact, _claim = _publish_one(project)
        snapshot = narrative_snapshot(project, limit=10)

    assert snapshot["status"] == "available"
    assert snapshot["cloud_enabled"] is False
    assert snapshot["total"] == 1
    jobs = snapshot["jobs"]
    assert isinstance(jobs, list)
    assert jobs[0]["artifact"]["artifact_id"] == artifact.artifact_id
    coverage = snapshot["coverage"]
    assert isinstance(coverage, dict)
    assert coverage["published_scene_jobs"] == 1
    assert coverage["expected_scene_jobs"] >= 1


def test_artifact_detail_and_lazy_claim_citations_are_exact(tmp_path: Path) -> None:
    with _project(tmp_path) as project:
        artifact, claim = _publish_one(project)
        detail = narrative_artifact_detail(project, artifact.artifact_id)
        citations = narrative_claim_citations(project, claim.claim_id)

    assert detail["title"] == artifact.title
    assert detail["publication"] == "complete"
    assert detail["claims"][0]["claim_id"] == claim.claim_id
    assert citations["traversed_claim_ids"] == [claim.claim_id]
    citation = citations["citations"][0]
    assert citation["authority"] == "m10"
    assert citation["record_kind"] == "evidence"
    assert citation["record_id"] == claim.support.direct_evidence[0].record_id
    assert citations["schema"] == "m13-narrative-claim-navigation-v1"
    assert citations["citation_count"] == 1
    assert citations["authority_labels"] == ["M10 evidence"]
    assert citations["claim_path"] == [claim.claim_id]
    assert citation["label"] == "M10 evidence"
    assert citation["navigation"] == {
        "mode": "canonical",
        "element_id": citation["record_id"],
        "focus_record_id": citation["record_id"],
    }
    assert "record" not in citation


def test_citation_ownership_corruption_fails_closed(tmp_path: Path) -> None:
    with _project(tmp_path) as project:
        artifact, claim = _publish_one(project)
        foreign_claim = NarrativeClaim(
            logical_job_id=claim.logical_job_id,
            job_kind=claim.job_kind,
            ordinal=1,
            claim_class=claim.claim_class,
            text=claim.text,
            support=ClaimSupport(
                SupportKind.DIRECT_EVIDENCE,
                direct_evidence=(
                    AuthorityReference(
                        claim.support.direct_evidence[0].authority,
                        claim.support.direct_evidence[0].record_kind,
                        claim.support.direct_evidence[0].record_id,
                        "foreign-scene",
                    ),
                ),
            ),
            semantics=claim.semantics,
        )
        authority = load_narrative_authority(project, include_m12=False)
        project.m13_persistence().put_claim(
            foreign_claim.claim_id,
            foreign_claim.to_dict(),
            authority_binding=authority.binding.to_dict(),
        )
        with pytest.raises(ValueError, match="ownership"):
            narrative_claim_citations(project, foreign_claim.claim_id)

        assert narrative_artifact_detail(project, artifact.artifact_id)["status"] == "available"


def test_lazy_citation_navigation_retains_the_exact_root_to_leaf_claim_path(
    tmp_path: Path,
) -> None:
    with _project(tmp_path) as project:
        _artifact, leaf_claim = _publish_one(project)
        root_claim = NarrativeClaim(
            logical_job_id=leaf_claim.logical_job_id,
            job_kind=LogicalJobKind.PLOT,
            ordinal=1,
            claim_class=ClaimClass.INTERPRETIVE,
            text="This interpretation is supported by the factual child claim.",
            support=ClaimSupport(
                SupportKind.CHILD_CLAIMS,
                child_claim_ids=(leaf_claim.claim_id,),
            ),
            semantics=ClaimSemantics(
                subject="scene",
                predicate="interprets",
                polarity=ClaimPolarity.POSITIVE,
                normalized_value="factual child",
            ),
        )
        authority = load_narrative_authority(project, include_m12=False)
        project.m13_persistence().put_claim(
            root_claim.claim_id,
            root_claim.to_dict(),
            authority_binding=authority.binding.to_dict(),
        )

        citations = narrative_claim_citations(project, root_claim.claim_id)

    assert citations["traversed_claim_ids"] == [
        root_claim.claim_id,
        leaf_claim.claim_id,
    ]
    assert citations["citations"][0]["claim_path"] == [
        root_claim.claim_id,
        leaf_claim.claim_id,
    ]
