from __future__ import annotations

from dataclasses import replace

from renpy_story_mapper.narrative.contracts import (
    ArtifactPublication,
    AuthorityReference,
    AuthoritySystem,
    ClaimClass,
    ClaimPolarity,
    ClaimSemantics,
    ClaimSupport,
    LogicalJobKind,
    LogicalJobSpec,
    NarrativeClaim,
    StructuralContext,
    SupportKind,
)
from renpy_story_mapper.narrative.evidence import PromptHandleTable
from renpy_story_mapper.narrative.validation import (
    ContextualClaim,
    ContradictionSeverity,
    RepairRequest,
    ValidationContext,
    contradiction_findings,
    validate_and_salvage,
)


def _scene_job(
    *,
    owner: str = "scene-a",
    lane: str = "lane-common",
    route: str | None = None,
    temporal: str = "scene-a",
    occurrence: str | None = None,
) -> LogicalJobSpec:
    return LogicalJobSpec(
        LogicalJobKind.SCENE,
        owner,
        StructuralContext(
            chapter_id="chapter-a",
            lane_id=lane,
            route_id=route,
            occurrence_id=occurrence,
            call_site_id=(f"call-{occurrence}" if occurrence else None),
            temporal_anchor=temporal,
        ),
        locale="en-US",
        perspective="neutral",
    )


def _scene_context(job: LogicalJobSpec | None = None) -> ValidationContext:
    spec = job or _scene_job()
    reference = AuthorityReference(AuthoritySystem.M10, "evidence", "evidence-a", spec.owner_id)
    handles = PromptHandleTable.build(
        scope_id=spec.job_id,
        allowed_owner_ids=(spec.owner_id,),
        evidence_references=(reference,),
    )
    return ValidationContext(
        spec,
        "input-revision-a",
        handles,
        deterministic_title="M11 Scene A",
    )


def _provider_claim(
    *,
    claim_class: str = "factual",
    evidence: list[str] | None = None,
    children: list[str] | None = None,
    value: str = "present",
    polarity: str = "positive",
    text: str = "Alice is present.",
) -> dict[str, object]:
    return {
        "claim_class": claim_class,
        "text": text,
        "evidence_handles": ["E1"] if evidence is None else evidence,
        "child_claim_handles": [] if children is None else children,
        "subject": "Alice",
        "predicate": "presence",
        "polarity": polarity,
        "normalized_value": value,
    }


def _provider_artifact(job_id: str, claims: list[object]) -> dict[str, object]:
    return {
        "logical_job_id": job_id,
        "title": "Arrival",
        "summary": "Alice arrives in the scene.",
        "claims": claims,
    }


def test_valid_scene_output_publishes_complete_owned_claims() -> None:
    context = _scene_context()

    result = validate_and_salvage(
        _provider_artifact(context.job.job_id, [_provider_claim()]),
        context,
    )

    assert result.repair_attempts == 0
    assert result.issues == ()
    assert result.artifact is not None
    assert result.artifact.publication is ArtifactPublication.COMPLETE
    assert result.artifact.claims[0].support.direct_evidence[0].owner_id == "scene-a"
    assert result.artifact.claims[0].semantics == ClaimSemantics(
        "Alice", "presence", ClaimPolarity.POSITIVE, "present"
    )


def test_invalid_title_and_unsupported_interpretation_salvage_valid_factual_work() -> None:
    context = _scene_context()
    raw = _provider_artifact(
        context.job.job_id,
        [
            _provider_claim(),
            _provider_claim(
                claim_class="interpretive",
                evidence=["E999"],
                text="Alice secretly wants to leave.",
                value="leave",
            ),
        ],
    )
    raw["title"] = " "

    result = validate_and_salvage(raw, context)

    assert result.artifact is not None
    assert result.artifact.publication is ArtifactPublication.PARTIAL
    assert result.artifact.title == "M11 Scene A"
    assert result.artifact.used_deterministic_title is True
    assert len(result.artifact.claims) == 1
    assert result.artifact.coverage.invalid_claim_count == 1
    assert any("invalid claim" in warning for warning in result.artifact.warnings)


def test_one_targeted_repair_replaces_only_invalid_claim_and_title() -> None:
    context = _scene_context()
    valid = _provider_claim()
    invalid = _provider_claim(evidence=["E404"], text="Bob is absent.", value="absent")
    raw = _provider_artifact(context.job.job_id, [valid, invalid])
    raw["title"] = ""
    requests: list[RepairRequest] = []

    def repair(request: RepairRequest) -> object:
        requests.append(request)
        return {
            "logical_job_id": context.job.job_id,
            "title": "Arrival",
            "claims": [
                {
                    "ordinal": 1,
                    **_provider_claim(
                        text="Bob is absent.",
                        value="absent",
                    ),
                }
            ],
        }

    result = validate_and_salvage(raw, context, repair=repair)

    assert result.repair_attempts == 1
    assert len(requests) == 1
    assert requests[0].invalid_claim_ordinals == (1,)
    assert requests[0].invalid_fields == ("title",)
    assert result.artifact is not None
    assert result.artifact.publication is ArtifactPublication.COMPLETE
    assert [claim.ordinal for claim in result.artifact.claims] == [0, 1]
    assert result.artifact.claims[0].text == "Alice is present."


