"""Data contracts for the deterministic storyboard evidence index."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

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
            warnings=tuple(_redact_message(warning) for warning in provenance.warnings),
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
            "options": _redact_value(self.options, preserve_exact_text=True),
            "cache_hit": self.cache_hit,
            "complete": self.complete,
            "warnings": [_redact_message(warning) for warning in self.warnings],
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
            "facts": _redact_value(self.metadata, preserve_exact_text=True),
            "metadata": _redact_value(self.metadata, preserve_exact_text=True),
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
        selection = self.selection.to_dict()
        selection_issue = next(
            (
                diagnostic
                for diagnostic in self.diagnostics
                if diagnostic.code
                in {
                    "label_not_found",
                    "source_not_found",
                    "source_selection_required",
                    "source_selection_ambiguous",
                }
            ),
            None,
        )
        selection["status"] = "unresolved" if selection_issue is not None else "resolved"
        selection["uncertainty"] = (
            None if selection_issue is None else _redact_message(selection_issue.message)
        )
        return {
            "schema_version": f"storyboard-evidence-v{self.schema_version}",
            "source": None if self.source is None else self.source.to_dict(),
            "selection": selection,
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


_PATH_KEYS = frozenset(
    {
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
)
_MESSAGE_KEYS = frozenset(
    {
        "warning",
        "warnings",
        "message",
        "error",
        "errors",
        "diagnostic",
        "diagnostics",
        "detail",
        "details",
    }
)
_EXACT_TEXT_KEYS = frozenset({"text", "source_text", "parser_text", "dialogue_text"})
_ABSOLUTE_PATH_TOKEN = re.compile(
    r"(?i)(?<![A-Za-z0-9+.\-:/])(?:file://)?(?:[A-Za-z]:[\\/]|\\\\|//|/)[^\s\"'<>]+"
)


def _is_absolute_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    if normalized.casefold().startswith("file://"):
        normalized = normalized[7:]
    return bool(re.match(r"^[A-Za-z]:/", normalized)) or normalized.startswith("/")


def _absolute_basename(value: str) -> str:
    normalized = value.replace("\\", "/")
    if normalized.casefold().startswith("file://"):
        normalized = normalized[7:]
    normalized = normalized.rstrip("/")
    name = normalized.rsplit("/", 1)[-1]
    return name or "source"


def _public_path(value: str) -> str:
    """Return a public path while preserving relative identity."""

    normalized = str(value).replace("\\", "/").strip()
    if not normalized:
        return "source"
    if _is_absolute_path(normalized):
        return f"source/{_absolute_basename(normalized)}"
    # Do not resolve or discard ``..``: relative paths can be stable logical identities.
    return normalized


def _public_span(span: SourceSpan) -> dict[str, object]:
    value = span.to_dict()
    value["path"] = _public_path(span.path)
    return value


def _redact_message(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        trailing = ""
        while token and token[-1] in ",.;!?)]}>":
            trailing = token[-1] + trailing
            token = token[:-1]
        return f"source/{_absolute_basename(token)}{trailing}"

    return _ABSOLUTE_PATH_TOKEN.sub(replace, value)


def _redact_mapping(value: Mapping[str, object]) -> dict[str, object]:
    redacted = _redact_value(value, preserve_exact_text=True)
    return redacted if isinstance(redacted, dict) else {}


def _redact_value(
    value: object,
    *,
    preserve_exact_text: bool = False,
    key: str | None = None,
) -> object:
    """Recursively redact local paths in public/AI data without changing source text."""

    normalized_key = key.casefold() if key is not None else None
    if isinstance(value, Mapping):
        return {
            str(raw_key): _redact_value(
                child,
                preserve_exact_text=preserve_exact_text,
                key=str(raw_key),
            )
            for raw_key, child in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _redact_value(child, preserve_exact_text=preserve_exact_text, key=key)
            for child in value
        ]
    if isinstance(value, str):
        if normalized_key in _PATH_KEYS:
            return _public_path(value)
        if preserve_exact_text and normalized_key in _EXACT_TEXT_KEYS:
            return value
        if (
            normalized_key in _MESSAGE_KEYS
            or _is_absolute_path(value)
            or _ABSOLUTE_PATH_TOKEN.search(value)
        ):
            return _redact_message(value)
    return value


def redact_public_value(value: object, *, preserve_exact_text: bool = False) -> object:
    """Return recursively redacted JSON-compatible data for public or AI artifacts."""

    return _redact_value(value, preserve_exact_text=preserve_exact_text)


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
