from __future__ import annotations

from renpy_story_mapper.narrative.contracts import (
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
from renpy_story_mapper.narrative.validation import (
    ContextualClaim,
    ContradictionSeverity,
    contradiction_findings,
)


def _job(
    *,
    lane: str = "lane-a",
    route: str = "route-a",
    chapter: str = "chapter-a",
    temporal: str = "scene-a:before",
    occurrence: str | None = "occurrence-a",
    call_site: str | None = "call-site-a",
) -> LogicalJobSpec:
    return LogicalJobSpec(
        kind=LogicalJobKind.SCENE,
        owner_id="scene-a",
        context=StructuralContext(
            chapter_id=chapter,
            lane_id=lane,
            route_id=route,
            temporal_anchor=temporal,
            occurrence_id=occurrence,
            call_site_id=call_site,
        ),
        locale="en-US",
        perspective="reader",
    )


def _claim(
    job: LogicalJobSpec,
    ordinal: int,
    value: str,
    *,
    claim_class: ClaimClass = ClaimClass.FACTUAL,
    polarity: ClaimPolarity = ClaimPolarity.POSITIVE,
) -> ContextualClaim:
    return ContextualClaim(
        NarrativeClaim(
            logical_job_id=job.job_id,
            job_kind=LogicalJobKind.SCENE,
            ordinal=ordinal,
            claim_class=claim_class,
            text=f"Claim {ordinal}: {value}",
            support=ClaimSupport(
                SupportKind.DIRECT_EVIDENCE,
                direct_evidence=(
                    AuthorityReference(
                        AuthoritySystem.M10,
                        "evidence",
                        f"evidence-{ordinal}",
                        "scene-a",
                    ),
                ),
            ),
            semantics=ClaimSemantics(
                subject="Character A",
                predicate="relationship state",
                polarity=polarity,
                normalized_value=value,
            ),
        ),
        job,
    )


def test_factual_conflict_in_identical_full_context_is_authority_violation() -> None:
    job = _job()
    left = _claim(job, 0, "trusted")
    right = _claim(job, 1, "distrusted")

    findings = contradiction_findings((left, right))

    assert len(findings) == 1
    assert findings[0].severity is ContradictionSeverity.AUTHORITY_VIOLATION
    identity = left.identity()
    assert identity.lane_id == "lane-a"
    assert identity.route_id == "route-a"
    assert identity.scene_id == "scene-a"
    assert identity.chapter_id == "chapter-a"
    assert identity.temporal_anchor == "scene-a:before"
    assert identity.occurrence_id == "occurrence-a"
    assert identity.call_site_id == "call-site-a"
    assert identity.claim_class is ClaimClass.FACTUAL
    assert identity.subject == "character a"
    assert identity.predicate == "relationship state"
    assert identity.polarity is ClaimPolarity.POSITIVE
    assert identity.normalized_value == "trusted"


def test_mutually_exclusive_routes_and_lanes_do_not_conflict() -> None:
    route_a = _claim(_job(lane="lane-a", route="route-a"), 0, "trusted")
    route_b = _claim(_job(lane="lane-b", route="route-b"), 0, "distrusted")

    assert contradiction_findings((route_a, route_b)) == ()


def test_legitimate_temporal_character_change_does_not_conflict() -> None:
    before = _claim(_job(temporal="chapter-a:before-turn"), 0, "distrusted")
    after = _claim(_job(temporal="chapter-a:after-turn"), 0, "trusted")
    other_chapter = _claim(
        _job(chapter="chapter-b", temporal="chapter-b:after-turn"),
        0,
        "allied",
    )

    assert contradiction_findings((before, after, other_chapter)) == ()


def test_occurrence_and_call_contexts_are_independent() -> None:
    first_call = _claim(
        _job(occurrence="occurrence-a", call_site="call-site-a"),
        0,
        "present",
    )
    second_call = _claim(
        _job(occurrence="occurrence-b", call_site="call-site-b"),
        0,
        "absent",
    )

    assert contradiction_findings((first_call, second_call)) == ()


def test_interpretive_disagreement_is_review_warning_not_authority_violation() -> None:
    job = _job()
    hopeful = _claim(
        job,
        0,
        "hopeful",
        claim_class=ClaimClass.INTERPRETIVE,
    )
    guarded = _claim(
        job,
        1,
        "guarded",
        claim_class=ClaimClass.INTERPRETIVE,
    )

    findings = contradiction_findings((hopeful, guarded))

    assert len(findings) == 1
    assert findings[0].severity is ContradictionSeverity.REVIEW_WARNING


def test_factual_and_interpretive_classes_are_not_treated_as_same_assertion() -> None:
    job = _job()
    factual = _claim(job, 0, "silent", claim_class=ClaimClass.FACTUAL)
    interpretation = _claim(
        job,
        1,
        "withdrawn",
        claim_class=ClaimClass.INTERPRETIVE,
    )

    assert contradiction_findings((factual, interpretation)) == ()


def test_case_normalization_avoids_false_positive_but_polarity_remains_identity() -> None:
    job = _job()
    first = _claim(job, 0, "Trusted")
    same = _claim(job, 1, "TRUSTED")
    negative = _claim(job, 2, "trusted", polarity=ClaimPolarity.NEGATIVE)

    assert contradiction_findings((first, same)) == ()
    findings = contradiction_findings((first, negative))
    assert len(findings) == 1
    assert findings[0].left_identity.polarity is ClaimPolarity.POSITIVE
    assert findings[0].right_identity.polarity is ClaimPolarity.NEGATIVE
