"""Static project analysis pipeline over durable SQLite storage.

This module only parses inert source text. It never imports, evaluates, or executes game code.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import cast

from renpy_story_mapper.errors import ScriptParseError, StoryMapperError
from renpy_story_mapper.graph import build_graph
from renpy_story_mapper.importer import inventory_archive
from renpy_story_mapper.model import (
    Call,
    If,
    IfBranch,
    Jump,
    Label,
    LabelAnchor,
    Menu,
    MenuCaption,
    MenuChoice,
    Opaque,
    Return,
    ScriptModule,
    Simple,
    SourceSpan,
    Statement,
)
from renpy_story_mapper.parser import parse_script
from renpy_story_mapper.project import (
    PayloadRecord,
    Project,
    RefreshReport,
    SourceFingerprint,
)
from renpy_story_mapper.rpa import RpaArchive, fingerprint_file
from renpy_story_mapper.semantic import build_semantic_story
from renpy_story_mapper.state import FactStatus, StateAnalysis, StateEvidence, extract_state
from renpy_story_mapper.storage import ProjectOperationCancelled, canonical_json

CancelCheck = Callable[[], bool] | None


def create_folder_project(
    database_path: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
    *,
    cancel_check: CancelCheck = None,
) -> Project:
    root = _source_root(source_root)
    _check_cancelled(cancel_check)
    project = Project.create(
        database_path,
        metadata={"source_kind": "folder", "source_root": str(root), "entry_label": "start"},
    )
    try:
        _refresh_open_project(
            project, _read_source_tree(root), entry_label="start", cancel_check=cancel_check
        )
        return project
    except BaseException:
        project.delete()
        raise


def refresh_folder_project(
    database_path: str | os.PathLike[str],
    source_root: str | os.PathLike[str],
    *,
    cancel_check: CancelCheck = None,
) -> RefreshReport:
    root = _source_root(source_root)
    project_path = Path(database_path).resolve(strict=True)
    content = _read_source_tree(root)
    temporary = project_path.with_name(f".{project_path.name}.{uuid.uuid4().hex}.refresh.tmp")
    _check_cancelled(cancel_check)
    original = Project.open(project_path)
    try:
        if _content_matches(original, content):
            return RefreshReport((), tuple(sorted(content)), ())
        original.backup(temporary)
    finally:
        original.close()
    try:
        staged = Project.open(temporary)
        try:
            metadata = staged.metadata()
            entry_label = str(metadata.get("entry_label", "start"))
            report = _refresh_open_project(
                staged,
                content,
                entry_label=entry_label,
                cancel_check=cancel_check,
            )
        finally:
            staged.close()
        _check_cancelled(cancel_check)
        os.replace(temporary, project_path)
        return report
    finally:
        if temporary.exists():
            temporary.unlink()


def create_rpa_project(
    database_path: str | os.PathLike[str],
    archive_path: str | os.PathLike[str],
    *,
    entry_label: str = "start",
    cancel_check: CancelCheck = None,
) -> Project:
    archive = Path(archive_path).resolve(strict=True)
    _check_cancelled(cancel_check)
    content, manifest = _read_archive_sources(archive, cancel_check=cancel_check)
    project = Project.create(
        database_path,
        metadata={
            "source_kind": "archive",
            "source_path": str(archive),
            "entry_label": entry_label,
        },
    )
    try:
        _refresh_open_project(project, content, entry_label=entry_label, cancel_check=cancel_check)
        project.write_payloads(
            [PayloadRecord("import_manifest", "authoritative", manifest, tuple(sorted(content)))],
            cancelled=cancel_check,
        )
        return project
    except BaseException:
        project.delete()
        raise


def refresh_rpa_project(
    database_path: str | os.PathLike[str],
    archive_path: str | os.PathLike[str],
    *,
    cancel_check: CancelCheck = None,
) -> RefreshReport:
    archive = Path(archive_path).resolve(strict=True)
    content, manifest = _read_archive_sources(archive, cancel_check=cancel_check)
    project_path = Path(database_path).resolve(strict=True)
    temporary = project_path.with_name(f".{project_path.name}.{uuid.uuid4().hex}.refresh.tmp")
    original = Project.open(project_path)
    try:
        if _content_matches(original, content):
            return RefreshReport((), tuple(sorted(content)), ())
        original.backup(temporary)
    finally:
        original.close()
    try:
        staged = Project.open(temporary)
        try:
            metadata = staged.metadata()
            entry_label = str(metadata.get("entry_label", "start"))
            report = _refresh_open_project(
                staged, content, entry_label=entry_label, cancel_check=cancel_check
            )
            staged.write_payloads(
                [
                    PayloadRecord(
                        "import_manifest", "authoritative", manifest, tuple(sorted(content))
                    )
                ],
                cancelled=cancel_check,
            )
        finally:
            staged.close()
        _check_cancelled(cancel_check)
        os.replace(temporary, project_path)
        return report
    finally:
        if temporary.exists():
            temporary.unlink()


def project_snapshot(project: Project) -> dict[str, object]:
    return {
        "schema_version": project.schema_version,
        "sources": [
            {
                "path": source.path,
                "sha256": source.content_hash,
                "size_bytes": source.size_bytes,
            }
            for source in project.sources()
        ],
        "graph": project.payload("m01_graph", "authoritative") or {},
        "semantic": project.payload("m02_semantic", "authoritative") or {},
        "import_manifest": project.payload("import_manifest", "authoritative") or {},
        "requirements": _payload_lists(project, "gates"),
        "effects": _payload_lists(project, "effects"),
        "state_variables": _payload_lists(project, "state_registry"),
        "unresolved": _payload_lists(project, "unresolved"),
        "diagnostics": _payload_lists(project, "diagnostics"),
    }


def _refresh_open_project(
    project: Project,
    content_by_path: Mapping[str, bytes],
    *,
    entry_label: str,
    cancel_check: CancelCheck,
) -> RefreshReport:
    previous_dependencies = _stored_dependencies(project)
    previous_registry = project.payload("state_registry", "authoritative")
    fingerprints = tuple(
        SourceFingerprint.from_bytes(path, content_by_path[path])
        for path in sorted(content_by_path)
    )
    refresh = project.refresh_sources(fingerprints, cancelled=cancel_check)
    parsed_paths = set(refresh.changed)
    modules: dict[str, ScriptModule] = {}
    for path in sorted(content_by_path):
        _check_cancelled(cancel_check)
        if path not in parsed_paths:
            cached = project.payload("parsed_source", path)
            if cached is not None:
                modules[path] = _module_from_value(cached)
                continue
            parsed_paths.add(path)
        modules[path] = _parse_source(path, content_by_path[path])

    module_values = [modules[path] for path in sorted(modules)]
    dependencies = _source_dependencies(module_values)
    invalidated = _dependent_closure(
        _merge_dependencies(previous_dependencies, dependencies),
        set(refresh.changed) | set(refresh.removed),
    )
    graph = build_graph(module_values, entry_label=entry_label)
    diagnostics = [item for module in module_values for item in module.diagnostics]
    diagnostics.sort(key=lambda item: canonical_json(item))
    graph["diagnostics"] = diagnostics
    counts = cast(dict[str, object], graph["counts"])
    counts["diagnostics"] = len(diagnostics)
    semantic = build_semantic_story(graph)
    state = extract_state(module_values)

    records = _analysis_records(
        modules,
        dependencies,
        graph,
        semantic,
        state,
        parsed_paths,
        previous_registry,
    )
    project.write_payloads(records, cancelled=cancel_check)
    reused = set(refresh.unchanged) - parsed_paths
    return RefreshReport(
        tuple(sorted(parsed_paths)),
        tuple(sorted(reused)),
        tuple(sorted(invalidated)),
        refresh.removed,
    )


def _analysis_records(
    modules: Mapping[str, ScriptModule],
    dependencies: Mapping[str, set[str]],
    graph: dict[str, object],
    semantic: dict[str, object],
    state: StateAnalysis,
    parsed_paths: set[str],
    previous_registry: object,
) -> list[PayloadRecord]:
    all_paths = tuple(sorted(modules))
    records: list[PayloadRecord] = []
    for path in sorted(parsed_paths):
        records.append(
            PayloadRecord("parsed_source", path, _module_to_value(modules[path]), (path,))
        )
    for path in all_paths:
        records.append(
            PayloadRecord(
                "source_dependencies", path, sorted(dependencies.get(path, set())), (path,)
            )
        )
    records.extend(
        (
            PayloadRecord("m01_graph", "authoritative", graph, all_paths),
            PayloadRecord("m02_semantic", "authoritative", semantic, all_paths),
        )
    )

    requirements_by_path: dict[str, list[dict[str, object]]] = {}
    effects_by_path: dict[str, list[dict[str, object]]] = {}
    unresolved_by_path: dict[str, list[dict[str, object]]] = {}
    for requirement in state.requirements:
        value = _requirement_value(requirement.to_dict(), requirement.evidence)
        destination = (
            requirements_by_path if requirement.status is FactStatus.PROVEN else unresolved_by_path
        )
        destination.setdefault(requirement.evidence.source_file, []).append(value)
    for effect in state.effects:
        value = _effect_value(effect.to_dict(), effect.evidence)
        destination = (
            effects_by_path if effect.status is not FactStatus.UNRESOLVED else unresolved_by_path
        )
        destination.setdefault(effect.evidence.source_file, []).append(value)

    for path, values in _semantic_unresolved_by_path(semantic).items():
        unresolved_by_path.setdefault(path, []).extend(values)
    for path in all_paths:
        module_diagnostics = sorted(modules[path].diagnostics, key=canonical_json)
        if module_diagnostics:
            records.append(PayloadRecord("diagnostics", path, module_diagnostics, (path,)))
        if path in requirements_by_path:
            records.append(PayloadRecord("gates", path, requirements_by_path[path], (path,)))
        if path in effects_by_path:
            records.append(PayloadRecord("effects", path, effects_by_path[path], (path,)))
        if path in unresolved_by_path:
            unique = {str(value["id"]): value for value in unresolved_by_path[path]}
            ordered = [unique[key] for key in sorted(unique)]
            records.append(PayloadRecord("unresolved", path, ordered, (path,)))
    variables = [_state_variable_value(item.to_dict()) for item in state.variables]
    variables = _merge_state_variable_metadata(variables, previous_registry)
    records.append(PayloadRecord("state_registry", "authoritative", variables, all_paths))
    return records


def _requirement_value(value: dict[str, object], evidence: StateEvidence) -> dict[str, object]:
    result = dict(value)
    result["evidence"] = _evidence_value(evidence)
    result["id"] = _stable_record_id("requirement", result)
    return result


def _effect_value(value: dict[str, object], evidence: StateEvidence) -> dict[str, object]:
    result = dict(value)
    result["evidence"] = _evidence_value(evidence)
    result["id"] = _stable_record_id("effect", result)
    return result


def _state_variable_value(value: dict[str, object]) -> dict[str, object]:
    result = dict(value)
    raw_evidence = _required_list(result.get("evidence"), "state variable evidence")
    result["evidence"] = [_evidence_mapping_value(item) for item in raw_evidence]
    result["id"] = _stable_record_id(
        "state_variable", {"original_name": result.get("original_name")}
    )
    return result


def _merge_state_variable_metadata(
    inferred: list[dict[str, object]], previous: object
) -> list[dict[str, object]]:
    if not isinstance(previous, list):
        return inferred
    by_name: dict[str, dict[str, object]] = {}
    for item in previous:
        if isinstance(item, dict) and isinstance(item.get("original_name"), str):
            by_name[cast(str, item["original_name"])] = item
    for value in inferred:
        name = value.get("original_name")
        old = by_name.get(name) if isinstance(name, str) else None
        if old is None:
            continue
        for field in ("display_name", "category", "user_override"):
            if field in old:
                value[field] = old[field]
    return inferred


def _semantic_unresolved_by_path(
    semantic: Mapping[str, object],
) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {}
    for raw in _required_list(semantic.get("unresolved"), "semantic unresolved"):
        value = dict(_required_mapping(raw, "semantic unresolved item"))
        source = _required_mapping(value.get("source"), "semantic unresolved source")
        path = _required_string(source.get("path"), "semantic unresolved source path")
        start = _required_mapping(source.get("start"), "semantic unresolved start")
        end = _required_mapping(source.get("end"), "semantic unresolved end")
        value["status"] = "unresolved"
        value["evidence"] = {
            "source_path": path,
            "start_line": _required_int(start.get("line"), "semantic start line"),
            "end_line": _required_int(end.get("line"), "semantic end line"),
        }
        result.setdefault(path, []).append(value)
    return result


def _evidence_value(evidence: StateEvidence) -> dict[str, object]:
    return {
        "source_path": evidence.source_file,
        "start_line": evidence.span.start_line,
        "end_line": evidence.span.end_line,
    }


def _evidence_mapping_value(raw: object) -> dict[str, object]:
    value = _required_mapping(raw, "state evidence")
    source = _required_mapping(value.get("source"), "state evidence source")
    start = _required_mapping(source.get("start"), "state evidence start")
    end = _required_mapping(source.get("end"), "state evidence end")
    return {
        "source_path": _required_string(value.get("source_file"), "state evidence path"),
        "start_line": _required_int(start.get("line"), "state evidence start line"),
        "end_line": _required_int(end.get("line"), "state evidence end line"),
    }


def _stable_record_id(kind: str, value: Mapping[str, object]) -> str:
    identity = {key: item for key, item in value.items() if key != "id"}
    return f"{kind}_{hashlib.sha256(canonical_json(identity)).hexdigest()[:20]}"


def _payload_lists(project: Project, collection: str) -> list[object]:
    result: list[object] = []
    for key in project.payload_keys(collection):
        value = project.payload(collection, key)
        if not isinstance(value, list):
            raise ValueError(f"project {collection}/{key} payload must be a list")
        result.extend(value)
    return result


def _read_source_tree(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for candidate in sorted(root.rglob("*.rpy"), key=lambda item: item.as_posix().casefold()):
        if not candidate.is_file():
            continue
        resolved = candidate.resolve(strict=True)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(f"source path escapes the selected root: {candidate}") from exc
        result[relative] = resolved.read_bytes()
    if not result:
        raise ValueError(f"source folder contains no .rpy files: {root}")
    return result


def _read_archive_sources(
    archive_path: Path, *, cancel_check: CancelCheck
) -> tuple[dict[str, bytes], dict[str, object]]:
    before = fingerprint_file(archive_path)
    archive = RpaArchive(archive_path)
    inventory = inventory_archive(archive, before)
    content: dict[str, bytes] = {}
    for entry in inventory.selected_sources:
        _check_cancelled(cancel_check)
        content[entry.path] = b"".join(archive.iter_entry_bytes(entry))
    if not content:
        raise StoryMapperError(
            "archive contains no .rpy source; this analyzer does not decompile .rpyc"
        )
    after = fingerprint_file(archive_path)
    if before != after:
        raise StoryMapperError("archive hash, size, or modification time changed during analysis")
    manifest = dict(inventory.manifest)
    manifest["archive_integrity"] = {
        "verified_unchanged": True,
        "before": before.to_dict(),
        "after": after.to_dict(),
    }
    return content, manifest


def _content_matches(project: Project, content_by_path: Mapping[str, bytes]) -> bool:
    existing = {source.path: source.content_hash for source in project.sources()}
    incoming = {
        path: hashlib.sha256(content).hexdigest() for path, content in content_by_path.items()
    }
    return existing == incoming


def _source_root(value: str | os.PathLike[str]) -> Path:
    root = Path(value).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"source root is not a directory: {root}")
    return root


def _parse_source(path: str, content: bytes) -> ScriptModule:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ScriptParseError(f"{path}: source is not valid UTF-8") from exc
    return parse_script(path, text.splitlines(keepends=True))


def _stored_dependencies(project: Project) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for path in project.payload_keys("source_dependencies"):
        value = project.payload("source_dependencies", path)
        result[path] = {
            _required_string(item, "stored dependency")
            for item in _required_list(value, "stored dependencies")
        }
    return result


def _merge_dependencies(
    left: Mapping[str, set[str]], right: Mapping[str, set[str]]
) -> dict[str, set[str]]:
    result = {key: set(value) for key, value in left.items()}
    for key, value in right.items():
        result.setdefault(key, set()).update(value)
    return result


def _dependent_closure(dependencies: Mapping[str, set[str]], affected: set[str]) -> set[str]:
    reverse: dict[str, set[str]] = {}
    for source, targets in dependencies.items():
        for target in targets:
            reverse.setdefault(target, set()).add(source)
    result = set(affected)
    pending = list(sorted(affected))
    while pending:
        current = pending.pop()
        for dependent in sorted(reverse.get(current, set())):
            if dependent not in result:
                result.add(dependent)
                pending.append(dependent)
    return result


def _source_dependencies(modules: Sequence[ScriptModule]) -> dict[str, set[str]]:
    label_paths = {label.name: label.span.path for module in modules for label in module.labels}
    result: dict[str, set[str]] = {module.path: set() for module in modules}
    for module in modules:
        for statement in _walk_statements(module.top_level):
            if isinstance(statement, (Call, Jump)) and statement.target in label_paths:
                target_path = label_paths[statement.target]
                if target_path != module.path:
                    result[module.path].add(target_path)
    return result


def _walk_statements(statements: Iterable[Statement]) -> Iterable[Statement]:
    for statement in statements:
        yield statement
        if isinstance(statement, LabelAnchor | Opaque):
            yield from _walk_statements(statement.body)
        elif isinstance(statement, If):
            for branch in statement.branches:
                yield from _walk_statements(branch.body)
        elif isinstance(statement, Menu):
            for choice in statement.choices:
                yield from _walk_statements(choice.body)


def _module_to_value(module: ScriptModule) -> dict[str, object]:
    return {
        "schema_version": 1,
        "path": module.path,
        "top_level": [_statement_to_value(item) for item in module.top_level],
        "diagnostics": module.diagnostics,
    }


def _module_from_value(raw: object) -> ScriptModule:
    value = _required_mapping(raw, "parsed source")
    if value.get("schema_version") != 1:
        raise ValueError("parsed source schema_version must be exactly 1")
    path = _required_string(value.get("path"), "parsed source path")
    top_level = [
        _statement_from_value(item)
        for item in _required_list(value.get("top_level"), "parsed source statements")
    ]
    diagnostics = [
        dict(_required_mapping(item, "parsed source diagnostic"))
        for item in _required_list(value.get("diagnostics"), "parsed source diagnostics")
    ]
    labels: list[Label] = []
    for statement in _walk_statements(top_level):
        if isinstance(statement, LabelAnchor):
            labels.append(Label(statement.name, statement.span, statement.text, statement.body))
    return ScriptModule(path, labels, top_level, diagnostics)


def _statement_to_value(statement: Statement) -> dict[str, object]:
    value: dict[str, object] = {
        "source": _span_to_value(statement.span),
        "text": statement.text,
    }
    if isinstance(statement, Simple):
        value.update({"type": "simple", "kind": statement.kind})
    elif isinstance(statement, Jump):
        value.update(
            {"type": "jump", "target": statement.target, "expression": statement.expression}
        )
    elif isinstance(statement, Call):
        value.update(
            {"type": "call", "target": statement.target, "expression": statement.expression}
        )
    elif isinstance(statement, Return):
        value.update({"type": "return", "expression": statement.expression})
    elif isinstance(statement, Opaque):
        value.update(
            {
                "type": "opaque",
                "reason": statement.reason,
                "body": [_statement_to_value(item) for item in statement.body],
            }
        )
    elif isinstance(statement, LabelAnchor):
        value.update(
            {
                "type": "label",
                "name": statement.name,
                "body": [_statement_to_value(item) for item in statement.body],
            }
        )
    elif isinstance(statement, If):
        value.update(
            {
                "type": "if",
                "branches": [
                    {
                        "condition": branch.condition,
                        "source": _span_to_value(branch.span),
                        "text": branch.text,
                        "body": [_statement_to_value(item) for item in branch.body],
                    }
                    for branch in statement.branches
                ],
            }
        )
    elif isinstance(statement, Menu):
        value.update(
            {
                "type": "menu",
                "choices": [
                    {
                        "caption": choice.caption,
                        "condition": choice.condition,
                        "source": _span_to_value(choice.span),
                        "text": choice.text,
                        "body": [_statement_to_value(item) for item in choice.body],
                    }
                    for choice in statement.choices
                ],
                "captions": [
                    {
                        "caption": caption.caption,
                        "source": _span_to_value(caption.span),
                        "text": caption.text,
                    }
                    for caption in statement.captions
                ],
            }
        )
    else:
        raise TypeError(f"unsupported parsed statement type: {type(statement).__name__}")
    return value


def _statement_from_value(raw: object) -> Statement:
    value = _required_mapping(raw, "parsed statement")
    kind = _required_string(value.get("type"), "parsed statement type")
    span = _span_from_value(value.get("source"))
    text = _required_string(value.get("text"), "parsed statement text")
    if kind == "simple":
        return Simple(span, text, _required_string(value.get("kind"), "simple kind"))
    if kind == "jump":
        return Jump(
            span,
            text,
            _optional_string(value.get("target")),
            _optional_string(value.get("expression")),
        )
    if kind == "call":
        return Call(
            span,
            text,
            _optional_string(value.get("target")),
            _optional_string(value.get("expression")),
        )
    if kind == "return":
        return Return(span, text, _optional_string(value.get("expression")))
    if kind == "opaque":
        return Opaque(
            span,
            text,
            _required_string(value.get("reason"), "opaque reason"),
            _statement_list(value.get("body")),
        )
    if kind == "label":
        return LabelAnchor(
            span,
            text,
            _required_string(value.get("name"), "label name"),
            _statement_list(value.get("body")),
        )
    if kind == "if":
        branches = []
        for raw_branch in _required_list(value.get("branches"), "if branches"):
            branch = _required_mapping(raw_branch, "if branch")
            branches.append(
                IfBranch(
                    _optional_string(branch.get("condition")),
                    _span_from_value(branch.get("source")),
                    _required_string(branch.get("text"), "if branch text"),
                    _statement_list(branch.get("body")),
                )
            )
        return If(span, text, branches)
    if kind == "menu":
        choices = []
        for raw_choice in _required_list(value.get("choices"), "menu choices"):
            choice = _required_mapping(raw_choice, "menu choice")
            choices.append(
                MenuChoice(
                    _required_string(choice.get("caption"), "choice caption"),
                    _optional_string(choice.get("condition")),
                    _span_from_value(choice.get("source")),
                    _required_string(choice.get("text"), "choice text"),
                    _statement_list(choice.get("body")),
                )
            )
        captions = []
        for raw_caption in _required_list(value.get("captions"), "menu captions"):
            caption = _required_mapping(raw_caption, "menu caption")
            captions.append(
                MenuCaption(
                    _required_string(caption.get("caption"), "menu caption text"),
                    _span_from_value(caption.get("source")),
                    _required_string(caption.get("text"), "menu caption source text"),
                )
            )
        return Menu(span, text, choices, captions)
    raise ValueError(f"unknown parsed statement type {kind!r}")


def _statement_list(raw: object) -> list[Statement]:
    return [_statement_from_value(item) for item in _required_list(raw, "statement body")]


def _span_to_value(span: SourceSpan) -> dict[str, object]:
    return {
        "path": span.path,
        "start_line": span.start_line,
        "start_column": span.start_column,
        "end_line": span.end_line,
        "end_column": span.end_column,
    }


def _span_from_value(raw: object) -> SourceSpan:
    value = _required_mapping(raw, "source span")
    return SourceSpan(
        _required_string(value.get("path"), "source span path"),
        _required_int(value.get("start_line"), "source span start_line"),
        _required_int(value.get("start_column"), "source span start_column"),
        _required_int(value.get("end_line"), "source span end_line"),
        _required_int(value.get("end_column"), "source span end_column"),
    )


def _check_cancelled(cancel_check: CancelCheck) -> None:
    if cancel_check is not None and cancel_check():
        raise ProjectOperationCancelled("project operation was cancelled")


def _required_mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{name} must be an object with string keys")
    return cast(dict[str, object], value)


def _required_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ValueError("optional string value must be a string or null")


def _required_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    return value