def test_failed_repair_retains_primary_valid_claims_and_never_retries_twice() -> None:
    context = _scene_context()
    raw = _provider_artifact(
        context.job.job_id,
        [_provider_claim(), _provider_claim(evidence=["E404"], text="Unsupported")],
    )
    calls = 0

    def repair(_request: RepairRequest) -> object:
        nonlocal calls
        calls += 1
        return {"logical_job_id": context.job.job_id, "claims": "still malformed"}

    result = validate_and_salvage(raw, context, repair=repair)

    assert calls == result.repair_attempts == 1
    assert result.artifact is not None
    assert result.artifact.publication is ArtifactPublication.PARTIAL
    assert [claim.text for claim in result.artifact.claims] == ["Alice is present."]
    assert any(issue.code == "repair_exhausted" for issue in result.issues)


def test_authority_binding_corruption_rejects_without_repair() -> None:
    context = _scene_context()
    calls = 0

    def repair(_request: RepairRequest) -> object:
        nonlocal calls
        calls += 1
        return _provider_artifact(context.job.job_id, [_provider_claim()])

    result = validate_and_salvage(
        _provider_artifact("foreign-job", [_provider_claim()]),
        context,
        repair=repair,
    )

    assert result.artifact is None
    assert result.rejected_reason == "authority_binding_invalid"
    assert result.repair_attempts == calls == 0


def test_one_schema_repair_can_rescue_unparseable_core() -> None:
    context = _scene_context()

    result = validate_and_salvage(
        "not an object",
        context,
        repair=lambda request: _provider_artifact(
            request.logical_job_id,
            [_provider_claim()],
        ),
    )

    assert result.repair_attempts == 1
    assert result.artifact is not None
    assert result.artifact.publication is ArtifactPublication.COMPLETE


def test_zero_supported_claims_rejects_unsafe_artifact() -> None:
    context = _scene_context()

    result = validate_and_salvage(
        _provider_artifact(context.job.job_id, [_provider_claim(evidence=["E404"])]),
        context,
    )

    assert result.artifact is None
    assert result.rejected_reason == "no_safe_claims"


def _persisted_claim(
    job: LogicalJobSpec,
    *,
    ordinal: int,
    claim_class: ClaimClass,
    value: str,
    polarity: ClaimPolarity = ClaimPolarity.POSITIVE,
) -> ContextualClaim:
    claim = NarrativeClaim(
        logical_job_id=job.job_id,
        job_kind=job.kind,
        ordinal=ordinal,
        claim_class=claim_class,
        text=f"Trust is {value}.",
        support=ClaimSupport(
            SupportKind.DIRECT_EVIDENCE,
            (
                AuthorityReference(
                    AuthoritySystem.M10,
                    "evidence",
                    f"evidence-{job.owner_id}-{ordinal}",
                    job.owner_id,
                ),
            ),
        ),
        semantics=ClaimSemantics("Alice", "trust", polarity, value),
    )
    return ContextualClaim(claim, job)


def test_factual_conflict_requires_same_route_temporal_occurrence_and_class_context() -> None:
    base = _scene_job(route="route-a", occurrence="occurrence-a")
    same_context = replace(base, owner_id="scene-a-copy")
    # Scene identity itself is a temporal anchor for scene claims, so use the same owner for a
    # same-scene contradiction and a different ordinal to retain distinct claim IDs.
    left = _persisted_claim(base, ordinal=0, claim_class=ClaimClass.FACTUAL, value="high")
    right = _persisted_claim(base, ordinal=1, claim_class=ClaimClass.FACTUAL, value="low")
    assert same_context.context == base.context

    findings = contradiction_findings((left, right))

    assert len(findings) == 1
    assert findings[0].severity is ContradictionSeverity.AUTHORITY_VIOLATION
    assert findings[0].left_identity.route_id == "route-a"
    assert findings[0].left_identity.occurrence_id == "occurrence-a"


def test_mutually_exclusive_routes_and_temporal_change_do_not_false_positive() -> None:
    route_a = _scene_job(route="route-a", temporal="chapter-start")
    route_b = _scene_job(route="route-b", temporal="chapter-start")
    later = _scene_job(route="route-a", temporal="chapter-end")
    claims = (
        _persisted_claim(route_a, ordinal=0, claim_class=ClaimClass.FACTUAL, value="low"),
        _persisted_claim(route_b, ordinal=0, claim_class=ClaimClass.FACTUAL, value="high"),
        _persisted_claim(later, ordinal=0, claim_class=ClaimClass.FACTUAL, value="high"),
    )

    assert contradiction_findings(claims) == ()


def test_interpretive_disagreement_is_review_warning_not_authority_violation() -> None:
    job = _scene_job()
    left = _persisted_claim(
        job,
        ordinal=0,
        claim_class=ClaimClass.INTERPRETIVE,
        value="protective",
    )
    right = _persisted_claim(
        job,
        ordinal=1,
        claim_class=ClaimClass.INTERPRETIVE,
        value="controlling",
    )

    finding = contradiction_findings((left, right))[0]

    assert finding.severity is ContradictionSeverity.REVIEW_WARNING
