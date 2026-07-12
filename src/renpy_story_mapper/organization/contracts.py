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
        "The prior response was rejected. Produce a new response from scratch as exactly one "
        "raw JSON object that satisfies output_contract. Do not use Markdown or code fences."
        if repair
        else "Organize the supplied deterministic records. Return exactly one raw JSON object "
        "that satisfies output_contract. Do not use Markdown or code fences."
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
        "output_contract": {
            "top_level": {
                "exact_keys": ["stage", "groups", "ungrouped_ids"],
                "stage": request.stage.value,
                "groups": "array of group objects",
                "ungrouped_ids": "array of unique allowed member ID strings",
            },
            "group": {
                "exact_keys": [
                    "id",
                    "title",
                    "summary",
                    "member_ids",
                    "characters",
                    "importance",
                    "outcomes",
                    "promoted_fact_ids",
                    "claims",
                    "warnings",
                ],
                "id": "non-empty string, at most 80 characters",
                "title": "non-empty string, at most 80 characters",
                "summary": "non-empty string, at most 320 characters",
                "member_ids": "non-empty array of unique allowed member ID strings",
                "characters": "array of unique allowed character-name strings",
                "importance": "exactly supporting, major, or turning point",
                "outcomes": "array of strings, each at most 320 characters",
                "promoted_fact_ids": "array of unique allowed fact ID strings",
                "claims": "array of claim objects",
                "warnings": "array of strings, each at most 320 characters",
            },
            "claim": {
                "exact_keys": ["text", "evidence_ids"],
                "text": "non-empty string, at most 320 characters",
                "evidence_ids": "non-empty array of unique allowed evidence ID strings",
            },
            "coverage": (
                "Place every ID in contract.required_member_ids exactly once in "
                "group.member_ids or ungrouped_ids. Never put a context-only ID in either "
                "location."
            ),
            "ordering": (
                "Every group ID must be unique. Preserve contract.allowed_member_ids order "
                "inside each group, keep groups in chronological non-crossing order, and never "
                "repeat a member across groups or ungrouped_ids."
            ),
            "serialization": (
                "Emit the JSON object only, beginning with { and ending with }. Do not emit "
                "analysis, prose, Markdown, or a fenced code block."
            ),
        },
        "contract": {
            "stage": request.stage.value,
            "allowed_member_ids": list(request.constraints.ordered_member_ids),
            "required_member_ids": [
                member_id
                for member_id in request.constraints.ordered_member_ids
                if member_id in request.constraints.required_member_ids
            ],
            "context_only_ids": sorted(request.constraints.context_member_ids),
            "allowed_fact_ids": sorted(request.constraints.fact_ids),
            "allowed_evidence_ids": sorted(request.constraints.evidence_ids),
            "allowed_characters": sorted(request.constraints.character_names),
        },
        "input": request.payload,
    }
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
