"""Thin Phase 01 orchestration for the AI-first storyboard canary.

The pipeline composes one canonical evidence/profile/analysis contract. Source recovery and syntax
inventory stay in ``storyboard.evidence``, semantic interpretation stays behind
``storyboard.ai_client``, and the validator and renderer consume the same mappings that are sent to
or replayed from the AI boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from renpy_story_mapper.errors import StoryMapperError
from renpy_story_mapper.ingestion import IngestionOptions
from renpy_story_mapper.storyboard.ai_client import (
    CanonicalValidationIssue,
    CodexCliJsonClient,
    ProviderCanonicalValidationError,
    StoryboardAIError,
    StoryboardJsonClient,
)
from renpy_story_mapper.storyboard.evidence import build_evidence_index
from renpy_story_mapper.storyboard.model import EvidenceIndex, redact_public_value
from renpy_story_mapper.storyboard.prompts import (
    build_canonical_repair_request,
    build_game_profile_request,
    build_story_analysis_request,
    schema_path,
)
from renpy_story_mapper.storyboard.render import render_storyboard_html
from renpy_story_mapper.storyboard.validation import ValidationReport, validate_phase01

__all__ = [
    "ARTIFACT_FILENAMES",
    "PipelineResult",
    "StoryboardPipelineError",
    "evidence_index_to_mapping",
    "run_phase01_pipeline",
    "run_storyboard_pipeline",
]

ARTIFACT_FILENAMES = (
    "evidence-index.json",
    "game-profile.json",
    "story-analysis.json",
    "validation-report.json",
    "index.html",
)

JsonMapping = Mapping[str, object]
ReplayInput = str | os.PathLike[str] | JsonMapping


class StoryboardPipelineError(StoryMapperError):
    """An expected failure while composing the Phase 01 static canary."""


@dataclass(frozen=True)
class PipelineResult:
    """In-memory result and paths for one completed five-artifact canary."""

    output_directory: Path
    artifacts: Mapping[str, Path]
    evidence_index: Mapping[str, object]
    game_profile: Mapping[str, object]
    story_analysis: Mapping[str, object]
    validation_report: ValidationReport

    @property
    def artifact_paths(self) -> Mapping[str, Path]:
        """Compatibility name for callers that prefer an explicit path property."""

        return self.artifacts


def run_storyboard_pipeline(
    game_path: str | os.PathLike[str],
    output_directory: str | os.PathLike[str] | None = None,
    *,
    output_dir: str | os.PathLike[str] | None = None,
    source_path: str | None = None,
    label: str | None = None,
    canary_label: str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    canary_start_line: int | None = None,
    canary_end_line: int | None = None,
    profile_replay: ReplayInput | None = None,
    analysis_replay: ReplayInput | None = None,
    profile_json: ReplayInput | None = None,
    analysis_json: ReplayInput | None = None,
    ai_client: StoryboardJsonClient | None = None,
    model: str = "gpt-5.5",
    reasoning_effort: str = "high",
    fast_mode: bool = True,
    timeout_seconds: float | None = None,
    ingestion_options: IngestionOptions | None = None,
) -> PipelineResult:
    """Run one bounded, source-grounded storyboard canary.

    ``profile_replay`` and ``analysis_replay`` may each be a JSON file path or an in-memory JSON
    mapping.  When a replay is absent, one corresponding request is sent through the supplied
    provider-neutral client (or a direct :class:`CodexCliJsonClient`); one targeted repair may
    follow only when that response fails canonical schema validation.  No provider is instantiated
    when both replays are supplied.

    The input is ingested and parsed before either AI call.  The output path is checked before
    ingestion, and the relevant source files are fingerprinted before and after the run.  Only the
    five names in :data:`ARTIFACT_FILENAMES` are written.
    """

    output = _resolve_output_directory(output_directory, output_dir)
    input_path = Path(game_path).resolve(strict=True)
    _reject_output_inside_input(input_path, output)
    if output.exists():
        raise StoryboardPipelineError(
            f"output directory already exists; choose a new output directory: {output}"
        )

    selected_label = _coalesce_scope_value(label, canary_label, "label")
    selected_start = _coalesce_scope_int(start_line, canary_start_line, "start_line")
    selected_end = _coalesce_scope_int(end_line, canary_end_line, "end_line")
    _validate_line_scope(selected_start, selected_end)

    selected_profile_replay = _coalesce_replay(profile_replay, profile_json, "profile")
    selected_analysis_replay = _coalesce_replay(analysis_replay, analysis_json, "analysis")

    before = _supported_input_fingerprint(input_path)
    evidence_object = build_evidence_index(
        input_path,
        source_path=source_path,
        label=selected_label,
        start_line=selected_start,
        end_line=selected_end,
        options=ingestion_options,
    )
    after = _supported_input_fingerprint(input_path)
    if before != after:
        raise StoryboardPipelineError("supported game input changed during evidence extraction")

    evidence = evidence_index_to_mapping(evidence_object)
    raw_evidence = _copy_json_mapping(evidence, preserve_exact_text=True)
    if not evidence_object.records:
        diagnostics = raw_evidence.get("diagnostics", [])
        raise StoryboardPipelineError(
            "canary evidence is empty; choose a valid source, label, or line span "
            f"(diagnostics: {_describe_diagnostics(diagnostics)})"
        )
    evidence_hash = _sha256_artifact_json(raw_evidence)
    if (
        selected_label is None
        and selected_start is None
        and selected_end is None
        and len(evidence_object.labels) != 1
    ):
        raise StoryboardPipelineError(
            "a bounded canary label or line span is required when the selected source "
            "contains more than one label"
        )

    canary_ids = tuple(
        record_id
        for raw_record in _sequence(evidence.get("records"))
        if isinstance(raw_record, Mapping)
        for record_id in (_text(raw_record.get("id")),)
        if record_id is not None
    )
    provider: StoryboardJsonClient | None = ai_client
    if provider is None and (
        selected_profile_replay is None or selected_analysis_replay is None
    ):
        provider = _new_provider()
    profile = _load_or_request_profile(
        selected_profile_replay,
        raw_evidence,
        canary_ids,
        provider=provider,
        evidence_hash=evidence_hash,
        model=model,
        reasoning_effort=reasoning_effort,
        fast_mode=fast_mode,
        timeout_seconds=timeout_seconds,
    )
    _validate_schema_document(profile, "game-profile")
    _verify_source_hash(
        profile,
        kind="game profile",
        field="evidence_index_hash",
        expected=evidence_hash,
    )
    _verify_source_ids(
        profile,
        kind="game profile",
        field="scope_evidence_ids",
        expected=canary_ids,
    )
    profile_hash = _sha256_artifact_json(profile)
    analysis = _load_or_request_analysis(
        selected_analysis_replay,
        raw_evidence,
        profile,
        canary_ids,
        provider=provider,
        evidence_hash=evidence_hash,
        profile_hash=profile_hash,
        model=model,
        reasoning_effort=reasoning_effort,
        fast_mode=fast_mode,
        timeout_seconds=timeout_seconds,
    )
    _validate_schema_document(analysis, "story-analysis")
    _verify_source_hash(
        analysis,
        kind="story analysis",
        field="evidence_index_hash",
        expected=evidence_hash,
    )
    _verify_source_hash(
        analysis,
        kind="story analysis",
        field="profile_hash",
        expected=profile_hash,
    )
    _verify_source_ids(
        analysis,
        kind="story analysis",
        field="canary_evidence_ids",
        expected=canary_ids,
    )
    analysis_hash = _sha256_artifact_json(analysis)

    # Keep this call before rendering.  A rejected report is still rendered so the static page
    # exposes the exact deterministic findings instead of disappearing behind a failed command.
    validation_report = validate_phase01(evidence, profile, analysis)
    report_mapping = validation_report.to_dict()
    provenance = _artifact_provenance(evidence_hash, profile_hash, analysis_hash)
    report_mapping["provenance"] = provenance
    html = render_storyboard_html(evidence, profile, analysis, report_mapping)
    html_provenance = dict(provenance)
    html_provenance["validation_report_hash"] = _sha256_artifact_json(report_mapping)
    html = _add_html_provenance(html, html_provenance)

    if _supported_input_fingerprint(input_path) != before:
        raise StoryboardPipelineError("supported game input changed before artifact writing")

    staging: Path | None = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent)
        ).resolve()
        staged_artifacts = {name: staging / name for name in ARTIFACT_FILENAMES}
        _write_json(staged_artifacts["evidence-index.json"], raw_evidence)
        _write_json(staged_artifacts["game-profile.json"], profile)
        _write_json(staged_artifacts["story-analysis.json"], analysis)
        _write_json(staged_artifacts["validation-report.json"], report_mapping)
        _write_text(staged_artifacts["index.html"], html)
        staging.replace(output)
        staging = None
    except StoryboardPipelineError:
        raise
    except OSError as error:
        raise StoryboardPipelineError(f"could not publish output directory: {output}") from error
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)

    artifacts = {name: output / name for name in ARTIFACT_FILENAMES}

    return PipelineResult(
        output.resolve(),
        {name: path.resolve() for name, path in artifacts.items()},
        raw_evidence,
        profile,
        analysis,
        validation_report,
    )


def run_phase01_pipeline(
    game_path: str | os.PathLike[str],
    output_directory: str | os.PathLike[str] | None = None,
    **kwargs: object,
) -> PipelineResult:
    """Compatibility entry point named after the active milestone phase."""

    return run_storyboard_pipeline(game_path, output_directory, **kwargs)  # type: ignore[arg-type]


def evidence_index_to_mapping(index: EvidenceIndex) -> dict[str, object]:
    """Return the one canonical JSON contract used by every storyboard phase."""

    return _copy_json_mapping(index.to_dict(), preserve_exact_text=True)


def _load_or_request_profile(
    replay: ReplayInput | None,
    evidence: Mapping[str, object],
    canary_ids: Sequence[str],
    *,
    provider: StoryboardJsonClient | None,
    evidence_hash: str,
    model: str,
    reasoning_effort: str,
    fast_mode: bool,
    timeout_seconds: float | None,
) -> dict[str, object]:
    if replay is not None:
        return _read_replay(replay, "profile")
    provider = provider or _new_provider()
    payload = build_game_profile_request(evidence_index=_copy_json_mapping(evidence))
    payload["required_provenance"] = {"evidence_index_hash": evidence_hash}
    profile = _complete(
        provider,
        payload,
        "game-profile",
        model=model,
        reasoning_effort=reasoning_effort,
        fast_mode=fast_mode,
        timeout_seconds=timeout_seconds,
    )
    return _bind_deterministic_source(
        profile,
        {
            "evidence_index_hash": evidence_hash,
            "scope_evidence_ids": list(canary_ids),
        },
    )


def _load_or_request_analysis(
    replay: ReplayInput | None,
    evidence: Mapping[str, object],
    profile: Mapping[str, object],
    canary_ids: Sequence[str],
    *,
    provider: StoryboardJsonClient | None,
    evidence_hash: str,
    profile_hash: str,
    model: str,
    reasoning_effort: str,
    fast_mode: bool,
    timeout_seconds: float | None,
) -> dict[str, object]:
    if replay is not None:
        return _read_replay(replay, "analysis")
    provider = provider or _new_provider()
    payload = build_story_analysis_request(
        evidence_index=_copy_json_mapping(evidence),
        game_profile=_copy_json_mapping(profile),
        canary_evidence_ids=canary_ids,
    )
    payload["required_provenance"] = {
        "evidence_index_hash": evidence_hash,
        "profile_hash": profile_hash,
    }
    analysis = _complete(
        provider,
        payload,
        "story-analysis",
        model=model,
        reasoning_effort=reasoning_effort,
        fast_mode=fast_mode,
        timeout_seconds=timeout_seconds,
    )
    return _bind_deterministic_source(
        analysis,
        {
            "evidence_index_hash": evidence_hash,
            "profile_hash": profile_hash,
            "canary_evidence_ids": list(canary_ids),
        },
    )


def _bind_deterministic_source(
    document: Mapping[str, object], source: Mapping[str, object]
) -> dict[str, object]:
    """Attach caller-owned provenance without changing AI semantic fields."""

    bound = _copy_json_mapping(document)
    bound["source"] = _copy_json_mapping(source)
    return bound


def _complete(
    provider: StoryboardJsonClient,
    payload: Mapping[str, object],
    kind: str,
    *,
    model: str,
    reasoning_effort: str,
    fast_mode: bool,
    timeout_seconds: float | None,
) -> dict[str, object]:
    value, issues = _complete_once(
        provider,
        payload,
        kind,
        model=model,
        reasoning_effort=reasoning_effort,
        fast_mode=fast_mode,
        timeout_seconds=timeout_seconds,
        repair=False,
    )
    if not issues:
        return value

    repair_payload = build_canonical_repair_request(
        kind=kind,
        prior_response=value,
        validator_issues=[
            {"path": list(issue.path), "message": issue.message} for issue in issues
        ],
    )
    required_provenance = payload.get("required_provenance")
    if isinstance(required_provenance, Mapping):
        repair_payload["required_provenance"] = _copy_json_mapping(required_provenance)
    repaired, repair_issues = _complete_once(
        provider,
        repair_payload,
        kind,
        model=model,
        reasoning_effort=reasoning_effort,
        fast_mode=fast_mode,
        timeout_seconds=timeout_seconds,
        repair=True,
    )
    if repair_issues:
        details = _format_validation_issues(repair_issues)
        raise StoryboardPipelineError(
            f"storyboard AI {kind} response still does not match the bundled schema after one "
            f"targeted repair: {details}"
        )
    return repaired


def _complete_once(
    provider: StoryboardJsonClient,
    payload: Mapping[str, object],
    kind: str,
    *,
    model: str,
    reasoning_effort: str,
    fast_mode: bool,
    timeout_seconds: float | None,
    repair: bool,
) -> tuple[dict[str, object], tuple[CanonicalValidationIssue, ...]]:
    try:
        value = provider.complete(
            payload=payload,
            schema_path=schema_path(kind),
            model=model,
            reasoning_effort=reasoning_effort,
            fast_mode=fast_mode,
            timeout_seconds=timeout_seconds,
        )
    except ProviderCanonicalValidationError as error:
        copied = _copy_json_mapping(error.response)
        return copied, _canonical_validation_issues(copied, kind)
    except StoryboardAIError as error:
        diagnostic = (
            f"; private diagnostic: {error.diagnostic_path}"
            if error.diagnostic_path is not None
            else ""
        )
        request_kind = f"{kind} repair" if repair else kind
        raise StoryboardPipelineError(
            f"storyboard AI {request_kind} request failed ({error.error_code}): "
            f"{error}{diagnostic}"
        ) from error
    if not isinstance(value, Mapping):
        request_kind = f"{kind} repair" if repair else kind
        raise StoryboardPipelineError(
            f"storyboard AI {request_kind} response must be a JSON object"
        )
    copied = _copy_json_mapping(value)
    return copied, _canonical_validation_issues(copied, kind)


def _canonical_validation_issues(
    value: Mapping[str, object],
    kind: str,
) -> tuple[CanonicalValidationIssue, ...]:
    try:
        schema = json.loads(schema_path(kind).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StoryboardPipelineError(f"could not load bundled {kind} schema") from error
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    return tuple(
        CanonicalValidationIssue(
            tuple(
                part if isinstance(part, int) and not isinstance(part, bool) else str(part)
                for part in error.absolute_path
            ),
            " ".join(error.message.split())[:500],
        )
        for error in errors[:5]
    )


def _format_validation_issues(issues: Sequence[CanonicalValidationIssue]) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in issue.path) or '$'}: {issue.message}"
        for issue in issues
    )


def _validate_schema_document(value: Mapping[str, object], kind: str) -> None:
    if not value:
        raise StoryboardPipelineError(f"storyboard AI {kind} response is empty")
    try:
        schema = json.loads(schema_path(kind).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StoryboardPipelineError(f"could not load bundled {kind} schema") from error
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(value),
        key=lambda item: tuple(str(part) for part in item.path),
    )
    if errors:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error.path) or '$'}: {error.message}"
            for error in errors[:5]
        )
        raise StoryboardPipelineError(
            f"storyboard AI {kind} response does not match the bundled schema: {details}"
        )


def _verify_source_hash(
    document: Mapping[str, object], *, kind: str, field: str, expected: str
) -> None:
    source = document.get("source")
    actual = source.get(field) if isinstance(source, Mapping) else None
    if actual != expected:
        raise StoryboardPipelineError(
            f"{kind} source.{field} does not match the frozen source hash "
            f"(expected {expected}, received {actual!r})"
        )


def _verify_source_ids(
    document: Mapping[str, object],
    *,
    kind: str,
    field: str,
    expected: Sequence[str],
) -> None:
    source = document.get("source")
    actual = _ids(source.get(field)) if isinstance(source, Mapping) else []
    expected_set = set(expected)
    actual_set = set(actual)
    if actual_set == expected_set and len(actual) == len(expected):
        return
    missing = sorted(expected_set - actual_set)
    extra = sorted(actual_set - expected_set)
    raise StoryboardPipelineError(
        f"{kind} source.{field} does not match the complete canary evidence scope "
        f"(missing {missing!r}, extra {extra!r})"
    )


def _artifact_provenance(
    evidence_hash: str, profile_hash: str, analysis_hash: str
) -> dict[str, object]:
    return {
        "hash_algorithm": "sha256",
        "hash_basis": "serialized artifact bytes",
        "serialization": "UTF-8 JSON with sorted keys, two-space indentation, and trailing newline",
        "evidence_index_hash": evidence_hash,
        "game_profile_hash": profile_hash,
        "story_analysis_hash": analysis_hash,
    }


def _add_html_provenance(html: str, provenance: Mapping[str, object]) -> str:
    names = (
        ("evidence-index", "evidence_index_hash"),
        ("game-profile", "game_profile_hash"),
        ("story-analysis", "story_analysis_hash"),
        ("validation-report", "validation_report_hash"),
    )
    tags = [
        '<meta name="storyboard-provenance-algorithm" content="sha256">',
        '<meta name="storyboard-provenance-serialization" '
        'content="utf8-json-sorted-keys-indent-2-trailing-newline">',
    ]
    for artifact, key in names:
        value = _text(provenance.get(key))
        if value is not None:
            tags.append(
                f'<meta name="storyboard-{artifact}-hash" content="{value}">'
            )
    marker = '<meta charset="utf-8">\n'
    metadata = "\n".join(tags) + "\n"
    if marker in html:
        return html.replace(marker, marker + metadata, 1)
    return html.replace("<head>\n", "<head>\n" + metadata, 1)


def _new_provider() -> StoryboardJsonClient:
    return CodexCliJsonClient()


def _read_replay(
    replay: ReplayInput,
    kind: str,
) -> dict[str, object]:
    if isinstance(replay, Mapping):
        value = _copy_json_mapping(replay)
    else:
        path = Path(replay)
        try:
            text = path.read_text(encoding="utf-8")
            loaded = json.loads(text, parse_constant=_reject_json_constant)
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
            raise StoryboardPipelineError(f"could not read {kind} replay JSON: {path}") from error
        if not isinstance(loaded, Mapping):
            raise StoryboardPipelineError(f"{kind} replay JSON must contain an object: {path}")
        value = _copy_json_mapping(loaded)
    legacy_envelope_keys = (
        ("profile", "game_profile") if kind == "profile" else ("analysis", "story_analysis")
    )
    if any(key in value for key in legacy_envelope_keys):
        raise StoryboardPipelineError(
            f"{kind} replay uses a legacy envelope; supply the canonical document directly"
        )
    return value


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _copy_json_mapping(value: object, *, preserve_exact_text: bool = False) -> dict[str, object]:
    copied = _copy_json(value, preserve_exact_text=preserve_exact_text)
    if not isinstance(copied, dict):
        raise StoryboardPipelineError("storyboard JSON value must be an object")
    return copied


def _copy_json(value: object, *, preserve_exact_text: bool = False) -> object:
    return redact_public_value(value, preserve_exact_text=preserve_exact_text)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _ids(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Mapping):
        for key in ("evidence_id", "source_evidence_id", "id", "reference_id"):
            identifier = _text(value.get(key))
            if identifier is not None:
                return [identifier]
        for key in ("evidence_ids", "source_evidence_ids", "items"):
            if key in value:
                return _ids(value.get(key))
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        result: list[str] = []
        for item in value:
            result.extend(_ids(item))
        return result
    return []


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_artifact_json(value: object) -> str:
    return hashlib.sha256(_artifact_json_text(value).encode("utf-8")).hexdigest()


def _artifact_json_text(value: object) -> str:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        )
    except (TypeError, ValueError) as error:
        raise StoryboardPipelineError("artifact is not finite JSON") from error


def _write_json(path: Path, value: object) -> None:
    try:
        content = _artifact_json_text(value)
    except StoryboardPipelineError as error:
        raise StoryboardPipelineError(f"artifact is not finite JSON: {path.name}") from error
    _write_text(path, content)


def _write_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        temporary.replace(path)
    except OSError as error:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise StoryboardPipelineError(f"could not write artifact: {path}") from error


def _resolve_output_directory(
    output_directory: str | os.PathLike[str] | None,
    output_dir: str | os.PathLike[str] | None,
) -> Path:
    if output_directory is None:
        output_directory = output_dir
    elif output_dir is not None and Path(output_directory).resolve() != Path(output_dir).resolve():
        raise StoryboardPipelineError("output_directory and output_dir disagree")
    if output_directory is None:
        raise StoryboardPipelineError("an output directory is required")
    return Path(output_directory).resolve(strict=False)


def _reject_output_inside_input(input_path: Path, output: Path) -> None:
    protected_root = input_path if input_path.is_dir() else input_path.parent
    try:
        output.relative_to(protected_root)
    except ValueError:
        return
    raise StoryboardPipelineError("output directory must be outside the selected game input")


def _coalesce_scope_value(first: str | None, second: str | None, name: str) -> str | None:
    if first is not None and second is not None and first != second:
        raise StoryboardPipelineError(f"{name} and canary_{name} disagree")
    return first if first is not None else second


def _coalesce_scope_int(first: int | None, second: int | None, name: str) -> int | None:
    if first is not None and second is not None and first != second:
        raise StoryboardPipelineError(f"{name} and canary_{name} disagree")
    return first if first is not None else second


def _coalesce_replay(
    first: ReplayInput | None, second: ReplayInput | None, name: str
) -> ReplayInput | None:
    if first is not None and second is not None:
        if isinstance(first, Mapping) or isinstance(second, Mapping):
            raise StoryboardPipelineError(f"{name} replay was supplied more than once")
        if Path(first).resolve() != Path(second).resolve():
            raise StoryboardPipelineError(f"{name} replay was supplied more than once")
    return first if first is not None else second


def _validate_line_scope(start_line: int | None, end_line: int | None) -> None:
    for name, value in (("start_line", start_line), ("end_line", end_line)):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise StoryboardPipelineError(f"{name} must be a positive integer")
    if start_line is not None and end_line is not None and start_line > end_line:
        raise StoryboardPipelineError("start_line must not exceed end_line")


def _supported_input_fingerprint(path: Path) -> tuple[tuple[str, int, str], ...]:
    if path.is_file():
        return (_file_fingerprint(path, path.name),)
    if not path.is_dir():
        return ()
    files = [
        item
        for item in path.rglob("*")
        if item.is_file() and item.suffix.casefold() in {".rpy", ".rpyc", ".rpa"}
    ]
    return tuple(
        _file_fingerprint(item, item.relative_to(path).as_posix())
        for item in sorted(files, key=lambda item: item.as_posix().casefold())
    )


def _file_fingerprint(path: Path, relative: str) -> tuple[str, int, str]:
    content = path.read_bytes()
    return relative.replace("\\", "/"), len(content), hashlib.sha256(content).hexdigest()


def _describe_diagnostics(value: object) -> str:
    messages: list[str] = []
    for item in _sequence(value):
        if isinstance(item, Mapping):
            message = _text(item.get("message"))
            if message:
                messages.append(message)
        elif isinstance(item, str):
            messages.append(item)
    return "; ".join(messages[:5]) or "no parser diagnostics"


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant {value!r}")
