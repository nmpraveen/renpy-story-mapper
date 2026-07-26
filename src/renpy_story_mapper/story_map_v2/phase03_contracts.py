"""Small versioned contracts for Story Map V2 Phase 03.

These records deliberately separate optional prose synthesis from Python-owned
story mechanics, navigation bindings, and project authority.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Final

from renpy_story_mapper.story_map_v2.contracts import (
    Reachability,
    StoryMapCore,
    canonical_hash,
)

PROJECT_SCHEMA: Final = "story-map-v2-project-v1"
SYNTHESIS_REQUEST_SCHEMA: Final = "story-map-v2-synthesis-request-v1"
SYNTHESIS_RESPONSE_SCHEMA: Final = "story-map-v2-synthesis-response-v1"
SYNTHESIS_RECORD_SCHEMA: Final = "story-map-v2-synthesis-record-v1"
SYNTHESIS_PREVIEW_SCHEMA: Final = "story-map-v2-synthesis-preview-v1"
STORY_PAGE_SCHEMA: Final = "story-map-v2-page-v1"
SYNTHESIS_PROMPT_VERSION: Final = "story-map-v2-synthesis-prompt-v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _text(value: str, label: str, *, maximum: int = 2_000) -> None:
    if not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be a non-empty trimmed bounded string")


def _digest(value: str, label: str) -> None:
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


@dataclass(frozen=True)
class StoryMapProjectIdentity:
    schema: str
    core_schema: str
    core_hash: str
    source_identity: str
    source_generation: str
    authority_hash: str
    source_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema != PROJECT_SCHEMA:
            raise ValueError("unsupported Story Map V2 project schema")
        _text(self.core_schema, "core schema", maximum=80)
        _text(self.source_identity, "source identity", maximum=512)
        _digest(self.core_hash, "core hash")
        _digest(self.source_generation, "source generation")
        _digest(self.authority_hash, "authority hash")
        if not self.source_paths or tuple(sorted(set(self.source_paths))) != self.source_paths:
            raise ValueError("source paths must be a non-empty sorted unique tuple")
        for path in self.source_paths:
            _text(path, "source path", maximum=1_024)

    @property
    def identity_hash(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True)
class SynthesisEventInput:
    anchor_id: str
    title: str
    summary: str
    characters: tuple[str, ...]
    source_order: int


@dataclass(frozen=True)
class SynthesisOutcomeInput:
    anchor_id: str
    summary: str


@dataclass(frozen=True)
class SynthesisArmInput:
    order: int
    caption: str
    condition: str | None
    effects: tuple[str, ...]
    destination: str | None
    rejoin: str | None


@dataclass(frozen=True)
class SynthesisChoiceInput:
    key: str
    arms: tuple[SynthesisArmInput, ...]
    parent_lineage: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class SynthesisRequest:
    schema: str
    prompt_version: str
    project_identity_hash: str
    events: tuple[SynthesisEventInput, ...]
    branch_outcomes: tuple[SynthesisOutcomeInput, ...]
    choices: tuple[SynthesisChoiceInput, ...]
    instructions: tuple[str, ...]
    transmitted_fields: tuple[str, ...]


@dataclass(frozen=True)
class SynthesisSection:
    section_title: str
    section_summary: str
    event_anchor_ids: tuple[str, ...]


@dataclass(frozen=True)
class SynthesisThread:
    title: str
    summary: str
    event_anchor_ids: tuple[str, ...]


@dataclass(frozen=True)
class SynthesisResponse:
    story_title: str
    story_overview: str
    ordered_sections: tuple[SynthesisSection, ...]
    optional_threads: tuple[SynthesisThread, ...]


@dataclass(frozen=True)
class ValidatedSynthesis:
    story_title: str
    story_overview: str
    ordered_sections: tuple[SynthesisSection, ...]
    optional_threads: tuple[SynthesisThread, ...]
    analysis_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SynthesisProviderSettings:
    model: str = "gpt-5.6-terra"
    reasoning: str = "high"
    fast_mode: bool = False


@dataclass(frozen=True)
class SynthesisPreview:
    schema: str
    project_identity_hash: str
    request_payload_hash: str
    prompt_version: str
    response_schema: str
    transmitted_fields: tuple[str, ...]
    settings: SynthesisProviderSettings
    maximum_calls: int
    privacy_exclusions: tuple[str, ...]

    @property
    def confirmation_hash(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True)
class SynthesisProviderReply:
    payload: bytes | str
    provider: str
    requested_model: str
    resolved_model: str
    reasoning: str
    fast_mode: bool
    input_tokens: int | None
    output_tokens: int | None
    elapsed_ms: int


class SynthesisStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SynthesisFailureKind(StrEnum):
    REFUSED = "refused"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    INVALID_RESPONSE = "invalid_response"
    IDENTITY = "identity"


@dataclass(frozen=True)
class SynthesisExecutionResult:
    schema: str
    project_identity_hash: str
    request_payload_hash: str
    preview_confirmation_hash: str
    prompt_version: str
    response_schema: str
    status: SynthesisStatus
    synthesis: ValidatedSynthesis | None
    provider: str | None
    requested_model: str
    resolved_model: str | None
    reasoning: str
    fast_mode: bool
    call_count: int
    input_tokens: int | None
    output_tokens: int | None
    elapsed_ms: int
    failure_kind: SynthesisFailureKind | None
    sanitized_reason: str | None


@dataclass(frozen=True)
class StoryMapProjectEnvelope:
    schema: str
    identity: StoryMapProjectIdentity
    core: StoryMapCore
    synthesis: SynthesisExecutionResult | None
    imported_at_utc: str

    def __post_init__(self) -> None:
        if self.schema != PROJECT_SCHEMA:
            raise ValueError("unsupported Story Map V2 project envelope schema")
        _text(self.imported_at_utc, "import timestamp", maximum=80)


@dataclass(frozen=True)
class SourceBinding:
    relative_path: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class NavigationBinding:
    selection_id: str
    destination_kind: str
    target_id: str
    detail_kind: str
    detail_id: str
    source: SourceBinding


@dataclass(frozen=True)
class StoryArmReadModel:
    selection_id: str
    caption: str
    outcome_summary: str
    condition: str | None
    effects: tuple[str, ...]
    destination_id: str | None
    rejoin_node_id: str | None
    rejoin_line: int | None
    reachability: Reachability
    warnings: tuple[str, ...]
    binding: NavigationBinding
    nested_choices: tuple[StoryChoiceReadModel, ...]


@dataclass(frozen=True)
class StoryChoiceReadModel:
    key: str
    source: SourceBinding
    arms: tuple[StoryArmReadModel, ...]


@dataclass(frozen=True)
class StoryEventReadModel:
    selection_id: str
    title: str
    summary: str
    characters: tuple[str, ...]
    reachability: Reachability
    warnings: tuple[str, ...]
    binding: NavigationBinding
    choices: tuple[StoryChoiceReadModel, ...]


@dataclass(frozen=True)
class StorySectionReadModel:
    id: str
    title: str
    summary: str
    events: tuple[StoryEventReadModel, ...]


@dataclass(frozen=True)
class StoryMapReadModel:
    schema: str
    status: str
    reason: str | None
    title: str
    overview: str
    analysis_notes: tuple[str, ...]
    sections: tuple[StorySectionReadModel, ...]
