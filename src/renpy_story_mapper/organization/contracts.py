"""Typed records shared by organization providers, chunking, and validation."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

MAX_PROMPT_CHARS = 48_000


class CodexMode(StrEnum):
    CODEX_CHATGPT = "codex_chatgpt"
    CODEX_LMSTUDIO = "codex_lmstudio"


class OrganizationStage(StrEnum):
    EVENTS = "events"
    RECONCILE = "reconcile"
    ARCS = "arcs"


class ProviderState(StrEnum):
    READY = "ready"
    MISSING = "missing"


@dataclass(frozen=True)
class ProviderStatus:
    state: ProviderState
    executable: str | None
    cli_version: str | None = None
    message: str = ""
    model_identifier: str | None = None
    context_window_tokens: int | None = None


@dataclass(frozen=True)
class FactRecord:
    id: str
    expression: str
    normalized_value: str
    certainty: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class BeatRecord:
    id: str
    scene_id: str
    kind: str
    order: int
    text: str = ""
    speaker: str | None = None
    condition: str | None = None
    relative_path: str = ""
    start_line: int = 0
    end_line: int = 0
    evidence_ids: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()
    outgoing_ids: tuple[str, ...] = ()
    speaker_names: tuple[str, ...] = ()

    @property
    def requires_coverage(self) -> bool:
        return self.kind in {"narrative", "dialogue", "choice", "condition"}

    @property
    def is_context_candidate(self) -> bool:
        return self.kind in {"narrative", "dialogue"}


@dataclass(frozen=True)
class OrganizationConstraints:
    ordered_member_ids: tuple[str, ...]
    required_member_ids: frozenset[str]
    context_member_ids: frozenset[str] = frozenset()
    fact_ids: frozenset[str] = frozenset()
    evidence_ids: frozenset[str] = frozenset()
    character_names: frozenset[str] = frozenset()


@dataclass(frozen=True)
class OrganizationRequest:
    run_id: str
    chunk_id: str
    scope_id: str
    stage: OrganizationStage
    payload: dict[str, object]
    constraints: OrganizationConstraints
    cloud_consent_run_id: str | None = None
    model: str | None = None
    timeout_seconds: float = 120.0


@dataclass(frozen=True)
class InterpretationClaim:
    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class OrganizationGroup:
    id: str
    title: str
    summary: str
    member_ids: tuple[str, ...]
    characters: tuple[str, ...]
    importance: str
    outcomes: tuple[str, ...]
    promoted_fact_ids: tuple[str, ...]
    claims: tuple[InterpretationClaim, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ProviderExecutionMetadata:
    provider_mode: CodexMode
    model_identifier: str | None
    cli_version: str | None
    elapsed_ms: int
    input_hash: str
    output_hash: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    context_window_tokens: int | None = None


@dataclass(frozen=True)
class OrganizationChunkResult:
    stage: OrganizationStage
    groups: tuple[OrganizationGroup, ...]
    ungrouped_ids: tuple[str, ...]
    raw_normalized: dict[str, object] = field(compare=False, repr=False)
    attempts: int = 1
    metadata: ProviderExecutionMetadata | None = None


class ProgressCallback(Protocol):
    def __call__(self, percent: int, status: str) -> None: ...


class CancelledCallback(Protocol):
    def __call__(self) -> bool: ...


class OrganizationProvider(Protocol):
    def status(self) -> ProviderStatus: ...

    def organize(
        self,
        request: OrganizationRequest,
        progress: ProgressCallback,
        cancelled: CancelledCallback,
    ) -> OrganizationChunkResult: ...

    def cancel(self) -> None: ...


ProgressFunction = Callable[[int, str], None]
CancelledFunction = Callable[[], bool]


def serialize_organization_prompt(request: OrganizationRequest, *, repair: bool) -> str:
    """Serialize the exact stdin envelope used by provider and chunk sizing."""
    instruction = (
        "Repair the prior response. Return only JSON matching the schema and supplied IDs."
        if repair
        else "Organize the supplied deterministic records. Return only schema-valid JSON."
    )
    envelope = {
        "instruction": instruction,
        "security": "Do not use tools, web, MCP, commands, or files.",
        "authority": (
            "Return only titles, summaries, existing memberships, characters supported by "
            "the input, outcomes, existing fact IDs, evidence-backed interpretations, "
            "warnings, and ungrouped IDs. Never invent edges, conditions, facts, source "
            "locations, route destinations, or causal authority."
        ),
        "contract": {
            "stage": request.stage.value,
            "allowed_member_ids": list(request.constraints.ordered_member_ids),
            "context_only_ids": sorted(request.constraints.context_member_ids),
            "allowed_fact_ids": sorted(request.constraints.fact_ids),
            "allowed_evidence_ids": sorted(request.constraints.evidence_ids),
            "allowed_characters": sorted(request.constraints.character_names),
        },
        "input": request.payload,
    }
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
