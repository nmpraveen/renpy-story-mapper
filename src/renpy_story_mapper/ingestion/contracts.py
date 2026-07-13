"""Public, toolkit-neutral ingestion contracts."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

type CancelCheck = Callable[[], bool] | None


class InputKind(StrEnum):
    GAME_FOLDER = "game_folder"
    SOURCE_FILE = "source_file"
    COMPILED_FILE = "compiled_file"
    ARCHIVE = "archive"
    PROJECT = "project"


class SourceTier(StrEnum):
    LOOSE_ORIGINAL = "loose_original_rpy"
    ARCHIVED_ORIGINAL = "archived_original_rpy"
    LOOSE_RECOVERED = "loose_recovered_rpyc"
    ARCHIVED_RECOVERED = "archived_recovered_rpyc"


@dataclass(frozen=True)
class IngestionOptions:
    """Strict defaults and explicit resource limits for ingestion."""

    allow_partial_recovery: bool = False
    cache_root: Path | None = None
    recovery_timeout_seconds: float = 30.0
    max_input_bytes: int = 64 * 1024 * 1024
    max_output_bytes: int = 128 * 1024 * 1024
    max_decompressed_bytes: int = 256 * 1024 * 1024
    max_total_output_bytes: int = 512 * 1024 * 1024
    max_log_bytes: int = 64 * 1024
    max_memory_bytes: int = 512 * 1024 * 1024
    max_sources: int = 100_000

    def resolved_cache_root(self) -> Path:
        if self.cache_root is not None:
            return self.cache_root.resolve()
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return (base / "RenPyStoryMapper" / "recovery-cache-v1").resolve()


@dataclass(frozen=True)
class SourceCandidate:
    logical_path: str
    tier: SourceTier
    locator: str
    input_hash: str
    size_bytes: int
    container_path: Path
    archive_entry: str | None = None


@dataclass(frozen=True)
class IngestionPlan:
    requested_path: Path
    resolved_input: Path
    input_kind: InputKind
    source_root: Path | None
    candidates: tuple[SourceCandidate, ...]
    selected: tuple[SourceCandidate, ...]
    existing_project: Path | None = None
    warnings: tuple[str, ...] = ()
    secondary_candidates: tuple[SourceCandidate, ...] = ()


@dataclass(frozen=True)
class SourceProvenance:
    source_kind: str
    locator: str
    tier: SourceTier
    input_sha256: str
    output_sha256: str
    line_basis: str
    tool_name: str | None = None
    tool_version: str | None = None
    tool_commit: str | None = None
    tool_bundle_sha256: str | None = None
    options: Mapping[str, object] = field(default_factory=dict)
    cache_hit: bool = False
    complete: bool = True
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "source_kind": self.source_kind,
            "locator": self.locator,
            "tier": self.tier.value,
            "input_sha256": self.input_sha256,
            "output_sha256": self.output_sha256,
            "line_basis": self.line_basis,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "tool_commit": self.tool_commit,
            "tool_bundle_sha256": self.tool_bundle_sha256,
            "options": dict(self.options),
            "cache_hit": self.cache_hit,
            "complete": self.complete,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class IngestionSource:
    path: str
    content: bytes
    provenance: SourceProvenance


@dataclass(frozen=True)
class RecoveryFailure:
    logical_path: str
    locator: str
    input_sha256: str
    error_kind: str
    sanitized_error: str


@dataclass(frozen=True)
class IngestionResult:
    plan: IngestionPlan
    sources: tuple[IngestionSource, ...]
    complete: bool
    ai_transmission_blocked: bool
    warnings: tuple[str, ...] = ()
    recovery_failures: tuple[RecoveryFailure, ...] = ()
    secondary_sources: tuple[IngestionSource, ...] = ()
    secondary_recovery_failures: tuple[RecoveryFailure, ...] = ()

    @property
    def content_by_path(self) -> dict[str, bytes]:
        return {source.path: source.content for source in self.sources}
