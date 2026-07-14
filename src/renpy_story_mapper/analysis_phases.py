"""Generation-bound persistence state for the deterministic M10 pipeline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from renpy_story_mapper import storage
from renpy_story_mapper.project import PayloadRecord

ANALYSIS_STATE_SCHEMA_VERSION = 2


class AnalysisStatus(StrEnum):
    STALE = "stale"
    CURRENT_PARTIAL = "current_partial"
    CURRENT_COMPLETE = "current_complete"
    FAILED = "failed"


class CanonicalAvailability(StrEnum):
    NONE = "none"
    STALE = "stale"
    CURRENT_COMPLETE = "current_complete"


class SimplifiedAvailability(StrEnum):
    NONE = "none"
    STALE = "stale"
    CURRENT_COMPLETE = "current_complete"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PhaseBinding:
    phase: str
    source_generation: str
    payloads: tuple[Mapping[str, str], ...]
    duration_seconds: float

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "source_generation": self.source_generation,
            "payloads": [dict(item) for item in self.payloads],
            "duration_seconds": self.duration_seconds,
        }


def payload_bindings(records: Sequence[PayloadRecord]) -> tuple[Mapping[str, str], ...]:
    return tuple(
        {
            "collection": item.collection,
            "key": item.key,
            "payload_hash": storage.payload_digest(storage.canonical_json(item.value)),
        }
        for item in sorted(records, key=lambda item: (item.collection, item.key))
    )


def analysis_state_payload(
    *,
    source_generation: str,
    status: AnalysisStatus,
    phases: Sequence[PhaseBinding],
    canonical_generation: str | None,
    canonical_hash: str | None,
    simplified_generation: str | None = None,
    simplified_canonical_hash: str | None = None,
    failure_phase: str | None = None,
    failure_code: str | None = None,
    failure_duration_seconds: float | None = None,
) -> dict[str, object]:
    if (canonical_generation is None) != (canonical_hash is None):
        raise ValueError("canonical generation and hash must be present together")
    if canonical_generation is None:
        availability = CanonicalAvailability.NONE
    elif canonical_generation == source_generation:
        availability = CanonicalAvailability.CURRENT_COMPLETE
    else:
        availability = CanonicalAvailability.STALE
    if (simplified_generation is None) != (simplified_canonical_hash is None):
        raise ValueError("simplified generation and canonical hash must be present together")
    if simplified_generation is None:
        simplified_availability = SimplifiedAvailability.NONE
    elif (
        simplified_generation != canonical_generation
        or simplified_canonical_hash != canonical_hash
    ):
        simplified_availability = SimplifiedAvailability.UNAVAILABLE
    elif simplified_generation == source_generation:
        simplified_availability = SimplifiedAvailability.CURRENT_COMPLETE
    else:
        simplified_availability = SimplifiedAvailability.STALE
    value: dict[str, object] = {
        "schema_version": ANALYSIS_STATE_SCHEMA_VERSION,
        "source_generation": source_generation,
        "status": status.value,
        "canonical_availability": availability.value,
        "simplified_availability": simplified_availability.value,
        "phases": [item.to_dict() for item in phases],
    }
    if canonical_generation is not None and canonical_hash is not None:
        value["canonical_generation"] = canonical_generation
        value["canonical_hash"] = canonical_hash
    if simplified_generation is not None and simplified_canonical_hash is not None:
        value["simplified_generation"] = simplified_generation
        value["simplified_canonical_hash"] = simplified_canonical_hash
    if failure_phase is not None:
        value["failure"] = {
            "phase": failure_phase,
            "code": failure_code or "analysis_phase_failed",
            "duration_seconds": max(0.0, failure_duration_seconds or 0.0),
            "message": "The phase failed safely; available deterministic results were preserved.",
        }
    return value
