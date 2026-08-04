"""Data contracts for the deterministic storyboard evidence index."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath

from renpy_story_mapper.ingestion.contracts import SourceProvenance
from renpy_story_mapper.model import SourceSpan


class EvidenceKind(StrEnum):
    """Stable categories emitted by the source evidence projection."""

    SOURCE_LINE = "source_line"
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
            locator=_public_path(provenance.locator),
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
            "options": _redact_mapping(self.options),
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
        return {"path": _public_path(self.path), "provenance": self.provenance.to_dict()}


@dataclass(frozen=True)
class EvidenceLocation:
    """A source span with the source identity needed to re-open it."""

    path: str
    span: SourceSpan
    provenance: EvidenceProvenance

    def to_dict(self) -> dict[str, object]:
        return {
            "path": _public_path(self.path),
            "span": _public_span(self.span),
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
            "source_path": None if self.source_path is None else _public_path(self.source_path),
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
            "message": _redact_message(self.message),
            "severity": self.severity,
        }
        if self.source is not None:
            value["source"] = _public_span(self.source)
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
            "source_text": self.text,
            "facts": dict(self.metadata),
            "metadata": dict(self.metadata),
            "accountable": self.is_leaf,
            "role": "leaf" if self.is_leaf else "annotation",
        }

    @property
    def is_leaf(self) -> bool:
        """Whether this record is a source-ledger leaf rather than a parser annotation."""

        return self.kind is EvidenceKind.SOURCE_LINE and self.metadata.get("leaf") is True


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
        record_values = [record.to_dict() for record in self.records]
        records_by_id = {
            record_id: record
            for record_id, record in (
                (record.get("id"), record) for record in record_values
            )
            if isinstance(record_id, str)
        }
        menus: list[dict[str, object]] = []
        for record in self.menus:
            arm_ids = [
                arm.id
                for arm in self.choice_arms
                if arm.metadata.get("parent_id") == record.id
            ]
            arm_ids.sort(key=lambda identifier: _record_order(records_by_id[identifier]))
            menus.append(
                {
                    "id": record.id,
                    "arm_ids": arm_ids,
                    "caption_ids": [
                        caption.id
                        for caption in self.records_of(EvidenceKind.MENU_CAPTION)
                        if caption.metadata.get("parent_id") == record.id
                    ],
                }
            )
        menus.sort(key=lambda item: _record_order(records_by_id[str(item["id"])]))
        source_line_records = self.records_of(EvidenceKind.SOURCE_LINE)
        leaf_ids = [record.id for record in source_line_records if record.is_leaf]
        annotation_ids = [
            record.id for record in self.records if record.kind is not EvidenceKind.SOURCE_LINE
        ]
        return {
            "schema_version": f"storyboard-evidence-v{self.schema_version}",
            "source": None if self.source is None else self.source.to_dict(),
            "selection": self.selection.to_dict(),
            "records": record_values,
            "ledger": [records_by_id[record.id] for record in source_line_records],
            "annotations": [records_by_id[identifier] for identifier in annotation_ids],
            "leaf_evidence_ids": leaf_ids,
            "annotation_evidence_ids": annotation_ids,
            "accountable_evidence_ids": leaf_ids,
            "menus": menus,
            "labels": [record.id for record in self.labels],
            "choice_arms": [record.id for record in self.choice_arms],
            "conditions": [record.id for record in self.conditions],
            "assignments": [record.id for record in self.assignments],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "counts": dict(sorted(counts.items())),
        }


def _public_path(value: str) -> str:
    """Return a stable logical path without exposing a local machine path."""

    normalized = str(value).replace("\\", "/")
    absolute = bool(re.match(r"^[A-Za-z]:/", normalized)) or normalized.startswith("/")
    parts = [part for part in PurePosixPath(normalized).parts if part not in {"", ".", ".."}]
    if not parts:
        return "source"
    if absolute:
        return f"source/{parts[-1]}"
    return "/".join(parts)


def _public_span(span: SourceSpan) -> dict[str, object]:
    value = span.to_dict()
    value["path"] = _public_path(span.path)
    return value


def _redact_message(value: str) -> str:
    normalized = value.replace("\\", "/")
    parts = normalized.split()
    redacted: list[str] = []
    for part in parts:
        if re.match(r"^[A-Za-z]:/", part) or part.startswith("/"):
            redacted.append(f"source/{PurePosixPath(part).name}")
        else:
            redacted.append(part)
    return " ".join(redacted)


def _redact_mapping(value: Mapping[str, object]) -> dict[str, object]:
    path_keys = {
        "path",
        "locator",
        "source_path",
        "relative_path",
        "file",
        "filename",
        "input_path",
        "output_path",
        "output_directory",
        "cwd",
    }
    result: dict[str, object] = {}
    for raw_key, child in value.items():
        key = str(raw_key)
        if key.casefold() in path_keys and isinstance(child, str):
            result[key] = _public_path(child)
        elif isinstance(child, Mapping):
            result[key] = _redact_mapping(child)
        elif isinstance(child, list):
            result[key] = [
                _redact_mapping(item) if isinstance(item, Mapping) else item for item in child
            ]
        else:
            result[key] = child
    return result


def _record_order(record: Mapping[str, object]) -> tuple[object, ...]:
    source = record.get("source")
    if not isinstance(source, Mapping):
        return (1, "", 0, 0, "")
    span = source.get("span")
    if not isinstance(span, Mapping):
        return (1, str(source.get("path", "")), 0, 0, str(record.get("id", "")))
    start = span.get("start")
    if not isinstance(start, Mapping):
        return (1, str(source.get("path", "")), 0, 0, str(record.get("id", "")))
    line = start.get("line") if isinstance(start.get("line"), int) else 0
    column = start.get("column") if isinstance(start.get("column"), int) else 0
    return (0, str(source.get("path", "")), line, column, str(record.get("id", "")))
