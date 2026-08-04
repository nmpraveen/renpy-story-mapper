"""Data contracts for the deterministic storyboard evidence index."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from renpy_story_mapper.ingestion.contracts import SourceProvenance
from renpy_story_mapper.model import SourceSpan


class EvidenceKind(StrEnum):
    """Stable categories emitted by the source evidence projection."""

    LABEL = "label"
    DIALOGUE = "dialogue"
    NARRATION = "narration"
    MENU = "menu"
    MENU_CAPTION = "menu_caption"
    CHOICE_ARM = "choice_arm"
    CONDITION = "condition"
    ASSIGNMENT = "assignment"
    JUMP = "jump"
    CALL = "call"
    RETURN = "return"
    PYTHON = "python"
    CUSTOM = "custom"
    UNKNOWN = "unknown"
    STATEMENT = "statement"


@dataclass(frozen=True)
class EvidenceProvenance:
    """Input and recovery identity attached to every evidence record."""

    source_kind: str
    locator: str
    tier: str
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

    @classmethod
    def from_source(cls, provenance: SourceProvenance) -> EvidenceProvenance:
        return cls(
            source_kind=provenance.source_kind,
            locator=provenance.locator,
            tier=provenance.tier.value,
            input_sha256=provenance.input_sha256,
            output_sha256=provenance.output_sha256,
            line_basis=provenance.line_basis,
            tool_name=provenance.tool_name,
            tool_version=provenance.tool_version,
            tool_commit=provenance.tool_commit,
            tool_bundle_sha256=provenance.tool_bundle_sha256,
            options=dict(provenance.options),
            cache_hit=provenance.cache_hit,
            complete=provenance.complete,
            warnings=provenance.warnings,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_kind": self.source_kind,
            "locator": self.locator,
            "tier": self.tier,
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
class EvidenceOrigin:
    """Logical source path and its immutable provenance identity."""

    path: str
    provenance: EvidenceProvenance

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "provenance": self.provenance.to_dict()}


@dataclass(frozen=True)
class EvidenceLocation:
    """A source span with the source identity needed to re-open it."""

    path: str
    span: SourceSpan
    provenance: EvidenceProvenance

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "span": self.span.to_dict(),
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True)
class EvidenceSelection:
    """The caller's requested source, label, and inclusive physical-line window."""

    source_path: str | None
    label: str | None
    start_line: int | None
    end_line: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "label": self.label,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


@dataclass(frozen=True)
class EvidenceDiagnostic:
    """A parser or selection issue that remains visible to later phases."""

    code: str
    message: str
    severity: str = "warning"
    source: SourceSpan | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.source is not None:
            value["source"] = self.source.to_dict()
        return value


@dataclass(frozen=True)
class EvidenceRecord:
    """One exact source construct owned by the deterministic evidence layer."""

    id: str
    kind: EvidenceKind
    text: str
    source: EvidenceLocation
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def source_text(self) -> str:
        """Compatibility name for callers that call the exact text source text."""

        return self.text

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "text": self.text,
            "source": self.source.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EvidenceIndex:
    """Deterministic, source-grounded records for one selected evidence scope."""

    schema_version: int
    source: EvidenceOrigin | None
    selection: EvidenceSelection
    records: tuple[EvidenceRecord, ...]
    diagnostics: tuple[EvidenceDiagnostic, ...] = ()

    def records_of(self, kind: EvidenceKind | str) -> tuple[EvidenceRecord, ...]:
        wanted = EvidenceKind(kind)
        return tuple(record for record in self.records if record.kind is wanted)

    @property
    def labels(self) -> tuple[EvidenceRecord, ...]:
        return self.records_of(EvidenceKind.LABEL)

    @property
    def menus(self) -> tuple[EvidenceRecord, ...]:
        return self.records_of(EvidenceKind.MENU)

    @property
    def choice_arms(self) -> tuple[EvidenceRecord, ...]:
        return self.records_of(EvidenceKind.CHOICE_ARM)

    @property
    def conditions(self) -> tuple[EvidenceRecord, ...]:
        return self.records_of(EvidenceKind.CONDITION)

    @property
    def assignments(self) -> tuple[EvidenceRecord, ...]:
        return self.records_of(EvidenceKind.ASSIGNMENT)

    def to_dict(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for record in self.records:
            counts[record.kind.value] = counts.get(record.kind.value, 0) + 1
        return {
            "schema_version": self.schema_version,
            "source": None if self.source is None else self.source.to_dict(),
            "selection": self.selection.to_dict(),
            "records": [record.to_dict() for record in self.records],
            "labels": [record.id for record in self.labels],
            "menus": [record.id for record in self.menus],
            "choice_arms": [record.id for record in self.choice_arms],
            "conditions": [record.id for record in self.conditions],
            "assignments": [record.id for record in self.assignments],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "counts": dict(sorted(counts.items())),
        }
