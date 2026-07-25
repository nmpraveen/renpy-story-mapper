"""Versioned provider-neutral contracts for Story Map V2 Phase 02."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum

STORY_MAP_V2_SCHEMA_VERSION = 1
STORY_MAP_V2_SCHEMA = f"story-map-v2-core-v{STORY_MAP_V2_SCHEMA_VERSION}"
MAPPER_SCHEMA_VERSION = "story-map-v2-mapper-v2"
PREVIEW_SCHEMA_VERSION = "story-map-v2-preview-v1"

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def canonical_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _text(value: str, label: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty trimmed string")


class Reachability(StrEnum):
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    UNRESOLVED = "unresolved"


class ChunkStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    CANCELLED = "cancelled"


class ProviderOrigin(StrEnum):
    CLOUD = "cloud"
    LOCAL_FALLBACK = "local_fallback"
    LOCAL_ONLY = "local_only"
    MISSING = "missing"


class ExecutionMode(StrEnum):
    CLOUD_PRIMARY = "cloud_primary"
    LOCAL_ONLY = "local_only"


class FailureKind(StrEnum):
    CONTENT_REFUSAL = "content_refusal"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    AUTHENTICATION = "authentication"
    TRANSPORT = "transport"
    INVALID_RESPONSE = "invalid_response"
    IDENTITY = "identity"
    CANCELLED = "cancelled"
    LOCAL_UNAVAILABLE = "local_unavailable"


@dataclass(frozen=True, order=True)
class ArmLineageStep:
    choice_key: str
    arm_order: int

    def __post_init__(self) -> None:
        _text(self.choice_key, "choice key")
        if self.arm_order < 1:
            raise ValueError("arm order must be positive")


@dataclass(frozen=True)
class SourceSpan:
    key: str
    relative_path: str
    start_line: int
    end_line: int
    raw_text: str
    estimated_tokens: int
    canonical_node_ids: tuple[str, ...]
    reachability: Reachability
    unresolved_warnings: tuple[str, ...] = ()
    choice_keys: tuple[str, ...] = ()
    arm_lineage: tuple[ArmLineageStep, ...] = ()
    natural_boundary_after: bool = False
    shared_continuation: bool = False

    def __post_init__(self) -> None:
        _text(self.key, "span key")
        _text(self.relative_path, "relative path")
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError("source span lines are invalid")
        if self.estimated_tokens < 0:
            raise ValueError("estimated tokens cannot be negative")
        if len(self.canonical_node_ids) != len(set(self.canonical_node_ids)):
            raise ValueError("canonical node IDs must be unique")
        for warning in self.unresolved_warnings:
            _text(warning, "unresolved warning")


@dataclass(frozen=True)
class ArmMechanic:
    order: int
    caption: str
    start_line: int
    end_line: int
    condition: str | None
    effects: tuple[str, ...]
    destination_id: str | None
    rejoin_node_id: str | None
    rejoin_line: int | None
    reachability: Reachability
    unresolved_warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.order < 1:
            raise ValueError("arm order must be positive")
        _text(self.caption, "arm caption")
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError("arm source lines are invalid")


@dataclass(frozen=True)
class ChoiceMechanic:
    key: str
    relative_path: str
    line: int
    arms: tuple[ArmMechanic, ...]
    parent_lineage: tuple[ArmLineageStep, ...] = ()
    story_choice: bool = True

    def __post_init__(self) -> None:
        _text(self.key, "choice key")
        _text(self.relative_path, "choice path")
        if self.line < 1 or not self.arms:
            raise ValueError("choices require a physical line and at least one arm")
        if tuple(arm.order for arm in self.arms) != tuple(range(1, len(self.arms) + 1)):
            raise ValueError("choice arm order must be contiguous and authoritative")


@dataclass(frozen=True)
class DensityMetrics:
    menus: int = 0
    arms: int = 0
    conditions: int = 0
    transfers: int = 0
    unresolved: int = 0

    def __post_init__(self) -> None:
        if min(asdict(self).values(), default=0) < 0:
            raise ValueError("density counts cannot be negative")

    @property
    def branch_weight(self) -> int:
        return self.menus * 4 + self.arms * 2 + self.conditions + self.transfers + self.unresolved


@dataclass(frozen=True)
class StoryScope:
    source_identity: str
    source_generation: str
    canonical_hash: str
    spans: tuple[SourceSpan, ...]
    choices: tuple[ChoiceMechanic, ...] = ()

    def __post_init__(self) -> None:
        for value, label in (
            (self.source_identity, "source identity"),
            (self.source_generation, "source generation"),
            (self.canonical_hash, "canonical hash"),
        ):
            _text(value, label)
        if len({span.key for span in self.spans}) != len(self.spans):
            raise ValueError("scope span keys must be unique")
        if len({choice.key for choice in self.choices}) != len(self.choices):
            raise ValueError("scope choice keys must be unique")


@dataclass(frozen=True)
class ChunkProfile:
    target_tokens: int = 8_000
    branch_target_tokens: int = 5_000
    maximum_tokens: int = 10_700
    branch_weight_threshold: int = 12

    def __post_init__(self) -> None:
        if not (
            0 < self.branch_target_tokens <= self.target_tokens <= self.maximum_tokens
            and self.branch_weight_threshold > 0
        ):
            raise ValueError("chunk profile limits are invalid")


@dataclass(frozen=True)
class StoryChunk:
    index: int
    span_keys: tuple[str, ...]
    choice_keys: tuple[str, ...]
    raw_text: str
    mechanics: str
    raw_tokens: int
    density: DensityMetrics
    packet_hash: str

    def __post_init__(self) -> None:
        if self.index < 1 or not self.span_keys or self.raw_tokens < 0:
            raise ValueError("chunk identity, spans, and tokens are required")
        _text(self.mechanics, "chunk mechanics")
        try:
            decoded_mechanics = json.loads(self.mechanics)
        except json.JSONDecodeError as exc:
            raise ValueError("chunk mechanics must be canonical JSON") from exc
        if (
            not isinstance(decoded_mechanics, dict)
            or canonical_json(decoded_mechanics).decode() != self.mechanics
        ):
            raise ValueError("chunk mechanics must be one canonical JSON object")
        _text(self.packet_hash, "packet hash")

    @property
    def identity(self) -> str:
        return canonical_hash(
            {
                "index": self.index,
                "span_keys": self.span_keys,
                "choice_keys": self.choice_keys,
                "packet_hash": self.packet_hash,
            }
        )

    @property
    def payload_hash(self) -> str:
        """Bind provider-facing story content independently of its declared packet hash."""

        return canonical_hash(
            {
                "raw_text": self.raw_text,
                "mechanics": json.loads(self.mechanics),
            }
        )


@dataclass(frozen=True)
class MapperEvent:
    title: str
    summary: str
    relative_path: str
    start_line: int
    end_line: int
    characters: tuple[str, ...] = ()
    warning: str | None = None


@dataclass(frozen=True)
class BranchSummary:
    choice_key: str
    arm_order: int
    outcome_summary: str


@dataclass(frozen=True)
class MapperResponse:
    scope_title: str | None
    scope_overview: str | None
    events: tuple[MapperEvent, ...]
    branch_summaries: tuple[BranchSummary, ...]


@dataclass(frozen=True)
class EventAnchor:
    id: str
    canonical_node_id: str
    relative_path: str
    line: int
    arm_lineage: tuple[ArmLineageStep, ...]
    destination_id: str | None


@dataclass(frozen=True)
class CoreEvent:
    title: str
    summary: str
    relative_path: str
    start_line: int
    end_line: int
    characters: tuple[str, ...]
    warnings: tuple[str, ...]
    anchor: EventAnchor
    reachability: Reachability


@dataclass(frozen=True)
class CoreBranchOutcome:
    choice_key: str
    arm_order: int
    caption: str
    summary: str
    anchor: EventAnchor
    reachability: Reachability
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.choice_key, "choice key")
        if self.arm_order < 1:
            raise ValueError("arm order must be positive")
        _text(self.caption, "branch caption")
        _text(self.summary, "branch summary")
        for warning in self.warnings:
            _text(warning, "branch warning")


@dataclass(frozen=True)
class CoreChunk:
    chunk_identity: str
    status: ChunkStatus
    origin: ProviderOrigin
    events: tuple[CoreEvent, ...]
    choices: tuple[ChoiceMechanic, ...]
    branch_outcomes: tuple[CoreBranchOutcome, ...] = ()
    scope_title: str | None = None
    scope_overview: str | None = None
    execution: ChunkExecutionResult | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.chunk_identity, "chunk identity")
        for value, label in (
            (self.scope_title, "scope title"),
            (self.scope_overview, "scope overview"),
        ):
            if value is not None:
                _text(value, label)


@dataclass(frozen=True)
class StoryMapCore:
    schema: str
    source_identity: str
    status: ChunkStatus
    chunks: tuple[CoreChunk, ...]
    title: str | None = None
    overview: str | None = None

    def __post_init__(self) -> None:
        _text(self.schema, "core schema")
        _text(self.source_identity, "source identity")
        for value, label in ((self.title, "core title"), (self.overview, "core overview")):
            if value is not None:
                _text(value, label)


@dataclass(frozen=True)
class ProviderSettings:
    model: str = "gpt-5.6-luna"
    reasoning: str = "high"
    fast_mode: bool = False


@dataclass(frozen=True)
class RunPreview:
    schema: str
    source_identity: str
    chunk_identities: tuple[str, ...]
    packet_hashes: tuple[str, ...]
    payload_hashes: tuple[str, ...]
    transmitted_fields: tuple[str, ...]
    prompt_version: str
    mapper_schema: str
    mode: ExecutionMode
    cloud_settings: ProviderSettings | None
    allow_local_fallback: bool
    local_model: str | None
    local_endpoint: str | None
    maximum_hosted_planned: int
    maximum_hosted_absolute: int
    maximum_local: int
    privacy_exclusions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not (
            len(self.chunk_identities)
            == len(self.packet_hashes)
            == len(self.payload_hashes)
        ):
            raise ValueError(
                "preview chunk identities, packet hashes, and payload hashes must align"
            )
        if (self.local_model is None) != (self.local_endpoint is None):
            raise ValueError("local model and endpoint must be bound together")
        if self.local_model is not None:
            _text(self.local_model, "local model")
        if self.local_endpoint is not None:
            _text(self.local_endpoint, "local endpoint")

    @property
    def confirmation_hash(self) -> str:
        return canonical_hash(asdict(self))


@dataclass(frozen=True)
class ChunkExecutionResult:
    chunk_identity: str
    origin: ProviderOrigin
    status: ChunkStatus
    response: MapperResponse | None
    failure_kind: FailureKind | None
    elapsed_ms: int
    response_hash: str | None
    sanitized_reason: str | None
    input_tokens: int | None = None
    output_tokens: int | None = None
    requested_model: str | None = None
    resolved_model: str | None = None
    reasoning: str | None = None
    fast_mode: bool | None = None

    def __post_init__(self) -> None:
        _text(self.chunk_identity, "chunk identity")
        if self.elapsed_ms < 0:
            raise ValueError("elapsed milliseconds cannot be negative")
        for value, label in (
            (self.requested_model, "requested model"),
            (self.resolved_model, "resolved model"),
            (self.reasoning, "reasoning"),
        ):
            if value is not None:
                _text(value, label)
        for token_count in (self.input_tokens, self.output_tokens):
            if token_count is not None and (
                isinstance(token_count, bool) or token_count < 0
            ):
                raise ValueError("token accounting cannot be negative")
