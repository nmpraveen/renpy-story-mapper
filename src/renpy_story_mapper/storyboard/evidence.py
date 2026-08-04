"""Deterministic, non-executing projection of Ren'Py source into evidence records."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath

from renpy_story_mapper.errors import ScriptParseError
from renpy_story_mapper.ingestion import IngestionOptions, IngestionSource, ingest_input
from renpy_story_mapper.ingestion.contracts import SourceProvenance, SourceTier
from renpy_story_mapper.model import (
    Call,
    If,
    Jump,
    Label,
    LabelAnchor,
    Menu,
    Opaque,
    Return,
    ScriptModule,
    Simple,
    SourceSpan,
    Statement,
)
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.storyboard.model import (
    EvidenceDiagnostic,
    EvidenceIndex,
    EvidenceKind,
    EvidenceLocation,
    EvidenceOrigin,
    EvidenceProvenance,
    EvidenceRecord,
    EvidenceSelection,
)

EVIDENCE_SCHEMA_VERSION = 1
type SourceInput = str | os.PathLike[str] | IngestionSource

_KIND_ORDER = {
    EvidenceKind.LABEL: 0,
    EvidenceKind.DIALOGUE: 10,
    EvidenceKind.NARRATION: 11,
    EvidenceKind.MENU: 20,
    EvidenceKind.MENU_CAPTION: 21,
    EvidenceKind.CHOICE_ARM: 22,
    EvidenceKind.CONDITION: 23,
    EvidenceKind.ASSIGNMENT: 30,
    EvidenceKind.JUMP: 40,
    EvidenceKind.CALL: 41,
    EvidenceKind.RETURN: 42,
    EvidenceKind.PYTHON: 50,
    EvidenceKind.CUSTOM: 51,
    EvidenceKind.UNKNOWN: 52,
    EvidenceKind.STATEMENT: 53,
}
_ASSIGNMENT_PATTERN = re.compile(
    r"(?P<target>[A-Za-z_][\w.\[\]'\"]*)\s*(?P<operator>\+=|-=|\*=|/=|%=|=)"
)
_SPEAKER_PATTERN = re.compile(r"[A-Za-z_][\w.\.]*\s*")
_CUSTOM_KEYWORDS = {
    "image",
    "init",
    "layeredimage",
    "screen",
    "style",
    "transform",
    "translate",
}


def build_evidence_index(
    source: SourceInput,
    *,
    source_path: str | None = None,
    label: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    options: IngestionOptions | None = None,
) -> EvidenceIndex:
    """Build evidence for one source, label, and optional inclusive line span.

    A filesystem input is passed through the existing read-only ingestion service. An
    :class:`IngestionSource` is accepted for callers that already performed ingestion,
    which keeps this layer a narrow parser projection rather than a second loader.
    No source code is executed or evaluated.
    """

    selection = EvidenceSelection(source_path, label, start_line, end_line)
    ingestion_warnings: tuple[str, ...] = ()
    sources: tuple[IngestionSource, ...]
    if isinstance(source, IngestionSource):
        sources = (source,)
    else:
        result = ingest_input(source, options)
        sources = result.sources
        ingestion_warnings = result.warnings

    selected, selection_diagnostics = _select_source(sources, source_path)
    if selected is None:
        diagnostics = list(selection_diagnostics)
        diagnostics.extend(
            EvidenceDiagnostic("ingestion_warning", warning) for warning in ingestion_warnings
        )
        return EvidenceIndex(
            EVIDENCE_SCHEMA_VERSION,
            None,
            selection,
            (),
            tuple(diagnostics),
        )

    return _index_selected_source(
        selected,
        selection,
        tuple(selection_diagnostics),
        ingestion_warnings,
    )


def build_evidence_index_from_source(
    source: IngestionSource,
    *,
    label: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> EvidenceIndex:
    """Build an index from an already materialized ingestion source."""

    return build_evidence_index(
        source,
        source_path=source.path,
        label=label,
        start_line=start_line,
        end_line=end_line,
    )


def build_evidence_index_from_text(
    text: str,
    *,
    path: str = "game/source.rpy",
    source_path: str | None = None,
    label: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> EvidenceIndex:
    """Build an index from UTF-8 text without touching the filesystem.

    This helper is useful for focused tests and callers that own source acquisition.
    Its provenance still uses the same source contract as normal ingestion.
    """

    content = text.encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    source = IngestionSource(
        path,
        content,
        SourceProvenance(
            source_kind="original",
            locator=path,
            tier=SourceTier.LOOSE_ORIGINAL,
            input_sha256=digest,
            output_sha256=digest,
            line_basis="physical_original_source",
        ),
    )
    return build_evidence_index(
        source,
        source_path=source_path or path,
        label=label,
        start_line=start_line,
        end_line=end_line,
    )


def _select_source(
    sources: Sequence[IngestionSource], requested: str | None
) -> tuple[IngestionSource | None, tuple[EvidenceDiagnostic, ...]]:
    if requested is None:
        if len(sources) == 1:
            return sources[0], ()
        if not sources:
            return None, (
                EvidenceDiagnostic("source_not_found", "ingestion produced no source files"),
            )
        return None, (
            EvidenceDiagnostic(
                "source_selection_required",
                "source_path is required when ingestion produces multiple source files",
            ),
        )

    matches = tuple(source for source in sources if _path_matches(requested, source))
    if not matches:
        return None, (
            EvidenceDiagnostic(
                "source_not_found",
                f"no ingested source matches {requested!r}",
            ),
        )
    if len(matches) > 1:
        return None, (
            EvidenceDiagnostic(
                "source_selection_ambiguous",
                f"source_path {requested!r} matches multiple ingested sources",
            ),
        )
    return matches[0], ()


def _path_matches(requested: str, source: IngestionSource) -> bool:
    requested_keys = _path_keys(requested)
    source_keys = _path_keys(source.path) | _path_keys(source.provenance.locator)
    if requested_keys & source_keys:
        return True
    requested_name = requested.replace("\\", "/").strip().casefold()
    if requested_name.startswith("./"):
        requested_name = requested_name[2:]
    if "/" not in requested_name:
        source_names = _path_keys(source.path, include_basename=True)
        return requested_name in source_names
    return False


def _path_keys(value: str, *, include_basename: bool = False) -> set[str]:
    normalized = value.replace("\\", "/").strip()
    if not normalized:
        return set()
    normalized = re.sub(r"/+", "/", normalized)
    exact = normalized.casefold()
    keys = {exact}
    if exact.startswith("./"):
        keys.add(exact[2:])
    if exact.startswith("game/"):
        keys.add(exact[5:])
    else:
        keys.add(f"game/{exact}")

    if exact.endswith(".rpyc"):
        replacement = exact[:-5] + ".rpy"
        keys.update(_path_keys(replacement, include_basename=include_basename))
    elif exact.endswith(".rpy"):
        replacement = exact[:-4] + ".rpyc"
        keys.add(replacement)
        if replacement.startswith("game/"):
            keys.add(replacement[5:])
        else:
            keys.add(f"game/{replacement}")

    # A logical path is allowed to be supplied as a basename, but basename matches
    # remain ambiguous when two sources share that basename.
    if include_basename and "/" in exact:
        keys.add(exact.rsplit("/", 1)[-1])
    return keys


def _index_selected_source(
    source: IngestionSource,
    selection: EvidenceSelection,
    selection_diagnostics: tuple[EvidenceDiagnostic, ...],
    ingestion_warnings: Sequence[str],
) -> EvidenceIndex:
    provenance = EvidenceProvenance.from_source(source.provenance)
    origin = EvidenceOrigin(source.path, provenance)
    diagnostics = list(selection_diagnostics)
    diagnostics.extend(
        EvidenceDiagnostic("ingestion_warning", warning) for warning in ingestion_warnings
    )
    if not source.provenance.complete:
        diagnostics.append(
            EvidenceDiagnostic(
                "source_incomplete",
                "source provenance reports incomplete recovery; dynamic evidence may be missing",
            )
        )
    diagnostics.extend(
        EvidenceDiagnostic("source_warning", warning)
        for warning in source.provenance.warnings
    )

    try:
        text = source.content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        diagnostics.append(
            EvidenceDiagnostic("source_decode_failed", f"source is not valid UTF-8: {exc}")
        )
        return EvidenceIndex(
            EVIDENCE_SCHEMA_VERSION,
            origin,
            selection,
            (),
            tuple(diagnostics),
        )

    raw_lines = text.splitlines(keepends=True)
    try:
        module = parse_script(source.path, raw_lines)
    except ScriptParseError as exc:
        diagnostics.append(EvidenceDiagnostic("parse_failed", str(exc)))
        return EvidenceIndex(
            EVIDENCE_SCHEMA_VERSION,
            origin,
            selection,
            (),
            tuple(diagnostics),
        )

    diagnostics.extend(_parser_diagnostics(module))
    roots, label_diagnostics = _select_labels(module, selection.label)
    diagnostics.extend(label_diagnostics)
    if not roots:
        if selection.label is None and not module.labels:
            diagnostics.append(
                EvidenceDiagnostic(
                    "no_labels", "selected source contains no statically parsed labels"
                )
            )
        return EvidenceIndex(
            EVIDENCE_SCHEMA_VERSION,
            origin,
            selection,
            (),
            tuple(diagnostics),
        )

    collector = _Collector(source.path, provenance, raw_lines)
    for root in roots:
        if isinstance(root, Label):
            collector.collect_label(root)
        else:
            collector.collect_statement(root, None)

    records = collector.records
    records, line_diagnostics = _apply_line_selection(
        records,
        selection.start_line,
        selection.end_line,
        len(raw_lines),
    )
    diagnostics.extend(line_diagnostics)
    records.sort(key=_record_sort_key)
    return EvidenceIndex(
        EVIDENCE_SCHEMA_VERSION,
        origin,
        selection,
        tuple(records),
        tuple(diagnostics),
    )


def _select_labels(
    module: ScriptModule, requested: str | None
) -> tuple[tuple[Label | LabelAnchor, ...], tuple[EvidenceDiagnostic, ...]]:
    if requested is not None:
        matches = tuple(label for label in module.labels if label.name == requested)
        if not matches:
            return (), (
                EvidenceDiagnostic("label_not_found", f"no label named {requested!r} was found"),
            )
        diagnostics: tuple[EvidenceDiagnostic, ...] = ()
        if len(matches) > 1:
            diagnostics = (
                EvidenceDiagnostic(
                    "duplicate_label",
                    f"label {requested!r} occurs {len(matches)} times in the source",
                ),
            )
        return matches, diagnostics

    anchors = tuple(
        statement for statement in module.top_level if isinstance(statement, LabelAnchor)
    )
    if anchors:
        return anchors, ()
    return tuple(module.labels), ()


def _parser_diagnostics(module: ScriptModule) -> list[EvidenceDiagnostic]:
    diagnostics: list[EvidenceDiagnostic] = []
    for raw in module.diagnostics:
        code = str(raw.get("code", "parser_diagnostic"))
        message = str(raw.get("message", "parser reported a diagnostic"))
        source = _span_from_mapping(raw.get("source"))
        diagnostics.append(EvidenceDiagnostic(code, message, source=source))
    return diagnostics


def _span_from_mapping(value: object) -> SourceSpan | None:
    if not isinstance(value, Mapping):
        return None
    path = value.get("path")
    start = value.get("start")
    end = value.get("end")
    if not isinstance(path, str) or not isinstance(start, Mapping) or not isinstance(end, Mapping):
        return None
    start_line = start.get("line")
    start_column = start.get("column")
    end_line = end.get("line")
    end_column = end.get("column")
    if not (
        isinstance(start_line, int)
        and isinstance(start_column, int)
        and isinstance(end_line, int)
        and isinstance(end_column, int)
    ):
        return None
    return SourceSpan(path, start_line, start_column, end_line, end_column)


class _Collector:
    def __init__(
        self,
        path: str,
        provenance: EvidenceProvenance,
        raw_lines: Sequence[str],
    ) -> None:
        self.path = path
        self.provenance = provenance
        self.raw_lines = raw_lines
        self.records: list[EvidenceRecord] = []

    def add(
        self,
        kind: EvidenceKind,
        span: SourceSpan,
        parser_text: str,
        metadata: Mapping[str, object] | None = None,
        *,
        raw_span: SourceSpan | None = None,
    ) -> EvidenceRecord:
        evidence_span = raw_span or span
        values: dict[str, object] = {"parser_text": parser_text}
        if metadata:
            values.update(metadata)
        text = _raw_text(self.raw_lines, evidence_span)
        if not text:
            text = parser_text
        record = EvidenceRecord(
            _stable_id(self.path, self.provenance, kind, evidence_span, text),
            kind,
            text,
            EvidenceLocation(self.path, evidence_span, self.provenance),
            values,
        )
        self.records.append(record)
        return record

    def collect_label(self, label: Label) -> None:
        label_record = self.add(
            EvidenceKind.LABEL,
            label.span,
            label.text,
            {"name": label.name},
        )
        for statement in label.body:
            self.collect_statement(statement, label_record.id)

    def collect_statement(self, statement: Statement, parent_id: str | None) -> None:
        if isinstance(statement, LabelAnchor):
            record = self.add(
                EvidenceKind.LABEL,
                statement.span,
                statement.text,
                {"name": statement.name, **_parent_metadata(parent_id)},
            )
            for child in statement.body:
                self.collect_statement(child, record.id)
            return
        if isinstance(statement, Menu):
            menu = self.add(
                EvidenceKind.MENU,
                statement.span,
                statement.text,
                {
                    "choice_count": len(statement.choices),
                    "caption_count": len(statement.captions),
                    "availability_unresolved": statement.availability_unresolved,
                    **_parent_metadata(parent_id),
                },
            )
            for caption in statement.captions:
                self.add(
                    EvidenceKind.MENU_CAPTION,
                    caption.span,
                    caption.text,
                    {"caption": caption.caption, **_parent_metadata(menu.id)},
                )
            for ordinal, choice in enumerate(statement.choices):
                arm = self.add(
                    EvidenceKind.CHOICE_ARM,
                    choice.span,
                    choice.text,
                    {
                        "caption": choice.caption,
                        "condition": choice.condition,
                        "ordinal": ordinal,
                        **_parent_metadata(menu.id),
                    },
                )
                if choice.condition is not None:
                    condition = self.add(
                        EvidenceKind.CONDITION,
                        choice.span,
                        choice.text,
                        {
                            "condition": choice.condition,
                            "condition_type": "menu_arm",
                            "parent_id": arm.id,
                        },
                    )
                    self._collect_body(choice.body, condition.id)
                else:
                    self._collect_body(choice.body, arm.id)
            return
        if isinstance(statement, If):
            for ordinal, branch in enumerate(statement.branches):
                condition = self.add(
                    EvidenceKind.CONDITION,
                    branch.span,
                    branch.text,
                    {
                        "condition": branch.condition,
                        "condition_type": "if_branch" if branch.condition else "else_branch",
                        "ordinal": ordinal,
                        **_parent_metadata(parent_id),
                    },
                )
                self._collect_body(branch.body, condition.id)
            return

        if isinstance(statement, Simple):
            kind, metadata = _classify_simple(statement)
            metadata.update(_parent_metadata(parent_id))
            self.add(kind, statement.span, statement.text, metadata)
            return
        if isinstance(statement, Jump):
            self.add(
                EvidenceKind.JUMP,
                statement.span,
                statement.text,
                {
                    "target": statement.target,
                    "expression": statement.expression,
                    "resolved": statement.target is not None,
                    **_parent_metadata(parent_id),
                },
            )
            return
        if isinstance(statement, Call):
            self.add(
                EvidenceKind.CALL,
                statement.span,
                statement.text,
                {
                    "target": statement.target,
                    "expression": statement.expression,
                    "resolved": statement.target is not None,
                    **_parent_metadata(parent_id),
                },
            )
            return
        if isinstance(statement, Return):
            self.add(
                EvidenceKind.RETURN,
                statement.span,
                statement.text,
                {"expression": statement.expression, **_parent_metadata(parent_id)},
            )
            return
        if isinstance(statement, Opaque):
            kind, metadata = _classify_opaque(statement)
            metadata.update(_parent_metadata(parent_id))
            opaque_record = self.add(
                kind,
                statement.span,
                statement.text,
                metadata,
                raw_span=_opaque_span(statement.span, self.raw_lines),
            )
            for child in statement.body:
                self.collect_statement(child, opaque_record.id)
            return

        self.add(
            EvidenceKind.UNKNOWN,
            statement.span,
            statement.text,
            {"reason": "unrecognized_parser_statement", **_parent_metadata(parent_id)},
        )

    def _collect_body(self, body: Sequence[Statement], parent_id: str) -> None:
        for statement in body:
            self.collect_statement(statement, parent_id)


def _parent_metadata(parent_id: str | None) -> dict[str, object]:
    return {} if parent_id is None else {"parent_id": parent_id}


def _classify_simple(statement: Simple) -> tuple[EvidenceKind, dict[str, object]]:
    assignment = _assignment_details(statement.text)
    if assignment is not None:
        return EvidenceKind.ASSIGNMENT, {
            "assignment_type": assignment[0],
            "expression": assignment[1],
            "target": assignment[2],
            "operator": assignment[3],
            "syntax_kind": statement.kind,
        }

    dialogue = _dialogue_details(statement.text)
    if dialogue is not None:
        speaker, dialogue_text = dialogue
        metadata: dict[str, object] = {
            "dialogue_text": dialogue_text,
            "syntax_kind": statement.kind,
        }
        if speaker is None:
            return EvidenceKind.NARRATION, metadata
        metadata["speaker"] = speaker
        return EvidenceKind.DIALOGUE, metadata

    if statement.kind == "statement":
        if _is_custom_statement(statement.text):
            return EvidenceKind.CUSTOM, {"syntax_kind": statement.kind}
        return EvidenceKind.UNKNOWN, {"syntax_kind": statement.kind}
    return EvidenceKind.STATEMENT, {"syntax_kind": statement.kind}


def _classify_opaque(statement: Opaque) -> tuple[EvidenceKind, dict[str, object]]:
    stripped = statement.text.lstrip()
    keyword = stripped.split(None, 1)[0].rstrip(":") if stripped else ""
    values: dict[str, object] = {
        "opaque_reason": statement.reason,
        "syntax_kind": "opaque",
    }
    if keyword == "$":
        assignment = _assignment_details(statement.text)
        if assignment is not None:
            return EvidenceKind.ASSIGNMENT, {
                **values,
                "assignment_type": assignment[0],
                "expression": assignment[1],
                "target": assignment[2],
                "operator": assignment[3],
            }
        return EvidenceKind.CUSTOM, values
    if keyword == "python" or stripped.startswith("init python"):
        return EvidenceKind.PYTHON, values
    if statement.reason == "interactive_screen_call":
        return EvidenceKind.CUSTOM, values
    if keyword in _CUSTOM_KEYWORDS or stripped.startswith("init "):
        return EvidenceKind.CUSTOM, values
    return EvidenceKind.UNKNOWN, values


def _assignment_details(text: str) -> tuple[str, str, str | None, str | None] | None:
    stripped = text.strip()
    assignment_type = "statement"
    expression = stripped
    if stripped.startswith("$"):
        assignment_type = "inline_python"
        expression = stripped[1:].strip()
    else:
        match = re.match(r"(?:default|define)\b(?P<tail>.*)", stripped)
        if match is not None:
            assignment_type = stripped.split(None, 1)[0]
            expression = match.group("tail").strip()
        else:
            return None

    target: str | None = None
    operator: str | None = None
    match = _ASSIGNMENT_PATTERN.search(expression)
    if match is not None:
        target = match.group("target")
        operator = match.group("operator")
    if assignment_type == "inline_python" and not _looks_like_assignment(expression):
        return None
    if assignment_type in {"default", "define"} and target is None:
        return None
    return assignment_type, expression, target, operator


def _looks_like_assignment(expression: str) -> bool:
    try:
        tree = ast.parse(expression, mode="exec")
    except SyntaxError:
        return _ASSIGNMENT_PATTERN.search(expression) is not None
    return bool(
        tree.body
        and isinstance(tree.body[0], (ast.Assign, ast.AnnAssign, ast.AugAssign))
    )


def _dialogue_details(text: str) -> tuple[str | None, str] | None:
    stripped = text.lstrip()
    candidate = stripped
    speaker: str | None = None
    if not candidate.startswith(("'", '"')):
        match = _SPEAKER_PATTERN.match(candidate)
        if match is None:
            return None
        speaker = match.group(0).strip()
        candidate = candidate[match.end() :].lstrip()
        if not candidate.startswith(("'", '"')):
            return None
    literal = _read_string_literal(candidate)
    if literal is None:
        return None
    raw_literal, remainder = literal
    if remainder.strip():
        return None
    try:
        value = ast.literal_eval(raw_literal)
    except (SyntaxError, ValueError):
        return None
    return (speaker, value) if isinstance(value, str) else None


def _read_string_literal(source: str) -> tuple[str, str] | None:
    if not source or source[0] not in ("'", '"'):
        return None
    quote = source[0]
    delimiter = quote * 3 if source.startswith(quote * 3) else quote
    index = len(delimiter)
    escaped = False
    while index < len(source):
        if source.startswith(delimiter, index) and not escaped:
            end = index + len(delimiter)
            return source[:end], source[end:]
        char = source[index]
        escaped = char == "\\" and not escaped
        index += 1
    return None


def _is_custom_statement(text: str) -> bool:
    stripped = text.strip()
    first = stripped.split(None, 1)[0].rstrip(":") if stripped else ""
    return stripped.startswith("renpy.") or first in _CUSTOM_KEYWORDS


def _opaque_span(span: SourceSpan, raw_lines: Sequence[str]) -> SourceSpan:
    """Extend opaque block evidence over its inert, indented source body."""

    header_index = span.start_line - 1
    if header_index < 0 or header_index >= len(raw_lines):
        return span
    header = raw_lines[header_index].rstrip("\r\n")
    header_indent = len(header) - len(header.lstrip(" "))
    last_body_line: int | None = None
    cursor = span.end_line
    while cursor < len(raw_lines):
        current = raw_lines[cursor].rstrip("\r\n")
        if not current.strip():
            cursor += 1
            continue
        indent = len(current) - len(current.lstrip(" "))
        if indent <= header_indent:
            break
        last_body_line = cursor + 1
        cursor += 1
    if last_body_line is None:
        return span
    final_line = raw_lines[last_body_line - 1].rstrip("\r\n")
    return SourceSpan(
        span.path,
        span.start_line,
        span.start_column,
        last_body_line,
        len(final_line) + 1,
    )


def _raw_text(lines: Sequence[str], span: SourceSpan) -> str:
    start = max(0, span.start_line - 1)
    end = min(len(lines), max(start, span.end_line))
    return "".join(lines[start:end])


def _stable_id(
    path: str,
    provenance: EvidenceProvenance,
    kind: EvidenceKind,
    span: SourceSpan,
    text: str,
) -> str:
    identity = {
        "path": _logical_path(path),
        "source": {
            "tier": provenance.tier,
            "output_sha256": provenance.output_sha256,
            "line_basis": provenance.line_basis,
        },
        "kind": kind.value,
        "span": span.to_dict(),
        "text": text,
    }
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"ev_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _logical_path(path: str) -> str:
    normalized = PurePosixPath(path.replace("\\", "/"))
    return normalized.as_posix().casefold()


def _apply_line_selection(
    records: list[EvidenceRecord],
    start_line: int | None,
    end_line: int | None,
    line_count: int,
) -> tuple[list[EvidenceRecord], list[EvidenceDiagnostic]]:
    diagnostics: list[EvidenceDiagnostic] = []
    if start_line is None and end_line is None:
        return records, diagnostics

    if start_line is not None and start_line < 1:
        diagnostics.append(
            EvidenceDiagnostic("invalid_start_line", "start_line must be at least 1")
        )
    if end_line is not None and end_line < 1:
        diagnostics.append(EvidenceDiagnostic("invalid_end_line", "end_line must be at least 1"))
    if (
        start_line is not None
        and end_line is not None
        and start_line > end_line
    ):
        diagnostics.append(
            EvidenceDiagnostic("invalid_line_span", "start_line must not exceed end_line")
        )
        return [], diagnostics

    effective_start = max(1, start_line or 1)
    effective_end = min(line_count, end_line if end_line is not None else line_count)
    if start_line is not None and start_line > line_count:
        diagnostics.append(
            EvidenceDiagnostic("line_span_out_of_bounds", "start_line is beyond the source")
        )
        return [], diagnostics
    if end_line is not None and end_line > line_count:
        diagnostics.append(
            EvidenceDiagnostic("line_span_clipped", "end_line exceeds the source and was clipped")
        )
    if effective_end < effective_start:
        return [], diagnostics

    return [
        record
        for record in records
        if record.source.span.end_line >= effective_start
        and record.source.span.start_line <= effective_end
    ], diagnostics


def _record_sort_key(record: EvidenceRecord) -> tuple[object, ...]:
    span = record.source.span
    return (
        span.start_line,
        span.start_column,
        span.end_line,
        _KIND_ORDER[record.kind],
        record.text,
        record.id,
    )


__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "SourceInput",
    "build_evidence_index",
    "build_evidence_index_from_source",
    "build_evidence_index_from_text",
]
