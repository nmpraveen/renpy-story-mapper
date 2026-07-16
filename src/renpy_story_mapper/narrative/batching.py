"""Deterministic transport batching for independent M13 scene jobs.

Transport batches are an optimization only.  Logical job identity, input
revision, validation, retry, and publication remain item-local.  This module
therefore never combines job payloads into a shared narrative object and never
interprets one item's output as support for another item.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

TRANSPORT_BATCH_VERSION = "m13-transport-batch-v1"


def _require_identifier(value: str, *, name: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty, trimmed string.")


@dataclass(frozen=True)
class BatchableSceneJob:
    """The provider-neutral transport facts needed to pack one logical job."""

    logical_job_id: str
    input_revision: str
    ordinal: int
    input_chars: int
    estimated_input_tokens: int

    def __post_init__(self) -> None:
        _require_identifier(self.logical_job_id, name="logical_job_id")
        _require_identifier(self.input_revision, name="input_revision")
        if self.ordinal < 0:
            raise ValueError("ordinal must be non-negative.")
        if self.input_chars <= 0:
            raise ValueError("input_chars must be positive.")
        if self.estimated_input_tokens <= 0:
            raise ValueError("estimated_input_tokens must be positive.")


@dataclass(frozen=True)
class BatchLimits:
    """Hard transport ceilings; every emitted batch satisfies all three."""

    maximum_items: int
    maximum_input_chars: int
    maximum_input_tokens: int

    def __post_init__(self) -> None:
        if self.maximum_items <= 0:
            raise ValueError("maximum_items must be positive.")
        if self.maximum_input_chars <= 0:
            raise ValueError("maximum_input_chars must be positive.")
        if self.maximum_input_tokens <= 0:
            raise ValueError("maximum_input_tokens must be positive.")


@dataclass(frozen=True)
class TransportBatch:
    """One operational provider request containing independent logical items."""

    batch_id: str
    ordinal: int
    items: tuple[BatchableSceneJob, ...]
    split_path: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.batch_id, name="batch_id")
        if self.ordinal < 0:
            raise ValueError("ordinal must be non-negative.")
        if not self.items:
            raise ValueError("A transport batch must contain at least one logical job.")
        if any(part not in (0, 1) for part in self.split_path):
            raise ValueError("split_path may contain only deterministic binary branches 0 or 1.")
        identifiers = [item.logical_job_id for item in self.items]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("A transport batch cannot repeat a logical job.")

    @property
    def logical_job_ids(self) -> tuple[str, ...]:
        return tuple(item.logical_job_id for item in self.items)

    @property
    def input_chars(self) -> int:
        return sum(item.input_chars for item in self.items)

    @property
    def estimated_input_tokens(self) -> int:
        return sum(item.estimated_input_tokens for item in self.items)


class BatchItemStatus(StrEnum):
    """Publication disposition for exactly one returned transport item."""

    VALID = "valid"
    MALFORMED = "malformed"
    MISSING = "missing"
    DUPLICATE = "duplicate"
    FOREIGN = "foreign"


@dataclass(frozen=True)
class BatchItemOutcome:
    """A sanitized item-level finding; raw provider payloads are not retained."""

    logical_job_id: str | None
    status: BatchItemStatus
    source_indexes: tuple[int, ...]
    output: object | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class BatchEvaluation:
    """Independent validation outcomes for one provider transport response."""

    batch_id: str
    known_outcomes: tuple[BatchItemOutcome, ...]
    foreign_outcomes: tuple[BatchItemOutcome, ...] = ()
    envelope_findings: tuple[BatchItemOutcome, ...] = ()
    whole_batch_unusable: bool = False

    @property
    def committable(self) -> tuple[BatchItemOutcome, ...]:
        """Valid items may be committed even when siblings need retry."""

        return tuple(
            outcome
            for outcome in self.known_outcomes
            if outcome.status is BatchItemStatus.VALID
        )

    @property
    def retry_logical_job_ids(self) -> tuple[str, ...]:
        """Return only known failed jobs, in original logical batch order."""

        return tuple(
            outcome.logical_job_id
            for outcome in self.known_outcomes
            if outcome.logical_job_id is not None
            and outcome.status is not BatchItemStatus.VALID
        )

    @property
    def findings(self) -> tuple[BatchItemOutcome, ...]:
        return self.known_outcomes + self.foreign_outcomes + self.envelope_findings


OutputValidator = Callable[[str, object], object]


def pack_scene_jobs(
    jobs: Sequence[BatchableSceneJob],
    limits: BatchLimits,
) -> tuple[TransportBatch, ...]:
    """Greedily pack deterministic job order without changing logical identity.

    The caller may supply jobs in any order.  Stable ordinal and logical ID form
    the transport order, so replay produces the same batches and batch IDs.
    """

    ordered = tuple(sorted(jobs, key=lambda item: (item.ordinal, item.logical_job_id)))
    _validate_unique_jobs(ordered)
    for job in ordered:
        if (
            job.input_chars > limits.maximum_input_chars
            or job.estimated_input_tokens > limits.maximum_input_tokens
        ):
            raise ValueError(
                f"Logical job {job.logical_job_id!r} exceeds an individual transport limit."
            )
    groups: list[tuple[BatchableSceneJob, ...]] = []
    pending: list[BatchableSceneJob] = []
    pending_chars = 0
    pending_tokens = 0
    for job in ordered:
        would_overflow = bool(pending) and (
            len(pending) + 1 > limits.maximum_items
            or pending_chars + job.input_chars > limits.maximum_input_chars
            or pending_tokens + job.estimated_input_tokens > limits.maximum_input_tokens
        )
        if would_overflow:
            groups.append(tuple(pending))
            pending = []
            pending_chars = 0
            pending_tokens = 0
        pending.append(job)
        pending_chars += job.input_chars
        pending_tokens += job.estimated_input_tokens
    if pending:
        groups.append(tuple(pending))
    return tuple(
        _make_batch(items, ordinal=ordinal, split_path=())
        for ordinal, items in enumerate(groups)
    )


def evaluate_batch_output(
    batch: TransportBatch,
    payload: object,
    validate_output: OutputValidator,
) -> BatchEvaluation:
    """Validate ownership and content independently for every logical item.

    The accepted envelope is exactly ``{"items": [...]}``; each array entry is
    exactly ``{"logical_job_id": ..., "output": ...}``.  Strict shape keeps
    ambiguous or cross-owned output from being published.  The validator is
    called only for a single, known job ID and receives that expected owner.
    """

    known_ids = batch.logical_job_ids
    if not isinstance(payload, Mapping) or set(payload) != {"items"}:
        return _unusable_evaluation(batch, "invalid_batch_envelope")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return _unusable_evaluation(batch, "invalid_batch_items")

    indexed_known: dict[str, list[tuple[int, object]]] = {
        logical_job_id: [] for logical_job_id in known_ids
    }
    foreign: list[BatchItemOutcome] = []
    malformed: list[BatchItemOutcome] = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, Mapping) or set(raw_item) != {
            "logical_job_id",
            "output",
        }:
            malformed.append(
                BatchItemOutcome(
                    logical_job_id=None,
                    status=BatchItemStatus.MALFORMED,
                    source_indexes=(index,),
                    error_code="malformed_batch_item",
                )
            )
            continue
        raw_id = raw_item.get("logical_job_id")
        if not isinstance(raw_id, str) or not raw_id or raw_id != raw_id.strip():
            malformed.append(
                BatchItemOutcome(
                    logical_job_id=None,
                    status=BatchItemStatus.MALFORMED,
                    source_indexes=(index,),
                    error_code="invalid_logical_job_id",
                )
            )
            continue
        if raw_id not in indexed_known:
            foreign.append(
                BatchItemOutcome(
                    logical_job_id=raw_id,
                    status=BatchItemStatus.FOREIGN,
                    source_indexes=(index,),
                    error_code="foreign_logical_job_id",
                )
            )
            continue
        indexed_known[raw_id].append((index, raw_item.get("output")))

    outcomes: list[BatchItemOutcome] = []
    for logical_job_id in known_ids:
        candidates = indexed_known[logical_job_id]
        if not candidates:
            outcomes.append(
                BatchItemOutcome(
                    logical_job_id=logical_job_id,
                    status=BatchItemStatus.MISSING,
                    source_indexes=(),
                    error_code="missing_logical_job_output",
                )
            )
            continue
        if len(candidates) > 1:
            outcomes.append(
                BatchItemOutcome(
                    logical_job_id=logical_job_id,
                    status=BatchItemStatus.DUPLICATE,
                    source_indexes=tuple(index for index, _output in candidates),
                    error_code="duplicate_logical_job_output",
                )
            )
            continue
        index, raw_output = candidates[0]
        try:
            normalized = validate_output(logical_job_id, raw_output)
        except Exception:
            # Provider-item validation is an isolation boundary.  Any ordinary
            # validator failure is sanitized and remains local to this item;
            # process-control exceptions still propagate because they do not
            # inherit from Exception.
            outcomes.append(
                BatchItemOutcome(
                    logical_job_id=logical_job_id,
                    status=BatchItemStatus.MALFORMED,
                    source_indexes=(index,),
                    error_code="invalid_logical_job_output",
                )
            )
        else:
            outcomes.append(
                BatchItemOutcome(
                    logical_job_id=logical_job_id,
                    status=BatchItemStatus.VALID,
                    source_indexes=(index,),
                    output=normalized,
                )
            )

    # A structurally valid response with no item attributable to this batch is
    # unusable as a whole.  Known but malformed/duplicate items remain local
    # failures and can be retried without discarding valid siblings.
    whole_batch_unusable = not any(indexed_known.values())
    return BatchEvaluation(
        batch_id=batch.batch_id,
        known_outcomes=tuple(outcomes),
        foreign_outcomes=tuple(foreign),
        envelope_findings=tuple(malformed),
        whole_batch_unusable=whole_batch_unusable,
    )


def split_unusable_batch(
    batch: TransportBatch,
    evaluation: BatchEvaluation,
) -> tuple[TransportBatch, ...]:
    """Split one wholly unusable request in deterministic binary order."""

    if evaluation.batch_id != batch.batch_id:
        raise ValueError("The evaluation does not belong to this transport batch.")
    if not evaluation.whole_batch_unusable:
        raise ValueError("Only a wholly unusable transport batch may be split.")
    return split_transport_batch(batch)


def split_transport_batch(batch: TransportBatch) -> tuple[TransportBatch, ...]:
    """Return one deterministic split level; a singleton cannot split further."""

    if len(batch.items) <= 1:
        return ()
    midpoint = len(batch.items) // 2
    parts = (batch.items[:midpoint], batch.items[midpoint:])
    return tuple(
        _make_batch(
            items,
            ordinal=batch.ordinal,
            split_path=(*batch.split_path, branch),
        )
        for branch, items in enumerate(parts)
    )


def recursive_singleton_batches(batch: TransportBatch) -> tuple[TransportBatch, ...]:
    """Return deterministic individual fallbacks for repeated whole-batch failure."""

    pending = [batch]
    leaves: list[TransportBatch] = []
    while pending:
        candidate = pending.pop(0)
        split = split_transport_batch(candidate)
        if not split:
            leaves.append(candidate)
        else:
            pending[0:0] = list(split)
    return tuple(leaves)


def _validate_unique_jobs(jobs: Sequence[BatchableSceneJob]) -> None:
    counts = Counter(job.logical_job_id for job in jobs)
    duplicates = sorted(logical_job_id for logical_job_id, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"Logical scene job IDs must be unique: {duplicates!r}.")


def _make_batch(
    items: tuple[BatchableSceneJob, ...],
    *,
    ordinal: int,
    split_path: tuple[int, ...],
) -> TransportBatch:
    material = {
        "transport_version": TRANSPORT_BATCH_VERSION,
        "ordinal": ordinal,
        "split_path": split_path,
        "logical_items": [
            {
                "logical_job_id": item.logical_job_id,
                "input_revision": item.input_revision,
            }
            for item in items
        ],
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return TransportBatch(
        batch_id=f"m13-batch-{hashlib.sha256(encoded).hexdigest()}",
        ordinal=ordinal,
        items=items,
        split_path=split_path,
    )


def _unusable_evaluation(batch: TransportBatch, error_code: str) -> BatchEvaluation:
    return BatchEvaluation(
        batch_id=batch.batch_id,
        known_outcomes=tuple(
            BatchItemOutcome(
                logical_job_id=logical_job_id,
                status=BatchItemStatus.MISSING,
                source_indexes=(),
                error_code="missing_logical_job_output",
            )
            for logical_job_id in batch.logical_job_ids
        ),
        envelope_findings=(
            BatchItemOutcome(
                logical_job_id=None,
                status=BatchItemStatus.MALFORMED,
                source_indexes=(),
                error_code=error_code,
            ),
        ),
        whole_batch_unusable=True,
    )
