"""Thin Phase 01 orchestration for the AI-first storyboard canary.

The pipeline deliberately owns only composition.  Source recovery and syntax inventory stay in
``storyboard.evidence``, semantic interpretation stays behind ``storyboard.ai_client``, and the
deterministic audit and HTML renderer remain independently testable.  The two small compatibility
projections in this module bridge the strict AI response shape (top-level choices) to the older
mapping shape accepted by the already-present validator and renderer without changing either
component or changing the AI artifact written to disk.
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
from typing import cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from renpy_story_mapper.errors import StoryMapperError
from renpy_story_mapper.ingestion import IngestionOptions
from renpy_story_mapper.storyboard.ai_client import (
    CodexCliJsonClient,
    StoryboardAIError,
    StoryboardJsonClient,
)
from renpy_story_mapper.storyboard.evidence import build_evidence_index
from renpy_story_mapper.storyboard.model import EvidenceIndex, EvidenceKind
from renpy_story_mapper.storyboard.prompts import (
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
    mapping.  When a replay is absent, exactly one corresponding request is sent through the
    supplied provider-neutral client (or a direct :class:`CodexCliJsonClient`).  No provider is
    instantiated when both replays are supplied.

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

    raw_evidence = _copy_json_mapping(evidence_object.to_dict())
    if not evidence_object.records:
        diagnostics = raw_evidence.get("diagnostics", [])
        raise StoryboardPipelineError(
            "canary evidence is empty; choose a valid source, label, or line span "
            f"(diagnostics: {_describe_diagnostics(diagnostics)})"
        )
    evidence = evidence_index_to_mapping(evidence_object)
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
        for record_id in cast(Sequence[object], evidence["accountable_evidence_ids"])
        if isinstance(record_id, str)
    )
    provider: StoryboardJsonClient | None = ai_client
    if provider is None and (
        selected_profile_replay is None or selected_analysis_replay is None
    ):
        provider = _new_provider()
    profile = _load_or_request_profile(
        selected_profile_replay,
        raw_evidence,
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

    validation_profile = _validation_profile(profile, evidence)
    validation_analysis = _validation_analysis(analysis, evidence)
    # Keep this call before rendering.  A rejected report is still rendered so the static page
    # exposes the exact deterministic findings instead of disappearing behind a failed command.
    validation_report = validate_phase01(evidence, validation_profile, validation_analysis)
    report_mapping = validation_report.to_dict()
    provenance = _artifact_provenance(evidence_hash, profile_hash, analysis_hash)
    report_mapping["provenance"] = provenance
    render_analysis = _presentation_analysis(analysis, evidence)
    html = render_storyboard_html(evidence, profile, render_analysis, report_mapping)
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
    """Serialize an :class:`EvidenceIndex` into the canonical Phase 01 JSON mapping.

    The original dataclass representation remains intact, including its exact ``text`` field and
    nested provenance.  The additional aliases make the seam explicit for the validator, renderer,
    and AI prompt: menu arm ownership is represented by ``menus[*].arm_ids`` and record facts are
    available under ``facts`` rather than being accidentally hidden in ``metadata``.
    """

    raw = _copy_json_mapping(index.to_dict())
    raw_records = _sequence(raw.get("records"))
    records: list[dict[str, object]] = []
    for raw_record in raw_records:
        if not isinstance(raw_record, Mapping):
            continue
        record = dict(raw_record)
        metadata = _copy_json_mapping(record.get("metadata", {}))
        record_id = _text(record.get("id"))
        if record_id is None:
            continue
        source_text = record.get("text")
        record["source_text"] = source_text
        record["metadata"] = metadata
        record["facts"] = dict(metadata)
        record["accountable"] = True
        records.append(record)

    records_by_id = {
        record_id: record
        for record in records
        if (record_id := _text(record.get("id"))) is not None
    }
    menus: list[dict[str, object]] = []
    for record in records:
        if _text(record.get("kind")) != EvidenceKind.MENU.value:
            continue
        menu_id = _text(record.get("id"))
        if menu_id is None:
            continue
        arm_ids = [
            arm_id
            for arm_id, arm in records_by_id.items()
            if _text(arm.get("kind")) == EvidenceKind.CHOICE_ARM.value
            and _text(_facts(arm).get("parent_id")) == menu_id
        ]
        arm_ids.sort(key=lambda item: _record_order(records_by_id[item]))
        menu_value: dict[str, object] = {
            "id": menu_id,
            "arm_ids": arm_ids,
            "caption_ids": [
                caption_id
                for caption_id, caption in records_by_id.items()
                if _text(caption.get("kind")) == EvidenceKind.MENU_CAPTION.value
                and _text(_facts(caption).get("parent_id")) == menu_id
            ],
        }
        menus.append(menu_value)

        menu_facts = dict(_facts(record))
        menu_facts["arm_ids"] = list(arm_ids)
        record["facts"] = menu_facts
        record["metadata"] = dict(menu_facts)

    menus.sort(key=lambda item: _record_order(records_by_id[_text(item["id"]) or ""]))
    accountable_ids = [
        _text(record.get("id")) for record in records if _text(record.get("id")) is not None
    ]
    accountable_ids = [cast(str, item) for item in accountable_ids]

    canonical = dict(raw)
    canonical.update(
        {
            "schema_version": "storyboard-evidence-v1",
            "records": records,
            "menus": menus,
            "accountable_evidence_ids": accountable_ids,
            "labels": [
                record_id
                for record_id, record in records_by_id.items()
                if _text(record.get("kind")) == EvidenceKind.LABEL.value
            ],
            "choice_arms": [
                record_id
                for record_id, record in records_by_id.items()
                if _text(record.get("kind")) == EvidenceKind.CHOICE_ARM.value
            ],
            "conditions": [
                record_id
                for record_id, record in records_by_id.items()
                if _text(record.get("kind")) == EvidenceKind.CONDITION.value
            ],
            "assignments": [
                record_id
                for record_id, record in records_by_id.items()
                if _text(record.get("kind")) == EvidenceKind.ASSIGNMENT.value
            ],
            "diagnostics": list(_sequence(raw.get("diagnostics"))),
        }
    )
    revision_payload = dict(canonical)
    revision_payload.pop("revision", None)
    canonical["revision"] = "idx-" + _sha256_json(revision_payload)
    return canonical


def _load_or_request_profile(
    replay: ReplayInput | None,
    evidence: Mapping[str, object],
    *,
    provider: StoryboardJsonClient | None,
    evidence_hash: str,
    model: str,
    reasoning_effort: str,
    fast_mode: bool,
    timeout_seconds: float | None,
) -> dict[str, object]:
    if replay is not None:
        return _read_replay(replay, "profile", ("profile", "game_profile"))
    provider = provider or _new_provider()
    payload = build_game_profile_request(evidence_index=_copy_json_mapping(evidence))
    payload["required_provenance"] = {"evidence_index_hash": evidence_hash}
    return _complete(
        provider,
        payload,
        "game-profile",
        model=model,
        reasoning_effort=reasoning_effort,
        fast_mode=fast_mode,
        timeout_seconds=timeout_seconds,
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
        return _read_replay(replay, "analysis", ("analysis", "story_analysis"))
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
    return _complete(
        provider,
        payload,
        "story-analysis",
        model=model,
        reasoning_effort=reasoning_effort,
        fast_mode=fast_mode,
        timeout_seconds=timeout_seconds,
    )


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
    try:
        value = provider.complete(
            payload=payload,
            schema_path=schema_path(kind),
            model=model,
            reasoning_effort=reasoning_effort,
            fast_mode=fast_mode,
            timeout_seconds=timeout_seconds,
        )
    except StoryboardAIError as error:
        raise StoryboardPipelineError(
            f"storyboard AI {kind} request failed ({error.error_code}): {error}"
        ) from error
    if not isinstance(value, Mapping):
        raise StoryboardPipelineError(f"storyboard AI {kind} response must be a JSON object")
    return _copy_json_mapping(value)


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
    wrapper_keys: Sequence[str],
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
    for key in wrapper_keys:
        nested = value.get(key)
        if isinstance(nested, Mapping) and "schema" not in value:
            return _copy_json_mapping(nested)
    return value


def _validation_profile(
    profile: Mapping[str, object], evidence: Mapping[str, object]
) -> dict[str, object]:
    value = _copy_json_mapping(profile)
    value.setdefault("source_revision", _text(evidence.get("revision")) or "")
    _normalize_claim_metadata(value)
    value["disagreements"] = _compat_disagreements(value.get("disagreements"))
    return value


def _validation_analysis(
    analysis: Mapping[str, object], evidence: Mapping[str, object]
) -> dict[str, object]:
    value = _presentation_analysis(analysis, evidence)
    _flatten_validation_choices(value, evidence)
    value.setdefault("source_revision", _text(evidence.get("revision")) or "")
    _normalize_claim_metadata(value)
    value["disagreements"] = _compat_disagreements(value.get("disagreements"))

    exclusions = _sequence(value.get("exclusions"))
    excluded_ids = _ids(value.get("excluded_evidence_ids"))
    if not exclusions and excluded_ids:
        value["exclusions"] = [
            {
                "evidence_id": evidence_id,
                "reason": "AI analysis excluded this source record",
                "unresolved": True,
                "uncertainty": "The exclusion needs human review before the source can be omitted.",
                "evidence_ids": [evidence_id],
                "confidence": "low",
            }
            for evidence_id in excluded_ids
        ]

    scenes = value.get("scenes")
    if isinstance(scenes, Sequence) and not isinstance(scenes, (str, bytes, bytearray)):
        for raw_scene in scenes:
            if not isinstance(raw_scene, dict):
                continue
            if "member_evidence_ids" not in raw_scene:
                member_ids: list[str] = []
                member_ids.extend(_ids(raw_scene.get("evidence_ids")))
                member_ids.extend(_ids(raw_scene.get("line_evidence_ids")))
                for raw_choice in _sequence(raw_scene.get("choices")):
                    if not isinstance(raw_choice, Mapping):
                        continue
                    member_ids.extend(_ids(raw_choice.get("evidence_ids")))
                    member_ids.extend(_ids(raw_choice.get("menu_evidence_id")))
                    member_ids.extend(_ids(raw_choice.get("arm_evidence_id")))
                    for raw_arm in _sequence(raw_choice.get("arms")):
                        if isinstance(raw_arm, Mapping):
                            member_ids.extend(_ids(raw_arm.get("evidence_ids")))
                raw_scene["member_evidence_ids"] = _unique(member_ids)
            # A strict-schema scene may have a semantic evidence list but no old-style lines.
            # Keep unknown IDs in the compatibility view so deterministic validation reports them.
    return value


def _flatten_validation_choices(
    value: dict[str, object], evidence: Mapping[str, object]
) -> None:
    """Present each strict-schema arm as one choice row to the existing validator."""

    scenes = value.get("scenes")
    if not isinstance(scenes, list):
        return
    for raw_scene in scenes:
        if not isinstance(raw_scene, dict):
            continue
        flattened: list[dict[str, object]] = []
        for raw_choice in _sequence(raw_scene.get("choices")):
            if not isinstance(raw_choice, Mapping):
                continue
            if "arm_evidence_id" in raw_choice:
                flattened.append(_copy_json_mapping(raw_choice))
                continue
            menu_id = _text(raw_choice.get("menu_evidence_id", raw_choice.get("menu_id")))
            choice_ids = _ids(raw_choice.get("evidence_ids"))
            arms = _sequence(raw_choice.get("arms"))
            if not arms:
                flattened.append(_copy_json_mapping(raw_choice))
                continue
            for raw_arm in arms:
                if not isinstance(raw_arm, Mapping):
                    continue
                arm_ids = _ids(raw_arm.get("evidence_ids"))
                arm_id = _text(raw_arm.get("arm_evidence_id")) or _first_kind(
                    arm_ids, _record_lookup(evidence), EvidenceKind.CHOICE_ARM.value
                )
                flat: dict[str, object] = {
                    "menu_evidence_id": menu_id,
                    "arm_evidence_id": arm_id,
                    "evidence_ids": _unique([*choice_ids, *arm_ids]),
                }
                for key in (
                    "consequence",
                    "destination",
                    "confidence",
                    "unresolved",
                    "uncertainty",
                ):
                    if key in raw_arm:
                        flat[key] = _copy_json(raw_arm[key])
                flattened.append(flat)
        raw_scene["choices"] = flattened


def _presentation_analysis(
    analysis: Mapping[str, object], evidence: Mapping[str, object]
) -> dict[str, object]:
    value = _copy_json_mapping(analysis)
    records = _record_lookup(evidence)
    raw_scenes = value.get("scenes")
    if not isinstance(raw_scenes, list):
        return value

    raw_choices = value.get("choices")
    strict_choices = [
        item
        for item in _sequence(raw_choices)
        if isinstance(item, Mapping) and "menu_evidence_id" not in item
    ]
    choices_by_scene: dict[str, list[dict[str, object]]] = {}
    menus_by_scene: dict[str, list[dict[str, object]]] = {}
    unmatched_menus: list[dict[str, object]] = []
    for raw_choice in strict_choices:
        choice = _compat_choice(raw_choice, records)
        scene_id = _text(raw_choice.get("scene_id")) or ""
        choices_by_scene.setdefault(scene_id, []).append(choice)
        menu_id = _text(choice.get("menu_evidence_id"))
        menu: dict[str, object] = {
            "id": _text(raw_choice.get("id")) or f"menu-{len(unmatched_menus)}",
            "title": _text(raw_choice.get("caption")) or "Choice",
            "evidence_id": menu_id,
            "evidence_ids": _ids(raw_choice.get("evidence_ids")),
            "arms": list(_sequence(choice.get("arms"))),
        }
        if menu_id is None:
            unmatched_menus.append(menu)
        else:
            menus_by_scene.setdefault(scene_id, []).append(menu)

    for raw_scene in raw_scenes:
        if not isinstance(raw_scene, dict):
            continue
        scene_id = _text(raw_scene.get("id")) or ""
        if strict_choices and "choices" not in raw_scene:
            raw_scene["choices"] = choices_by_scene.get(scene_id, [])
        if strict_choices and "menus" not in raw_scene:
            raw_scene["menus"] = menus_by_scene.get(scene_id, [])
        if "menus" not in raw_scene:
            raw_scene["menus"] = _legacy_scene_menus(raw_scene, records)
        if "branches" not in raw_scene:
            raw_scene["branches"] = _scene_transition_branches(raw_scene, value)
    if unmatched_menus:
        value["menus"] = list(_sequence(value.get("menus"))) + unmatched_menus
    return value


def _scene_transition_branches(
    scene: Mapping[str, object], analysis: Mapping[str, object]
) -> list[dict[str, object]]:
    scene_id = _text(scene.get("id"))
    if scene_id is None:
        return []
    result: list[dict[str, object]] = []
    for raw_transition in _sequence(analysis.get("transitions")):
        if not isinstance(raw_transition, Mapping):
            continue
        if _text(raw_transition.get("from_id")) != scene_id:
            continue
        target = _text(raw_transition.get("to_id"))
        result.append(
            {
                "title": _text(raw_transition.get("kind")) or "Transition",
                "destination": target or "unresolved destination",
                "evidence_ids": _ids(raw_transition.get("evidence_ids")),
                "confidence": _text(raw_transition.get("confidence")) or "low",
                "unresolved": raw_transition.get("unresolved", False),
            }
        )
    return result


def _legacy_scene_menus(
    scene: Mapping[str, object], records: Mapping[str, Mapping[str, object]]
) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for raw_choice in _sequence(scene.get("choices")):
        if not isinstance(raw_choice, Mapping):
            continue
        menu_id = _text(raw_choice.get("menu_evidence_id", raw_choice.get("menu_id")))
        arm_id = _text(raw_choice.get("arm_evidence_id", raw_choice.get("arm_id")))
        if menu_id is None:
            continue
        menu = grouped.setdefault(
            menu_id,
            {
                "id": menu_id,
                "title": "Choice",
                "evidence_id": menu_id,
                "evidence_ids": [menu_id],
                "arms": [],
            },
        )
        facts = _facts(records.get(arm_id)) if arm_id is not None else {}
        choice_evidence_ids = [arm_id] if arm_id is not None else []
        choice_evidence_ids.extend(_ids(raw_choice.get("evidence_ids")))
        arm: dict[str, object] = {
            "id": arm_id,
            "caption": _text(raw_choice.get("caption"))
            or _text(facts.get("caption"))
            or "Choice arm",
            "condition": raw_choice.get("condition", facts.get("condition")),
            "consequence": _copy_json(raw_choice.get("consequence")),
            "destination": _copy_json(raw_choice.get("destination")),
            "rejoin": _copy_json(raw_choice.get("rejoin")),
            "terminal": _copy_json(raw_choice.get("terminal")),
            "evidence_ids": _unique([menu_id, *choice_evidence_ids]),
        }
        arms = menu["arms"]
        if isinstance(arms, list):
            arms.append(arm)
    return list(grouped.values())


def _compat_choice(
    raw_choice: Mapping[str, object], records: Mapping[str, Mapping[str, object]]
) -> dict[str, object]:
    if "menu_evidence_id" in raw_choice or "menu_id" in raw_choice:
        return _copy_json_mapping(raw_choice)

    choice_ids = _ids(raw_choice.get("evidence_ids"))
    arms: list[dict[str, object]] = []
    menu_id = _first_kind(choice_ids, records, EvidenceKind.MENU.value)
    for raw_arm in _sequence(raw_choice.get("arms")):
        if not isinstance(raw_arm, Mapping):
            continue
        arm_ids = _ids(raw_arm.get("evidence_ids"))
        arm_id = _first_kind(arm_ids, records, EvidenceKind.CHOICE_ARM.value)
        arm_id = arm_id or _text(raw_arm.get("id"))
        if arm_id is not None and arm_id in records:
            parent_id = _text(_facts(records[arm_id]).get("parent_id"))
            if menu_id is None and parent_id in records:
                menu_id = parent_id
        combined_ids = _unique(arm_ids + _ids(raw_arm.get("line_evidence_ids")))
        facts = _facts(records.get(arm_id)) if arm_id is not None else {}
        condition = raw_arm.get("condition", facts.get("condition"))
        arm_value: dict[str, object] = {
            "id": _text(raw_arm.get("id")) or arm_id,
            "caption": _text(raw_arm.get("caption")) or _text(facts.get("caption")) or "Choice arm",
            "condition": condition,
            "consequence": _compat_consequence(raw_arm, combined_ids),
            "evidence_ids": combined_ids,
            "confidence": _text(raw_arm.get("confidence")) or "low",
            "unresolved": raw_arm.get("unresolved", False),
        }
        destination_id = raw_arm.get("destination_id")
        if destination_id is not None:
            destination_text = _text(destination_id)
            target = records.get(destination_text or "")
            if target is not None:
                target_kind = _text(target.get("kind"))
                destination_kind = (
                    "label" if target_kind == EvidenceKind.LABEL.value else "unresolved"
                )
                if destination_kind == "label":
                    arm_value["destination"] = {
                        "kind": "label",
                        "target_evidence_id": destination_text,
                        "evidence_ids": _unique([*combined_ids, destination_text or ""]),
                        "confidence": _text(raw_arm.get("confidence")) or "low",
                        "unresolved": False,
                    }
                else:
                    arm_value["destination"] = _unresolved_destination(
                        destination_text, combined_ids
                    )
            else:
                arm_value["destination"] = _unresolved_destination(
                    destination_text, combined_ids
                )
        else:
            arm_value["destination"] = _unresolved_destination(None, combined_ids)
        rejoin_id = _text(raw_arm.get("rejoin_id"))
        if rejoin_id is not None:
            arm_value["rejoin"] = rejoin_id
        terminal = _text(raw_arm.get("terminal"))
        if terminal not in {None, "none"}:
            arm_value["terminal"] = terminal
        arms.append(arm_value)

    value: dict[str, object] = _copy_json_mapping(raw_choice)
    value["menu_evidence_id"] = menu_id
    value["arms"] = arms
    if menu_id is None:
        value["menu_id"] = None
    return value


def _compat_consequence(arm: Mapping[str, object], evidence_ids: Sequence[str]) -> object:
    consequence = arm.get("consequence")
    if isinstance(consequence, Mapping):
        return _copy_json_mapping(consequence)
    text = _text(consequence)
    if text is None:
        return None
    return {
        "text": text,
        "evidence_ids": list(evidence_ids) or ["unresolved-consequence"],
        "confidence": _text(arm.get("confidence")) or "low",
        "unresolved": _unresolved_flag(arm.get("unresolved")),
        "uncertainty": _uncertainty_text(arm.get("unresolved")),
    }


def _unresolved_destination(
    destination_id: str | None, evidence_ids: Sequence[str]
) -> dict[str, object]:
    label = destination_id or "no concrete destination"
    return {
        "kind": "unresolved",
        "label": label,
        "evidence_ids": list(evidence_ids),
        "confidence": "low",
        "unresolved": True,
        "uncertainty": (
            f"The analysis names {label!r}, but the selected evidence does not establish a "
            "concrete destination record."
        ),
    }


def _compat_disagreements(value: object) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for raw in _sequence(value):
        if not isinstance(raw, Mapping):
            continue
        if "parser" in raw or "parser_observation" in raw:
            result.append(_copy_json_mapping(raw))
            continue
        evidence_ids = _ids(raw.get("deterministic_evidence_ids"))
        unresolved = raw.get("unresolved")
        result.append(
            {
                "id": _text(raw.get("id")) or "disagreement",
                "evidence_ids": evidence_ids,
                "parser": "Deterministic evidence cited by the parser: " + ", ".join(evidence_ids),
                "ai": _text(raw.get("ai_statement")) or "AI interpretation was not supplied.",
                "resolution": _text(raw.get("resolution")) or "unresolved",
                "confidence": _text(raw.get("confidence")) or "low",
                "unresolved": _unresolved_flag(unresolved),
                "uncertainty": _uncertainty_text(unresolved)
                or "The parser and AI interpretation remain separate for review.",
            }
        )
    return result


def _normalize_claim_metadata(value: object) -> None:
    if isinstance(value, dict):
        if "evidence_ids" in value and "confidence" in value and "unresolved" in value:
            raw_unresolved = value.get("unresolved")
            if not isinstance(raw_unresolved, bool):
                unresolved = _unresolved_flag(raw_unresolved)
                value["unresolved"] = unresolved
                if unresolved and not _text(value.get("uncertainty")):
                    value["uncertainty"] = _uncertainty_text(raw_unresolved) or (
                        "The AI marked this evidence-dependent behavior as unresolved."
                    )
        for child in value.values():
            _normalize_claim_metadata(child)
    elif isinstance(value, list):
        for child in value:
            _normalize_claim_metadata(child)


def _unresolved_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = " ".join(value.casefold().split())
        return normalized not in {"", "none", "no", "resolved", "not unresolved", "n/a", "na"}
    return bool(value)


def _uncertainty_text(value: object) -> str:
    if isinstance(value, str) and _unresolved_flag(value):
        return value
    return ""


def _record_lookup(evidence: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for raw in _sequence(evidence.get("records", evidence.get("evidence"))):
        if isinstance(raw, Mapping):
            identifier = _text(raw.get("id", raw.get("evidence_id")))
            if identifier is not None:
                result[identifier] = raw
    return result


def _facts(record: Mapping[str, object] | None) -> Mapping[str, object]:
    if record is None:
        return {}
    value = record.get("facts", record.get("metadata"))
    return value if isinstance(value, Mapping) else {}


def _first_kind(
    identifiers: Sequence[str], records: Mapping[str, Mapping[str, object]], kind: str
) -> str | None:
    for identifier in identifiers:
        if _text(records.get(identifier, {}).get("kind")) == kind:
            return identifier
    return None


def _record_order(record: Mapping[str, object]) -> tuple[object, ...]:
    source = record.get("source")
    if not isinstance(source, Mapping):
        return (1, "", 0, 0, _text(record.get("id")) or "")
    span = source.get("span")
    if not isinstance(span, Mapping):
        return (1, _text(source.get("path")) or "", 0, 0, _text(record.get("id")) or "")
    start = span.get("start")
    if not isinstance(start, Mapping):
        return (1, _text(source.get("path")) or "", 0, 0, _text(record.get("id")) or "")
    line = start.get("line") if isinstance(start.get("line"), int) else 0
    column = start.get("column") if isinstance(start.get("column"), int) else 0
    return (0, _text(source.get("path")) or "", line, column, _text(record.get("id")) or "")


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


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _copy_json_mapping(value: object) -> dict[str, object]:
    copied = _copy_json(value)
    if not isinstance(copied, dict):
        raise StoryboardPipelineError("storyboard JSON value must be an object")
    return copied


def _copy_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _copy_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_copy_json(item) for item in value]
    return value


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


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
