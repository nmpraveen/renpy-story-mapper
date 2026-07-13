"""Strict M08 evaluation manifest model.

The manifest contains only repository-relative fixture paths or user-supplied slot names. It never
resolves external paths and therefore cannot access or transmit story material.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from renpy_story_mapper.evaluation.contracts import sha256_json

MANIFEST_SCHEMA_VERSION = 1
FEATURE_IDS = frozenset(
    {
        "character_development",
        "route_meaning",
        "temporary_detours",
        "persistent_routes",
        "loops",
        "endings",
    }
)


class ManifestError(ValueError):
    """Raised when an evaluation manifest is unsafe or structurally invalid."""


@dataclass(frozen=True)
class InputReference:
    source_kind: str
    external: bool
    repository_path: str | None
    input_sha256: str | None
    path_slot: str | None
    fingerprint_slot: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "source_kind": self.source_kind,
            "external": self.external,
            "repository_path": self.repository_path,
            "input_sha256": self.input_sha256,
            "path_slot": self.path_slot,
            "fingerprint_slot": self.fingerprint_slot,
        }


@dataclass(frozen=True)
class BoundedWindow:
    window_id: str
    parent_scope_id: str
    selection_mode: str
    expected_node_ids: tuple[str, ...]
    expected_evidence_ids: tuple[str, ...]
    boundary_before_node_ids: tuple[str, ...]
    boundary_after_node_ids: tuple[str, ...]
    id_set_sha256: str | None
    id_set_slot: str | None
    id_set_fingerprint_slot: str | None
    max_nodes: int
    max_evidence: int
    require_strict_subset: bool

    @property
    def resolved(self) -> bool:
        return (
            bool(self.expected_node_ids)
            and bool(self.expected_evidence_ids)
            and self.id_set_slot is None
            and self.id_set_fingerprint_slot is None
            and self.id_set_sha256 == self.computed_id_set_sha256
            and not self.parent_scope_id.startswith("$slot:")
        )

    @property
    def computed_id_set_sha256(self) -> str:
        return sha256_json(
            {
                "window_id": self.window_id,
                "parent_scope_id": self.parent_scope_id,
                "selection_mode": self.selection_mode,
                "node_ids": list(self.expected_node_ids),
                "evidence_ids": list(self.expected_evidence_ids),
                "boundary_before_node_ids": list(self.boundary_before_node_ids),
                "boundary_after_node_ids": list(self.boundary_after_node_ids),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "window_id": self.window_id,
            "parent_scope_id": self.parent_scope_id,
            "selection_mode": self.selection_mode,
            "expected_node_ids": list(self.expected_node_ids),
            "expected_evidence_ids": list(self.expected_evidence_ids),
            "boundary_before_node_ids": list(self.boundary_before_node_ids),
            "boundary_after_node_ids": list(self.boundary_after_node_ids),
            "id_set_sha256": self.id_set_sha256,
            "id_set_slot": self.id_set_slot,
            "id_set_fingerprint_slot": self.id_set_fingerprint_slot,
            "max_nodes": self.max_nodes,
            "max_evidence": self.max_evidence,
            "require_strict_subset": self.require_strict_subset,
        }


@dataclass(frozen=True)
class ScopeBounds:
    entry_label: str | None
    scope_ids: tuple[str, ...]
    max_source_files: int
    max_labels: int
    window: BoundedWindow

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_label": self.entry_label,
            "scope_ids": list(self.scope_ids),
            "max_source_files": self.max_source_files,
            "max_labels": self.max_labels,
            "window": self.window.to_dict(),
        }


@dataclass(frozen=True)
class EvaluationExpectations:
    eligible_ids: tuple[str, ...]
    scene_boundaries: tuple[tuple[str, ...], ...]
    meaningful_event_ids: tuple[str, ...]
    feature_subjects: Mapping[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, object]:
        return {
            "eligible_ids": list(self.eligible_ids),
            "scene_boundaries": [list(group) for group in self.scene_boundaries],
            "meaningful_event_ids": list(self.meaningful_event_ids),
            "feature_subjects": {
                key: list(value) for key, value in sorted(self.feature_subjects.items())
            },
        }


@dataclass(frozen=True)
class EvaluationBudget:
    max_calls: int
    max_tokens: int
    max_elapsed_ms: int

    def to_dict(self) -> dict[str, int]:
        return {
            "max_calls": self.max_calls,
            "max_tokens": self.max_tokens,
            "max_elapsed_ms": self.max_elapsed_ms,
        }


@dataclass(frozen=True)
class EvaluationScope:
    id: str
    label: str
    input: InputReference
    bounds: ScopeBounds
    expectations: EvaluationExpectations
    budget: EvaluationBudget

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "input": self.input.to_dict(),
            "bounds": self.bounds.to_dict(),
            "expectations": self.expectations.to_dict(),
            "budget": self.budget.to_dict(),
        }


@dataclass(frozen=True)
class ProviderPolicy:
    model: str
    reasoning: str
    fast_mode: bool
    invocation_default: str

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "reasoning": self.reasoning,
            "fast_mode": self.fast_mode,
            "invocation_default": self.invocation_default,
        }


@dataclass(frozen=True)
class RubricPolicy:
    pass_score: float
    max_title_chars: int
    max_summary_chars: int

    def to_dict(self) -> dict[str, object]:
        return {
            "pass_score": self.pass_score,
            "max_title_chars": self.max_title_chars,
            "max_summary_chars": self.max_summary_chars,
        }


@dataclass(frozen=True)
class EvaluationManifest:
    id: str
    safety: Mapping[str, bool]
    provider_policy: ProviderPolicy
    rubric: RubricPolicy
    scopes: tuple[EvaluationScope, ...]

    def scope(self, scope_id: str) -> EvaluationScope:
        for scope in self.scopes:
            if scope.id == scope_id:
                return scope
        raise KeyError(f"evaluation scope does not exist: {scope_id}")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "id": self.id,
            "safety": dict(sorted(self.safety.items())),
            "provider_policy": self.provider_policy.to_dict(),
            "rubric": self.rubric.to_dict(),
            "scopes": [scope.to_dict() for scope in self.scopes],
        }

    @classmethod
    def load(cls, path: str | Path) -> EvaluationManifest:
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ManifestError("evaluation manifest is not valid JSON") from error
        return cls.from_value(value)

    @classmethod
    def from_value(cls, value: object) -> EvaluationManifest:
        root = _mapping(value, "manifest")
        _keys(
            root,
            {"schema_version", "id", "safety", "provider_policy", "rubric", "scopes"},
            "manifest",
        )
        if _integer(root["schema_version"], "schema_version") != MANIFEST_SCHEMA_VERSION:
            raise ManifestError("unsupported evaluation manifest schema version")
        safety = _bool_mapping(root["safety"], "safety")
        required_safety = {
            "provider_invocation_default_forbidden": True,
            "external_text_forbidden": True,
            "absolute_paths_forbidden": True,
            "walkthrough_is_evaluation_only": True,
        }
        if safety != required_safety:
            raise ManifestError("manifest safety flags must exactly preserve the M08 boundary")

        policy_value = _mapping(root["provider_policy"], "provider_policy")
        _keys(
            policy_value,
            {"model", "reasoning", "fast_mode", "invocation_default"},
            "provider_policy",
        )
        policy = ProviderPolicy(
            model=_text(policy_value["model"], "provider_policy.model"),
            reasoning=_text(policy_value["reasoning"], "provider_policy.reasoning"),
            fast_mode=_boolean(policy_value["fast_mode"], "provider_policy.fast_mode"),
            invocation_default=_text(
                policy_value["invocation_default"], "provider_policy.invocation_default"
            ),
        )
        if policy != ProviderPolicy("gpt-5.6-luna", "high", False, "forbidden"):
            raise ManifestError("provider policy must lock Luna High with fast mode disabled")

        rubric_value = _mapping(root["rubric"], "rubric")
        _keys(
            rubric_value,
            {"pass_score", "max_title_chars", "max_summary_chars"},
            "rubric",
        )
        rubric = RubricPolicy(
            pass_score=_number(rubric_value["pass_score"], "rubric.pass_score"),
            max_title_chars=_integer(rubric_value["max_title_chars"], "rubric.max_title_chars"),
            max_summary_chars=_integer(
                rubric_value["max_summary_chars"], "rubric.max_summary_chars"
            ),
        )
        if not 0.0 < rubric.pass_score <= 1.0:
            raise ManifestError("rubric.pass_score must be in (0, 1]")
        if rubric.max_title_chars <= 0 or rubric.max_summary_chars <= 0:
            raise ManifestError("rubric text limits must be positive")

        scope_values = _object_list(root["scopes"], "scopes")
        if not scope_values:
            raise ManifestError("manifest must contain at least one scope")
        scopes = tuple(_scope(item) for item in scope_values)
        if len({scope.id for scope in scopes}) != len(scopes):
            raise ManifestError("scope IDs must be unique")
        return cls(_text(root["id"], "id"), safety, policy, rubric, scopes)


def _scope(value: Mapping[str, object]) -> EvaluationScope:
    _keys(value, {"id", "label", "input", "bounds", "expectations", "budget"}, "scope")
    input_value = _mapping(value["input"], "scope.input")
    _keys(
        input_value,
        {
            "source_kind",
            "external",
            "repository_path",
            "input_sha256",
            "path_slot",
            "fingerprint_slot",
        },
        "scope.input",
    )
    input_reference = InputReference(
        source_kind=_text(input_value["source_kind"], "scope.input.source_kind"),
        external=_boolean(input_value["external"], "scope.input.external"),
        repository_path=_optional_text(
            input_value["repository_path"], "scope.input.repository_path"
        ),
        input_sha256=_optional_text(input_value["input_sha256"], "scope.input.input_sha256"),
        path_slot=_optional_text(input_value["path_slot"], "scope.input.path_slot"),
        fingerprint_slot=_optional_text(
            input_value["fingerprint_slot"], "scope.input.fingerprint_slot"
        ),
    )
    _validate_input(input_reference)

    bounds_value = _mapping(value["bounds"], "scope.bounds")
    _keys(
        bounds_value,
        {"entry_label", "scope_ids", "max_source_files", "max_labels", "window"},
        "scope.bounds",
    )
    window_value = _mapping(bounds_value["window"], "scope.bounds.window")
    _keys(
        window_value,
        {
            "window_id",
            "parent_scope_id",
            "selection_mode",
            "expected_node_ids",
            "expected_evidence_ids",
            "boundary_before_node_ids",
            "boundary_after_node_ids",
            "id_set_sha256",
            "id_set_slot",
            "id_set_fingerprint_slot",
            "max_nodes",
            "max_evidence",
            "require_strict_subset",
        },
        "scope.bounds.window",
    )
    window = BoundedWindow(
        window_id=_text(window_value["window_id"], "window.window_id"),
        parent_scope_id=_text(window_value["parent_scope_id"], "window.parent_scope_id"),
        selection_mode=_text(window_value["selection_mode"], "window.selection_mode"),
        expected_node_ids=_strings(window_value["expected_node_ids"], "window.expected_node_ids"),
        expected_evidence_ids=_strings(
            window_value["expected_evidence_ids"], "window.expected_evidence_ids"
        ),
        boundary_before_node_ids=_strings(
            window_value["boundary_before_node_ids"], "window.boundary_before_node_ids"
        ),
        boundary_after_node_ids=_strings(
            window_value["boundary_after_node_ids"], "window.boundary_after_node_ids"
        ),
        id_set_sha256=_optional_text(window_value["id_set_sha256"], "window.id_set_sha256"),
        id_set_slot=_optional_text(window_value["id_set_slot"], "window.id_set_slot"),
        id_set_fingerprint_slot=_optional_text(
            window_value["id_set_fingerprint_slot"], "window.id_set_fingerprint_slot"
        ),
        max_nodes=_integer(window_value["max_nodes"], "window.max_nodes"),
        max_evidence=_integer(window_value["max_evidence"], "window.max_evidence"),
        require_strict_subset=_boolean(
            window_value["require_strict_subset"], "window.require_strict_subset"
        ),
    )
    if window.selection_mode != "bounded_window":
        raise ManifestError("evaluation windows must use bounded_window selection")
    if window.max_nodes <= 0 or window.max_evidence <= 0:
        raise ManifestError("evaluation window limits must be positive")
    unresolved = window.id_set_slot is not None or window.id_set_fingerprint_slot is not None
    if unresolved:
        if not window.id_set_slot or not window.id_set_fingerprint_slot:
            raise ManifestError("unresolved windows require both ID-set and fingerprint slots")
        if window.expected_node_ids or window.expected_evidence_ids:
            raise ManifestError("unresolved windows must not mix slots with expected IDs")
        if window.id_set_sha256 is not None:
            raise ManifestError("unresolved windows must not embed an ID-set fingerprint")
    elif not window.resolved:
        raise ManifestError("resolved windows require complete IDs and a matching fingerprint")
    bounds = ScopeBounds(
        entry_label=_optional_text(bounds_value["entry_label"], "scope.bounds.entry_label"),
        scope_ids=_strings(bounds_value["scope_ids"], "scope.bounds.scope_ids"),
        max_source_files=_integer(
            bounds_value["max_source_files"], "scope.bounds.max_source_files"
        ),
        max_labels=_integer(bounds_value["max_labels"], "scope.bounds.max_labels"),
        window=window,
    )
    if not bounds.scope_ids or bounds.max_source_files <= 0 or bounds.max_labels <= 0:
        raise ManifestError("every evaluation scope must be explicit and positively bounded")

    expected_value = _mapping(value["expectations"], "scope.expectations")
    _keys(
        expected_value,
        {"eligible_ids", "scene_boundaries", "meaningful_event_ids", "feature_subjects"},
        "scope.expectations",
    )
    eligible = _strings(expected_value["eligible_ids"], "scope.expectations.eligible_ids")
    if not eligible:
        raise ManifestError("scope expectations must identify eligible deterministic IDs")
    boundaries = tuple(
        _strings(item, "scope.expectations.scene_boundaries[]")
        for item in _array(
            expected_value["scene_boundaries"], "scope.expectations.scene_boundaries"
        )
    )
    feature_value = _mapping(expected_value["feature_subjects"], "feature_subjects")
    if set(feature_value) != FEATURE_IDS:
        raise ManifestError("feature_subjects must define the complete M08 story rubric")
    features = {
        key: _strings(feature_value[key], f"feature_subjects.{key}")
        for key in sorted(FEATURE_IDS)
    }
    expected = EvaluationExpectations(
        eligible_ids=eligible,
        scene_boundaries=boundaries,
        meaningful_event_ids=_strings(
            expected_value["meaningful_event_ids"], "scope.expectations.meaningful_event_ids"
        ),
        feature_subjects=features,
    )
    referenced = set(expected.meaningful_event_ids)
    referenced.update(item for group in boundaries for item in group)
    referenced.update(item for values in features.values() for item in values)
    if window.resolved and referenced - set(eligible):
        raise ManifestError("scope expectations reference IDs outside eligible_ids")

    budget_value = _mapping(value["budget"], "scope.budget")
    _keys(budget_value, {"max_calls", "max_tokens", "max_elapsed_ms"}, "scope.budget")
    budget = EvaluationBudget(
        _integer(budget_value["max_calls"], "scope.budget.max_calls"),
        _integer(budget_value["max_tokens"], "scope.budget.max_tokens"),
        _integer(budget_value["max_elapsed_ms"], "scope.budget.max_elapsed_ms"),
    )
    if min(budget.max_calls, budget.max_tokens, budget.max_elapsed_ms) <= 0:
        raise ManifestError("evaluation budgets must be positive")
    return EvaluationScope(
        id=_text(value["id"], "scope.id"),
        label=_text(value["label"], "scope.label"),
        input=input_reference,
        bounds=bounds,
        expectations=expected,
        budget=budget,
    )


def _validate_input(value: InputReference) -> None:
    if value.source_kind not in {"rpy", "rpyc", "bounded_external"}:
        raise ManifestError("scope input source_kind is unsupported")
    if value.external:
        if (
            value.repository_path is not None
            or value.input_sha256 is not None
            or not value.path_slot
            or not value.fingerprint_slot
        ):
            raise ManifestError("external inputs require path/fingerprint slots and no path")
        return
    if (
        value.path_slot is not None
        or value.fingerprint_slot is not None
        or not value.repository_path
        or value.input_sha256 is None
    ):
        raise ManifestError("checked-in inputs require one repository-relative path")
    if len(value.input_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in value.input_sha256
    ):
        raise ManifestError("checked-in input_sha256 must be a lowercase SHA-256 digest")
    path = PurePosixPath(value.repository_path)
    if path.is_absolute() or ".." in path.parts or path.parts[0] != "tests":
        raise ManifestError("repository paths must be safe, relative test fixture paths")


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ManifestError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise ManifestError(f"{name} fields do not match the strict schema")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{name} must be non-empty text")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ManifestError(f"{name} must be an integer")
    return value


def _number(value: object, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ManifestError(f"{name} must be a number")
    return float(value)


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ManifestError(f"{name} must be a boolean")
    return value


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ManifestError(f"{name} must be an array")
    return cast(list[object], value)


def _object_list(value: object, name: str) -> list[Mapping[str, object]]:
    return [_mapping(item, f"{name}[]") for item in _array(value, name)]


def _strings(value: object, name: str) -> tuple[str, ...]:
    values = tuple(_text(item, f"{name}[]") for item in _array(value, name))
    if len(set(values)) != len(values):
        raise ManifestError(f"{name} must not contain duplicates")
    return values


def _bool_mapping(value: object, name: str) -> dict[str, bool]:
    mapping = _mapping(value, name)
    return {key: _boolean(item, f"{name}.{key}") for key, item in mapping.items()}
