from __future__ import annotations

import pytest

from renpy_story_mapper.narrative.batching import (
    BatchableSceneJob,
    BatchItemStatus,
    BatchLimits,
    evaluate_batch_output,
    pack_scene_jobs,
    recursive_singleton_batches,
    split_transport_batch,
    split_unusable_batch,
)


def _job(index: int, *, chars: int = 100, tokens: int = 25) -> BatchableSceneJob:
    return BatchableSceneJob(
        logical_job_id=f"scene-job-{index}",
        input_revision=f"revision-{index}",
        ordinal=index,
        input_chars=chars,
        estimated_input_tokens=tokens,
    )


def _mapping_output(owner: str, value: object) -> dict[str, object]:
    return {"owner": owner, "value": value}


def _validate_owned_output(logical_job_id: str, output: object) -> object:
    if not isinstance(output, dict) or set(output) != {"owner", "value"}:
        raise ValueError("invalid output shape")
    if output["owner"] != logical_job_id:
        raise ValueError("cross-owned output")
    return dict(output)


def test_packing_is_deterministic_bounded_and_does_not_change_logical_identity() -> None:
    jobs = tuple(_job(index) for index in range(7))
    limits = BatchLimits(
        maximum_items=3,
        maximum_input_chars=350,
        maximum_input_tokens=100,
    )

    first = pack_scene_jobs(tuple(reversed(jobs)), limits)
    replay = pack_scene_jobs(jobs, limits)

    assert first == replay
    assert [batch.logical_job_ids for batch in first] == [
        ("scene-job-0", "scene-job-1", "scene-job-2"),
        ("scene-job-3", "scene-job-4", "scene-job-5"),
        ("scene-job-6",),
    ]
    assert tuple(job for batch in first for job in batch.items) == jobs
    assert all(len(batch.items) <= limits.maximum_items for batch in first)
    assert all(batch.input_chars <= limits.maximum_input_chars for batch in first)
    assert all(
        batch.estimated_input_tokens <= limits.maximum_input_tokens for batch in first
    )


def test_pack_rejects_duplicate_or_individually_oversized_logical_job() -> None:
    limits = BatchLimits(2, 100, 100)
    duplicate = _job(0)

    with pytest.raises(ValueError, match="must be unique"):
        pack_scene_jobs((duplicate, duplicate), limits)
    with pytest.raises(ValueError, match="exceeds an individual transport limit"):
        pack_scene_jobs((_job(1, chars=101),), limits)


def test_batch_items_validate_commit_and_retry_independently() -> None:
    (batch,) = pack_scene_jobs(
        tuple(_job(index) for index in range(4)),
        BatchLimits(8, 10_000, 10_000),
    )
    payload = {
        "items": [
            {
                "logical_job_id": "scene-job-0",
                "output": _mapping_output("scene-job-0", "valid"),
            },
            {
                "logical_job_id": "scene-job-1",
                "output": _mapping_output("another-job", "cross-owned"),
            },
            {
                "logical_job_id": "scene-job-2",
                "output": _mapping_output("scene-job-2", "first"),
            },
            {
                "logical_job_id": "scene-job-2",
                "output": _mapping_output("scene-job-2", "duplicate"),
            },
            {
                "logical_job_id": "foreign-job",
                "output": _mapping_output("foreign-job", "foreign"),
            },
            {"wrong": "shape"},
        ]
    }

    result = evaluate_batch_output(batch, payload, _validate_owned_output)

    assert [outcome.status for outcome in result.known_outcomes] == [
        BatchItemStatus.VALID,
        BatchItemStatus.MALFORMED,
        BatchItemStatus.DUPLICATE,
        BatchItemStatus.MISSING,
    ]
    assert [outcome.logical_job_id for outcome in result.committable] == ["scene-job-0"]
    assert result.retry_logical_job_ids == (
        "scene-job-1",
        "scene-job-2",
        "scene-job-3",
    )
    assert [outcome.status for outcome in result.foreign_outcomes] == [
        BatchItemStatus.FOREIGN
    ]
    assert [outcome.status for outcome in result.envelope_findings] == [
        BatchItemStatus.MALFORMED
    ]
    assert result.whole_batch_unusable is False


def test_one_validator_exception_does_not_discard_a_valid_sibling() -> None:
    (batch,) = pack_scene_jobs((_job(0), _job(1)), BatchLimits(8, 10_000, 10_000))

    def validate(logical_job_id: str, output: object) -> object:
        if logical_job_id == "scene-job-1":
            raise RuntimeError("item-local validator failure")
        return _validate_owned_output(logical_job_id, output)

    result = evaluate_batch_output(
        batch,
        {
            "items": [
                {
                    "logical_job_id": logical_job_id,
                    "output": _mapping_output(logical_job_id, "value"),
                }
                for logical_job_id in batch.logical_job_ids
            ]
        },
        validate,
    )

    assert [outcome.logical_job_id for outcome in result.committable] == ["scene-job-0"]
    assert result.retry_logical_job_ids == ("scene-job-1",)


@pytest.mark.parametrize(
    "payload",
    (
        None,
        {},
        {"items": "not-an-array"},
        {"items": [], "extra": True},
        {"items": [{"logical_job_id": "foreign", "output": {}}]},
        {"items": [{"bad": "shape"}]},
    ),
)
def test_wholly_unusable_batch_retries_all_known_jobs_and_can_split(payload: object) -> None:
    (batch,) = pack_scene_jobs(
        tuple(_job(index) for index in range(5)),
        BatchLimits(8, 10_000, 10_000),
    )

    result = evaluate_batch_output(batch, payload, _validate_owned_output)
    split = split_unusable_batch(batch, result)

    assert result.whole_batch_unusable is True
    assert result.retry_logical_job_ids == batch.logical_job_ids
    assert [part.logical_job_ids for part in split] == [
        ("scene-job-0", "scene-job-1"),
        ("scene-job-2", "scene-job-3", "scene-job-4"),
    ]
    assert tuple(job for part in split for job in part.items) == batch.items
    assert all(part.batch_id != batch.batch_id for part in split)


def test_repeated_unusable_splits_are_deterministic_individual_retries() -> None:
    (batch,) = pack_scene_jobs(
        tuple(_job(index) for index in range(6)),
        BatchLimits(8, 10_000, 10_000),
    )

    first = recursive_singleton_batches(batch)
    replay = recursive_singleton_batches(batch)

    assert first == replay
    assert [leaf.logical_job_ids for leaf in first] == [
        ("scene-job-0",),
        ("scene-job-1",),
        ("scene-job-2",),
        ("scene-job-3",),
        ("scene-job-4",),
        ("scene-job-5",),
    ]
    assert all(leaf.items[0] in batch.items for leaf in first)
    assert split_transport_batch(first[0]) == ()


def test_a_usable_batch_cannot_be_split_as_if_the_whole_transport_failed() -> None:
    (batch,) = pack_scene_jobs((_job(0), _job(1)), BatchLimits(8, 10_000, 10_000))
    result = evaluate_batch_output(
        batch,
        {
            "items": [
                {
                    "logical_job_id": "scene-job-0",
                    "output": _mapping_output("scene-job-0", "valid"),
                }
            ]
        },
        _validate_owned_output,
    )

    with pytest.raises(ValueError, match="wholly unusable"):
        split_unusable_batch(batch, result)
