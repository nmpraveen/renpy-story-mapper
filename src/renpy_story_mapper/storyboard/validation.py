"""Validation for the Phase 01 AI-first storyboard artifacts.

The validation boundary intentionally accepts plain ``Mapping`` values.  The evidence worker and
the AI worker can therefore evolve their internal dataclasses independently as long as the JSON
contract exposed here remains stable.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

VALIDATION_SCHEMA_VERSION = "storyboard-validation-v1"
_CONFIDENCE_VALUES = frozenset({"high", "medium", "low"})
_UNRESOLVED_KINDS = frozenset({"dynamic_jump", "dynamic_call", "python"})
_CITATION_KEYS = frozenset(
    {
        "evidence_id",
        "evidence_ids",
        "citation_id",
        "citation_ids",
        "source_evidence_id",
        "source_evidence_ids",
        "target_evidence_id",
        "line_evidence_id",
        "line_evidence_ids",
        "choice_evidence_ids",
        "menu_evidence_id",
        "arm_evidence_id",
    }
)
_CLAIM_EVIDENCE_KEYS = (
    "evidence_id",
    "evidence_ids",
    "line_evidence_ids",
    "source_evidence_ids",
    "target_evidence_id",
    "target_evidence_ids",
    "condition_evidence_ids",
)
_LEGACY_MEMBERSHIP_FIELDS = frozenset(
    {"leaf_evidence_ids", "body_evidence_ids", "member_evidence_ids"}
)
_STATUS_VALUES = frozenset({"resolved", "uncertain", "unresolved", "excluded"})

JsonObject = Mapping[str, object]


@dataclass(frozen=True)
class ValidationIssue:
    """One deterministic validation finding."""

    code: str
    message: str
    severity: str = "error"
    evidence_ids: tuple[str, ...] = ()
    source: Mapping[str, object] | None = None
    details: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "evidence_ids": list(self.evidence_ids),
        }
        if self.source is not None:
            value["source"] = dict(self.source)
        if self.details is not None:
            value["details"] = dict(self.details)
        return value


@dataclass(frozen=True)
class ValidationReport:
    """Stable, JSON-ready result of ``validate_phase01``."""

    publishable: bool
    errors: tuple[ValidationIssue, ...]
    warnings: tuple[ValidationIssue, ...]
    unresolved: tuple[Mapping[str, object], ...]
    disagreements: tuple[Mapping[str, object], ...]
    coverage: Mapping[str, object]
    schema_version: str = VALIDATION_SCHEMA_VERSION

    @property
    def status(self) -> str:
        return "publishable" if self.publishable else "rejected"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "publishable": self.publishable,
            "errors": [item.to_dict() for item in self.errors],
            "warnings": [item.to_dict() for item in self.warnings],
            "unresolved": [dict(item) for item in self.unresolved],
            "disagreements": [dict(item) for item in self.disagreements],
            "coverage": dict(self.coverage),
        }


class _Issues:
    def __init__(self) -> None:
        self.items: list[ValidationIssue] = []

    def add(
        self,
        code: str,
        message: str,
        *,
        severity: str = "error",
        evidence_ids: Iterable[str] = (),
        source: Mapping[str, object] | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.items.append(
            ValidationIssue(
                code,
                message,
                severity,
                tuple(dict.fromkeys(evidence_ids)),
                None if source is None else dict(source),
                None if details is None else dict(details),
            )
        )

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(item for item in self.items if item.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(item for item in self.items if item.severity != "error")


@dataclass(frozen=True)
class _IndexView:
    records: Mapping[str, JsonObject]
    menus: Mapping[str, tuple[str, ...]]
    accountable_ids: frozenset[str]
    leaf_ids: frozenset[str]
    annotation_ids: frozenset[str]
    dynamic_ids: frozenset[str]
    expected_branch_by_leaf: Mapping[str, str]
    expected_leaves_by_branch: Mapping[str, frozenset[str]]
    selection_unresolved: bool


def validate_phase01(
    evidence_index: Mapping[str, object],
    profile: Mapping[str, object],
    analysis: Mapping[str, object],
) -> ValidationReport:
    """Validate a Phase 01 evidence index, profile, and story analysis.

    Inputs are deliberately typed as ``Mapping`` rather than project-specific dataclasses.  The
    function reports all independent findings it can safely identify and only marks the result
    publishable when there are no blocking errors and all accountable source records are covered.
    """

    index = _require_mapping(evidence_index, "evidence index")
    profile_value = _require_mapping(profile, "game profile")
    analysis_value = _require_mapping(analysis, "story analysis")
    issues = _Issues()
    view = _index_view(index, issues)
    if not profile_value:
        issues.add("empty_game_profile", "game profile must not be empty")
    if not analysis_value:
        issues.add("empty_story_analysis", "story analysis must not be empty")

    _validate_membership_shape(profile_value, "profile", issues)
    _validate_membership_shape(analysis_value, "analysis", issues)
    _validate_revision(index, profile_value, analysis_value, issues)
    _validate_citations(profile_value, "profile", view, issues)
    _validate_citations(analysis_value, "analysis", view, issues)
    _validate_semantic_inference_objects(profile_value, "profile", view, issues)
    _validate_semantic_inference_objects(analysis_value, "analysis", view, issues)
    _validate_story_references(analysis_value, issues)
    _validate_analysis(analysis_value, view, issues)
    _validate_menu_coverage(analysis_value, view, issues)
    coverage = _validate_coverage(analysis_value, view, issues)
    disagreements = _visible_disagreements(profile_value, analysis_value, view, issues)
    unresolved = _unresolved_items(profile_value, analysis_value)

    publishable = not issues.errors and bool(coverage["complete"])
    return ValidationReport(
        publishable,
        issues.errors,
        issues.warnings,
        unresolved,
        disagreements,
        coverage,
    )


def validate(
    evidence_index: Mapping[str, object],
    profile: Mapping[str, object],
    analysis: Mapping[str, object],
) -> ValidationReport:
    """Short alias for callers that do not need the Phase 01 name."""

    return validate_phase01(evidence_index, profile, analysis)


def _require_mapping(value: object, label: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a Mapping")
    return value


def _validate_membership_shape(value: JsonObject, owner: str, issues: _Issues) -> None:
    """Reject pre-canonical source membership fields instead of treating them as aliases."""

    def walk(current: object, path: tuple[str, ...]) -> None:
        if isinstance(current, Mapping):
            for key, child in current.items():
                key_text = str(key)
                child_path = (*path, key_text)
                if key_text in _LEGACY_MEMBERSHIP_FIELDS:
                    issues.add(
                        "legacy_membership_field",
                        f"{owner}.{'.'.join(child_path)} is not a canonical membership field; "
                        "use line_evidence_ids",
                        evidence_ids=_text_ids_without_issues(child),
                    )
                walk(child, child_path)
        elif isinstance(current, Sequence) and not isinstance(
            current, (str, bytes, bytearray)
        ):
            for ordinal, child in enumerate(current):
                walk(child, (*path, str(ordinal)))

    walk(value, ())


def _index_view(index: JsonObject, issues: _Issues) -> _IndexView:
    records: dict[str, JsonObject] = {}
    raw_records = _sequence(index.get("records", index.get("evidence")))
    for ordinal, raw in enumerate(raw_records):
        if not isinstance(raw, Mapping):
            issues.add("invalid_evidence_record", f"evidence record {ordinal} is not a mapping")
            continue
        record_id = _text(raw.get("id", raw.get("evidence_id")))
        if record_id is None:
            issues.add("invalid_evidence_record", f"evidence record {ordinal} has no ID")
            continue
        if record_id in records:
            issues.add("duplicate_evidence_id", f"evidence ID {record_id!r} is declared twice")
            continue
        records[record_id] = raw

    if not records:
        issues.add("empty_evidence_index", "evidence index must contain at least one record")

    menus: dict[str, tuple[str, ...]] = {}
    raw_menus = _sequence(index.get("menus"))
    for raw in raw_menus:
        if not isinstance(raw, Mapping):
            issues.add("invalid_menu_record", "menu metadata is not a mapping")
            continue
        menu_id = _text(raw.get("id", raw.get("evidence_id")))
        if menu_id is None:
            issues.add("invalid_menu_record", "menu metadata has no ID")
            continue
        arms = _text_ids(raw.get("arm_ids", raw.get("choice_arm_ids")), issues, "menu arms")
        _report_duplicates(arms, "duplicate_menu_arm", menu_id, issues)
        if menu_id in menus:
            issues.add("duplicate_menu_id", f"menu ID {menu_id!r} is declared twice")
        else:
            menus[menu_id] = tuple(arms)

    for record_id, record in records.items():
        if _text(record.get("kind")) != "menu":
            continue
        facts = record.get("facts")
        if not isinstance(facts, Mapping):
            facts = record
        arms = _text_ids(facts.get("arm_ids", facts.get("choice_arm_ids")), issues, "menu arms")
        if arms and record_id not in menus:
            menus[record_id] = tuple(arms)
        elif record_id in menus and arms and tuple(arms) != menus[record_id]:
            issues.add(
                "conflicting_menu_arms",
                f"menu {record_id!r} has conflicting arm declarations",
                evidence_ids=(record_id,),
                source=_source(record),
            )

    for menu_id, menu_arms in menus.items():
        for arm_id in menu_arms:
            arm = records.get(arm_id)
            if arm is None:
                issues.add(
                    "invalid_index_reference",
                    f"menu {menu_id!r} references unknown arm {arm_id!r}",
                    evidence_ids=(menu_id, arm_id),
                    source=_source(records.get(menu_id)),
                )

    ledger_leaves = [
        record_id
        for record_id, record in records.items()
        if _text(record.get("kind")) == "source_line"
        and (record.get("accountable") is True or _facts(record).get("leaf") is True)
    ]
    if ledger_leaves:
        leaf_ids = frozenset(ledger_leaves)
    else:
        explicit_accountable = _text_ids(
            index.get("accountable_evidence_ids"), issues, "accountable IDs"
        )
        if explicit_accountable:
            leaf_ids = frozenset(explicit_accountable)
        else:
            declared = [record for record in records.values() if "accountable" in record]
            if declared:
                leaf_ids = frozenset(
                    record_id
                    for record_id, record in records.items()
                    if record.get("accountable") is True
                )
            else:
                leaf_ids = frozenset(
                    record_id
                    for record_id, record in records.items()
                    if _text(record.get("kind"))
                    not in {"source_line", "blank", "comment", "diagnostic"}
                )
    for record_id in sorted(leaf_ids):
        if record_id not in records:
            issues.add(
                "invalid_leaf_id",
                f"source-ledger leaf {record_id!r} is not indexed",
                evidence_ids=(record_id,),
            )

    annotation_ids = frozenset(set(records) - set(leaf_ids))
    for record_id, record in records.items():
        parent_id = _text(_facts(record).get("parent_id"))
        if parent_id is not None and parent_id not in records:
            issues.add(
                "dangling_parent_id",
                f"evidence record {record_id!r} references missing parent {parent_id!r}",
                evidence_ids=(record_id, parent_id),
                source=_source(record),
            )

    dynamic_ids = frozenset(
        record_id for record_id, record in records.items() if _is_dynamic_record(record)
    )
    for raw_diagnostic in _sequence(index.get("diagnostics")):
        if not isinstance(raw_diagnostic, Mapping):
            continue
        code = _text(raw_diagnostic.get("code"))
        if code in {"parse_failed", "parser_annotations_unavailable"}:
            issues.add(
                code,
                _text(raw_diagnostic.get("message"))
                or "parser annotations are unavailable for this evidence index",
                details={"diagnostic_code": code},
            )
    expected_branch_by_leaf, expected_leaves_by_branch = _derive_expected_leaf_ownership(
        records, leaf_ids, issues
    )
    selection_unresolved = False
    for raw_diagnostic in _sequence(index.get("diagnostics")):
        if not isinstance(raw_diagnostic, Mapping):
            continue
        if _text(raw_diagnostic.get("code")) in {
            "label_not_found",
            "source_not_found",
            "source_selection_required",
            "source_selection_ambiguous",
        }:
            selection_unresolved = True
            issues.add(
                "unresolved_selection",
                _text(raw_diagnostic.get("message"))
                or "the requested evidence selection could not be resolved",
            )
    selection = index.get("selection")
    if isinstance(selection, Mapping) and _text(selection.get("status")) == "unresolved":
        selection_unresolved = True
        issues.add(
            "unresolved_selection",
            _text(selection.get("uncertainty"))
            or "the requested evidence selection could not be resolved",
        )
    return _IndexView(
        records,
        menus,
        leaf_ids,
        leaf_ids,
        annotation_ids,
        dynamic_ids,
        expected_branch_by_leaf,
        expected_leaves_by_branch,
        selection_unresolved,
    )


def _derive_expected_leaf_ownership(
    records: Mapping[str, JsonObject],
    leaf_ids: frozenset[str],
    issues: _Issues,
) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    """Derive branch ownership from parser annotations and physical source containment."""

    parent_by_id: dict[str, str] = {}
    for record_id, record in records.items():
        parent_id = _text(_facts(record).get("parent_id"))
        if parent_id is None:
            continue
        parent_by_id[record_id] = parent_id
        if parent_id not in records:
            # The ordinary index pass reports the dangling reference. Keep this diagnostic
            # specific to the ownership walk as well only when the chain is actually needed.
            continue

    def chain(record_id: str) -> tuple[str, ...]:
        result: list[str] = []
        seen: set[str] = set()
        current: str | None = record_id
        while current is not None:
            if current in seen:
                issues.add(
                    "cyclic_parent_id",
                    f"evidence parent chain cycles at {current!r}",
                    evidence_ids=tuple(result),
                    source=_source(records.get(current)),
                )
                break
            seen.add(current)
            result.append(current)
            current = parent_by_id.get(current)
            if current is not None and current not in records:
                break
        return tuple(result)

    annotations = [
        (record_id, record)
        for record_id, record in records.items()
        if record_id not in leaf_ids
    ]
    expected: dict[str, str] = {}
    branch_leaves: dict[str, set[str]] = defaultdict(set)
    for leaf_id in leaf_ids:
        leaf = records.get(leaf_id)
        if leaf is None:
            continue
        leaf_source = _source(leaf)
        leaf_span = _span_mapping(leaf_source)
        if leaf_span is None:
            continue
        candidates: list[tuple[int, int, str]] = []
        for record_id, annotation in annotations:
            annotation_span = _span_mapping(_source(annotation))
            if annotation_span is None or not _spans_overlap(leaf_span, annotation_span):
                continue
            branch_id = _branch_id_for_chain(chain(record_id), records)
            if branch_id is None:
                continue
            # Prefer the narrowest physical annotation, then the deepest structural chain. This
            # handles an opaque block that contains its body as well as same-line arm/condition
            # annotations without guessing from dialogue text or labels.
            width = _span_width(annotation_span)
            candidates.append((width, -len(chain(record_id)), branch_id))
        if not candidates:
            continue
        _width, _depth, branch_id = min(candidates)
        expected[leaf_id] = branch_id
        branch_leaves[branch_id].add(leaf_id)
    return expected, {
        branch_id: frozenset(leaf_ids_for_branch)
        for branch_id, leaf_ids_for_branch in branch_leaves.items()
    }


def _branch_id_for_chain(
    chain: Sequence[str], records: Mapping[str, JsonObject]
) -> str | None:
    # The parent chain is ordered from the leaf annotation outward.  An inner evaluated
    # condition therefore owns a leaf before its enclosing menu arm or outer condition.  The
    # enclosing records remain in the chain for structural ancestry and citation validation.
    for record_id in chain:
        record = records.get(record_id)
        if record is None:
            continue
        if _text(record.get("kind")) != "condition":
            continue
        condition_type = _text(_facts(record).get("condition_type"))
        if condition_type in {"if_branch", "else_branch"}:
            return record_id
    for record_id in chain:
        record = records.get(record_id)
        if record is not None and _text(record.get("kind")) == "choice_arm":
            return record_id
    return None


def _source_span(source: Mapping[str, object] | None) -> Mapping[str, object] | None:
    if source is None:
        return None
    span = source.get("span")
    return span if isinstance(span, Mapping) else source


def _span_mapping(source: Mapping[str, object] | None) -> Mapping[str, object] | None:
    span = _source_span(source)
    if span is None:
        return None
    start = span.get("start")
    end = span.get("end")
    if not isinstance(start, Mapping) or not isinstance(end, Mapping):
        return None
    if not isinstance(start.get("line"), int) or not isinstance(end.get("line"), int):
        return None
    return span


def _spans_overlap(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    left_path = _text(left.get("path"))
    right_path = _text(right.get("path"))
    if (
        left_path is not None
        and right_path is not None
        and left_path.casefold() != right_path.casefold()
    ):
        return False
    left_start = left.get("start")
    left_end = left.get("end")
    right_start = right.get("start")
    right_end = right.get("end")
    if not all(
        isinstance(value, Mapping) for value in (left_start, left_end, right_start, right_end)
    ):
        return False
    assert isinstance(left_start, Mapping)
    assert isinstance(left_end, Mapping)
    assert isinstance(right_start, Mapping)
    assert isinstance(right_end, Mapping)
    left_start_line = left_start.get("line")
    left_end_line = left_end.get("line")
    right_start_line = right_start.get("line")
    right_end_line = right_end.get("line")
    return (
        isinstance(left_start_line, int)
        and isinstance(left_end_line, int)
        and isinstance(right_start_line, int)
        and isinstance(right_end_line, int)
        and left_start_line <= right_end_line
        and right_start_line <= left_end_line
    )


def _span_width(span: Mapping[str, object]) -> int:
    start = span.get("start")
    end = span.get("end")
    if not isinstance(start, Mapping) or not isinstance(end, Mapping):
        return 1_000_000
    start_line = start.get("line")
    end_line = end.get("line")
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        return 1_000_000
    return max(0, end_line - start_line)


def _validate_revision(
    index: JsonObject,
    profile: JsonObject,
    analysis: JsonObject,
    issues: _Issues,
) -> None:
    revision = _text(index.get("revision", index.get("index_revision")))
    if revision is None:
        return
    for label, value in (("profile", profile), ("analysis", analysis)):
        supplied = _text(value.get("source_revision", value.get("index_revision")))
        if supplied is None:
            issues.add("missing_source_revision", f"{label} does not declare the evidence revision")
        elif supplied != revision:
            issues.add(
                "source_revision_mismatch",
                f"{label} references {supplied!r}, expected {revision!r}",
            )


def _validate_citations(
    value: JsonObject,
    owner: str,
    view: _IndexView,
    issues: _Issues,
) -> None:
    for path, key, raw_ids in _citation_fields(value):
        ids = _text_ids(raw_ids, issues, f"{owner}.{'.'.join(path)}")
        _report_duplicates(ids, "duplicate_citation", f"{owner}.{'.'.join(path)}", issues)
        for evidence_id in ids:
            if evidence_id not in view.records:
                issues.add(
                    "unknown_evidence_id",
                    f"{owner} cites unknown evidence ID {evidence_id!r}",
                    evidence_ids=(evidence_id,),
                    details={"path": ".".join((*path, key))},
                )


def _validate_claims(value: JsonObject, owner: str, view: _IndexView, issues: _Issues) -> None:
    for path, claim in _claim_fields(value):
        _validate_claim(claim, f"{owner}.{'.'.join(path)}", view, issues)


def _validate_analysis(value: JsonObject, view: _IndexView, issues: _Issues) -> None:
    scenes = _sequence(value.get("scenes"))
    _validate_scene_order(scenes, issues)
    for scene_index, raw_scene in enumerate(scenes):
        if not isinstance(raw_scene, Mapping):
            issues.add("invalid_scene", f"analysis scene {scene_index} is not a mapping")
    for choice_index, (scene, choice, arm, menu_id, arm_id) in enumerate(
        _choice_rows(value, view)
    ):
        conditional_arm = arm_id is not None and _is_conditional_branch_record(
            view.records.get(arm_id, {})
        )
        if arm_id is None or (menu_id is None and not conditional_arm):
            issues.add(
                "invalid_choice_reference",
                f"choice {choice_index} lacks menu and arm IDs",
                evidence_ids=tuple(item for item in (menu_id, arm_id) if item is not None),
            )
            continue
        if menu_id is not None and menu_id not in view.menus:
            issues.add(
                "invalid_choice_reference",
                f"choice references unknown menu {menu_id!r}",
                evidence_ids=(menu_id,),
                source=_source(view.records.get(menu_id)),
            )
        if arm_id not in view.records:
            issues.add(
                "invalid_choice_reference",
                f"choice references unknown arm {arm_id!r}",
                evidence_ids=(arm_id,),
                source=_source(view.records.get(arm_id)),
            )
        for legacy_field in ("menu_id", "arm_id", "arm_evidence_id"):
            if legacy_field in choice or legacy_field in arm:
                issues.add(
                    "legacy_choice_shape",
                    f"choice {choice_index} uses legacy field {legacy_field!r}; "
                    "use canonical evidence_ids",
                    evidence_ids=_choice_evidence(choice),
                )
        for legacy_field in (
            "destination",
            "rejoin",
            "destination_id",
            "rejoin_id",
            "destination_evidence_ids",
            "rejoin_evidence_ids",
        ):
            if legacy_field in arm:
                issues.add(
                    "legacy_destination_shape",
                    f"choice arm {choice_index} uses legacy field {legacy_field!r}; "
                    "use semantic scene IDs",
                    evidence_ids=_choice_evidence(choice),
                )
        _validate_scene_destination(arm, value, view, issues, choice_index)
        if scene is not None:
            scene_id = _text(scene.get("id"))
            if scene_id is not None and _text(choice.get("scene_id")) not in {None, scene_id}:
                issues.add(
                    "invalid_story_reference",
                    f"choice {choice_index} is assigned to a different scene",
                    evidence_ids=tuple(item for item in (menu_id, arm_id) if item is not None),
                )
    _validate_evidence_bindings(value, view, issues)


def _validate_scene_order(scenes: Sequence[object], issues: _Issues) -> None:
    if not any(isinstance(scene, Mapping) and "order" in scene for scene in scenes):
        return
    orders: list[int] = []
    for ordinal, raw_scene in enumerate(scenes):
        if not isinstance(raw_scene, Mapping):
            continue
        value = raw_scene.get("order")
        if isinstance(value, bool) or not isinstance(value, int):
            issues.add("invalid_scene_order", f"scene {ordinal} must declare an integer order")
            continue
        orders.append(value)
        if value != ordinal:
            issues.add(
                "invalid_scene_order",
                f"scene {ordinal} declares order {value}; expected {ordinal}",
            )
    if len(set(orders)) != len(orders):
        issues.add("duplicate_scene_order", "scene order values must be unique")


def _choice_rows(
    value: JsonObject, view: _IndexView
) -> Iterable[
    tuple[JsonObject | None, JsonObject, JsonObject, str | None, str | None]
]:
    scenes = [item for item in _sequence(value.get("scenes")) if isinstance(item, Mapping)]
    top_choices = [item for item in _sequence(value.get("choices")) if isinstance(item, Mapping)]
    for choice in top_choices:
        scene = next(
            (
                candidate
                for candidate in scenes
                if _text(candidate.get("id")) == _text(choice.get("scene_id"))
            ),
            None,
        )
        menu_id = _choice_menu_id(choice, view)
        arms = [item for item in _sequence(choice.get("arms")) if isinstance(item, Mapping)]
        if arms:
            for arm in arms:
                yield scene, choice, arm, menu_id, _choice_arm_id(arm, view)
        else:
            yield scene, choice, choice, menu_id, _choice_arm_id(choice, view)


def _choice_menu_id(choice: JsonObject, view: _IndexView) -> str | None:
    explicit = _text(choice.get("menu_evidence_id"))
    if explicit is not None:
        return explicit
    return _first_kind(_text_ids_without_issues(choice.get("evidence_ids")), view.records, "menu")


def _choice_arm_id(arm: JsonObject, view: _IndexView) -> str | None:
    explicit = None
    if (
        explicit is not None
        and explicit in view.records
        and _is_branch_record(view.records[explicit])
    ):
        return explicit
    for kind in ("choice_arm", "condition"):
        found = _first_kind(_text_ids_without_issues(arm.get("evidence_ids")), view.records, kind)
        if found is not None and _is_branch_record(view.records[found]):
            return found
    return None


def _is_branch_record(record: JsonObject) -> bool:
    kind = _text(record.get("kind"))
    if kind == "choice_arm":
        return True
    if kind != "condition":
        return False
    condition_type = _text(_facts(record).get("condition_type"))
    return condition_type in {"if_branch", "else_branch"}


def _is_conditional_branch_record(record: JsonObject) -> bool:
    return _text(record.get("kind")) == "condition" and _text(
        _facts(record).get("condition_type")
    ) in {"if_branch", "else_branch"}


def _text_ids_without_issues(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _first_kind(
    identifiers: Sequence[str], records: Mapping[str, JsonObject], kind: str
) -> str | None:
    for identifier in identifiers:
        if _text(records.get(identifier, {}).get("kind")) == kind:
            return identifier
    return None


def _validate_story_references(value: JsonObject, issues: _Issues) -> None:
    """Validate the strict Phase 01 scene/choice/transition object graph.

    Older validator fixtures use nested compatibility choices and intentionally have no top-level
    ``choices`` or ``transitions`` collections.  The strict graph checks apply only when either
    collection is present, which is always true for schema-bound pipeline responses.
    """

    if "choices" not in value and "transitions" not in value:
        return

    scenes = [item for item in _sequence(value.get("scenes")) if isinstance(item, Mapping)]
    choices = [item for item in _sequence(value.get("choices")) if isinstance(item, Mapping)]
    transitions = [
        item for item in _sequence(value.get("transitions")) if isinstance(item, Mapping)
    ]

    typed_objects: list[tuple[str, JsonObject]] = []
    typed_objects.extend(("scene", item) for item in scenes)
    typed_objects.extend(("choice", item) for item in choices)
    typed_objects.extend(("transition", item) for item in transitions)
    for choice in choices:
        typed_objects.extend(
            ("arm", item)
            for item in _sequence(choice.get("arms"))
            if isinstance(item, Mapping)
        )

    ids_by_kind: dict[str, set[str]] = defaultdict(set)
    owner_by_id: dict[str, str] = {}
    for kind, item in typed_objects:
        identifier = _text(item.get("id"))
        if identifier is None:
            issues.add("invalid_story_id", f"{kind} is missing an ID")
            continue
        previous = owner_by_id.get(identifier)
        if previous is not None:
            issues.add(
                "duplicate_story_id",
                f"{kind} ID {identifier!r} conflicts with an existing {previous} ID",
            )
        else:
            owner_by_id[identifier] = kind
        ids_by_kind[kind].add(identifier)

    scene_ids = ids_by_kind["scene"]
    choice_ids = ids_by_kind["choice"]
    scene_choice_ids: dict[str, set[str]] = {}
    for scene in scenes:
        scene_id = _text(scene.get("id"))
        if scene_id is None:
            continue
        declared = set(_text_ids(scene.get("choice_ids"), issues, f"scene {scene_id}.choice_ids"))
        scene_choice_ids[scene_id] = declared
        for declared_choice_id in sorted(declared - choice_ids):
            issues.add(
                "invalid_story_reference",
                f"scene {scene_id!r} references unknown choice {declared_choice_id!r}",
            )

    for choice in choices:
        choice_id = _text(choice.get("id"))
        scene_id = _text(choice.get("scene_id"))
        if scene_id not in scene_ids:
            issues.add(
                "invalid_story_reference",
                f"choice {choice_id!r} references unknown scene {scene_id!r}",
            )
        else:
            declared_scene = next(
                (scene for scene in scenes if _text(scene.get("id")) == scene_id),
                None,
            )
            if (
                choice_id is not None
                and declared_scene is not None
                and "choice_ids" in declared_scene
                and choice_id not in scene_choice_ids.get(scene_id, set())
            ):
                issues.add(
                    "invalid_story_reference",
                    f"choice {choice_id!r} is not listed by scene {scene_id!r}",
                )
        for arm in _sequence(choice.get("arms")):
            if not isinstance(arm, Mapping):
                continue
            arm_id = _text(arm.get("id"))
            for field in ("destination_scene_id", "rejoin_scene_id"):
                target = _text(arm.get(field))
                if target is not None and target not in scene_ids:
                    issues.add(
                        "invalid_story_reference",
                        f"arm {arm_id!r} {field} references unknown scene {target!r}",
                    )

    for transition in transitions:
        transition_id = _text(transition.get("id"))
        for legacy_field in ("source_scene_id", "destination_scene_id"):
            if legacy_field in transition:
                issues.add(
                    "legacy_transition_shape",
                    f"transition {transition_id!r} uses legacy field {legacy_field!r}; "
                    "use from_id/to_id",
                )
        for field in ("from_id", "to_id"):
            target = _text(transition.get(field))
            if field == "to_id" and target is None:
                continue
            if target not in scene_ids:
                issues.add(
                    "invalid_story_reference",
                    f"transition {transition_id!r} {field} references unknown scene {target!r}",
                )
        if (
            _text(transition.get("to_id")) is not None
        ):
            source_ids = _text_ids_without_issues(transition.get("source_evidence_ids"))
            target_ids = _text_ids_without_issues(transition.get("target_evidence_ids"))
            if not source_ids or not target_ids:
                issues.add(
                    "missing_source_target_evidence",
                    f"transition {transition_id!r} needs explicit source and target evidence",
                    evidence_ids=tuple(_text_ids_without_issues(transition.get("evidence_ids"))),
                )


def _validate_scene_destination(
    arm: JsonObject,
    analysis: JsonObject,
    view: _IndexView,
    issues: _Issues,
    ordinal: int,
) -> None:
    scenes = {
        _text(scene.get("id"))
        for scene in _sequence(analysis.get("scenes"))
        if isinstance(scene, Mapping) and _text(scene.get("id")) is not None
    }
    for field in ("destination_scene_id", "rejoin_scene_id"):
        target = _text(arm.get(field))
        if target is not None and target not in scenes:
            issues.add(
                "invalid_story_reference",
                f"choice arm {ordinal} {field} references unknown scene {target!r}",
            )
    for field in (
        "source_evidence_ids",
        "target_evidence_ids",
    ):
        for evidence_id in _text_ids_without_issues(arm.get(field)):
            if evidence_id not in view.records:
                issues.add(
                    "unknown_evidence_id",
                    f"choice arm {ordinal} {field} references unknown evidence {evidence_id!r}",
                    evidence_ids=(evidence_id,),
                )
    destination_ids = [
        target
        for target in (
            _text(arm.get("destination_scene_id")),
            _text(arm.get("rejoin_scene_id")),
        )
        if target is not None
    ]
    if destination_ids:
        source_ids = _text_ids_without_issues(arm.get("source_evidence_ids"))
        target_ids = _text_ids_without_issues(arm.get("target_evidence_ids"))
        if not source_ids or not target_ids:
            issues.add(
                "missing_source_target_evidence",
                f"choice arm {ordinal} concrete destination {destination_ids[0]!r} needs "
                "explicit source and target evidence",
                evidence_ids=tuple(_text_ids_without_issues(arm.get("evidence_ids"))),
            )


def _validate_evidence_bindings(
    analysis: JsonObject, view: _IndexView, issues: _Issues
) -> None:
    """Bind concrete edges to the source object and destination scene they claim."""

    scenes = {
        scene_id: scene
        for scene in _sequence(analysis.get("scenes"))
        if isinstance(scene, Mapping)
        for scene_id in (_text(scene.get("id")),)
        if scene_id is not None
    }

    def scene_scope(scene_id: str | None) -> set[str]:
        scene = scenes.get(scene_id or "")
        if scene is None:
            return set()
        return _expand_evidence_scope(
            {
                *_text_ids_without_issues(scene.get("line_evidence_ids")),
                *_text_ids_without_issues(scene.get("evidence_ids")),
            },
            view,
        )

    def arm_scope(arm: JsonObject) -> set[str]:
        return _expand_evidence_scope(
            {
                *_text_ids_without_issues(arm.get("line_evidence_ids")),
                *_text_ids_without_issues(arm.get("evidence_ids")),
                *_text_ids_without_issues(arm.get("condition_evidence_ids")),
            },
            view,
        )

    def check_binding(
        evidence_ids: Sequence[str],
        allowed: set[str],
        *,
        code: str,
        message: str,
        details: Mapping[str, object],
    ) -> None:
        wrong = tuple(
            evidence_id
            for evidence_id in dict.fromkeys(evidence_ids)
            if evidence_id in view.records and evidence_id not in allowed
        )
        if wrong:
            issues.add(
                code,
                message,
                evidence_ids=wrong,
                details={**details, "allowed_evidence_ids": sorted(allowed)},
            )

    for choice_index, choice in enumerate(
        item for item in _sequence(analysis.get("choices")) if isinstance(item, Mapping)
    ):
        origin_scene_id = _text(choice.get("scene_id"))
        for arm_index, raw_arm in enumerate(
            item for item in _sequence(choice.get("arms")) if isinstance(item, Mapping)
        ):
            arm = raw_arm
            arm_id = _text(arm.get("id")) or f"choice-{choice_index}-arm-{arm_index}"
            source_ids = _text_ids_without_issues(arm.get("source_evidence_ids"))
            target_ids = _text_ids_without_issues(arm.get("target_evidence_ids"))
            if source_ids:
                check_binding(
                    source_ids,
                    arm_scope(arm),
                    code="source_evidence_not_in_origin_arm",
                    message=(
                        f"choice arm {arm_id!r} cites source evidence outside its actual "
                        "origin arm"
                    ),
                    details={"origin_scene_id": origin_scene_id, "arm_id": arm_id},
                )
            target_scene_ids = tuple(
                target
                for target in (
                    _text(arm.get("destination_scene_id")),
                    _text(arm.get("rejoin_scene_id")),
                )
                if target is not None
            )
            if target_ids and not target_scene_ids:
                issues.add(
                    "target_evidence_without_destination",
                    f"choice arm {arm_id!r} declares target evidence without a destination "
                    "or rejoin scene",
                    evidence_ids=target_ids,
                    details={"arm_id": arm_id},
                )
            if target_ids and target_scene_ids:
                target_scope: set[str] = set()
                for target_scene_id in target_scene_ids:
                    target_scope.update(scene_scope(target_scene_id))
                check_binding(
                    target_ids,
                    target_scope,
                    code="target_evidence_not_in_destination_scene",
                    message=(
                        f"choice arm {arm_id!r} cites target evidence outside destination "
                        f"scene(s) {', '.join(target_scene_ids)!r}"
                    ),
                    details={"destination_scene_ids": list(target_scene_ids), "arm_id": arm_id},
                )

    for ordinal, raw_transition in enumerate(
        item for item in _sequence(analysis.get("transitions")) if isinstance(item, Mapping)
    ):
        transition_id = _text(raw_transition.get("id")) or f"transition-{ordinal}"
        source_ids = _text_ids_without_issues(raw_transition.get("source_evidence_ids"))
        target_ids = _text_ids_without_issues(raw_transition.get("target_evidence_ids"))
        from_id = _text(raw_transition.get("from_id"))
        to_id = _text(raw_transition.get("to_id"))
        if source_ids:
            check_binding(
                source_ids,
                scene_scope(from_id),
                code="source_evidence_not_in_origin_scene",
                message=(
                    f"transition {transition_id!r} cites source evidence outside origin "
                    f"scene {from_id!r}"
                ),
                details={"origin_scene_id": from_id, "transition_id": transition_id},
            )
        if target_ids and to_id is not None:
            check_binding(
                target_ids,
                scene_scope(to_id),
                code="target_evidence_not_in_destination_scene",
                message=(
                    f"transition {transition_id!r} cites target evidence outside destination "
                    f"scene {to_id!r}"
                ),
                details={"destination_scene_id": to_id, "transition_id": transition_id},
            )
        elif target_ids:
            issues.add(
                "target_evidence_without_destination",
                f"transition {transition_id!r} declares target evidence without a destination",
                evidence_ids=target_ids,
                details={"transition_id": transition_id},
            )


def _expand_evidence_scope(scope_ids: set[str], view: _IndexView) -> set[str]:
    """Include parser annotations whose physical spans belong to the supplied source lines."""

    allowed = {evidence_id for evidence_id in scope_ids if evidence_id in view.records}
    source_line_spans: list[Mapping[str, object]] = []
    for evidence_id in scope_ids:
        if evidence_id not in view.leaf_ids:
            continue
        span = _span_mapping(_source(view.records[evidence_id]))
        if span is not None:
            source_line_spans.append(span)
    for evidence_id, record in view.records.items():
        candidate_span = _span_mapping(_source(record))
        if candidate_span is None:
            continue
        if any(_spans_overlap(candidate_span, line_span) for line_span in source_line_spans):
            allowed.add(evidence_id)
    return allowed


def _register_scene_membership(
    membership: dict[str, list[str]],
    scene_members: set[str],
    owner: str,
    evidence_id: str,
) -> None:
    if evidence_id not in scene_members:
        scene_members.add(evidence_id)
        membership[evidence_id].append(owner)


def _validate_menu_coverage(value: JsonObject, view: _IndexView, issues: _Issues) -> None:
    observed: dict[str, list[str]] = defaultdict(list)
    for _scene, _choice, _arm, menu_id, arm_id in _choice_rows(value, view):
        if menu_id is None or arm_id is None:
            continue
        if menu_id not in view.menus:
            issues.add(
                "invalid_choice_reference",
                f"analysis references unknown menu {menu_id!r}",
                evidence_ids=(menu_id,),
                source=_source(view.records.get(menu_id)),
            )
            continue
        if arm_id not in view.records:
            continue
        if arm_id not in view.menus[menu_id]:
            issues.add(
                "unexpected_menu_arm",
                f"analysis arm {arm_id!r} does not belong to menu {menu_id!r}",
                evidence_ids=(menu_id, arm_id),
                source=_source(view.records.get(arm_id)),
            )
        if arm_id in observed[menu_id]:
            issues.add(
                "duplicate_menu_arm",
                f"analysis repeats arm {arm_id!r} for menu {menu_id!r}",
                evidence_ids=(menu_id, arm_id),
                source=_source(view.records.get(arm_id)),
            )
        observed[menu_id].append(arm_id)

    for menu_id, expected_values in view.menus.items():
        expected = set(expected_values)
        actual = set(observed.get(menu_id, ()))
        for arm_id in sorted(expected - actual):
            issues.add(
                "missing_menu_arm",
                f"analysis omits menu arm {arm_id!r} from menu {menu_id!r}",
                evidence_ids=(menu_id, arm_id),
                source=_source(view.records.get(arm_id)) or _source(view.records.get(menu_id)),
            )


def _validate_coverage(value: JsonObject, view: _IndexView, issues: _Issues) -> dict[str, object]:
    membership: dict[str, list[str]] = defaultdict(list)
    exclusions: dict[str, list[str]] = defaultdict(list)
    duplicate_membership_ids: set[str] = set()
    scene_leaves: dict[str, set[str]] = defaultdict(set)
    scene_owned_leaves: dict[str, set[str]] = defaultdict(set)
    arm_leaves: dict[str, set[str]] = defaultdict(set)
    ownership_violation = False
    scenes = [item for item in _sequence(value.get("scenes")) if isinstance(item, Mapping)]

    def own(
        evidence_id: str,
        owner: str,
        *,
        bucket: str,
        scene_id: str | None = None,
        arm_id: str | None = None,
        branch_id: str | None = None,
    ) -> None:
        nonlocal ownership_violation
        if evidence_id not in view.records:
            issues.add(
                "unknown_evidence_id",
                f"coverage references unknown evidence ID {evidence_id!r}",
                evidence_ids=(evidence_id,),
            )
            return
        # Structural parser records can be cited by a story object but cannot own a source leaf.
        if evidence_id not in view.leaf_ids:
            return
        enforce_parser_ownership = any(
            _text(record.get("kind")) == "source_line" for record in view.records.values()
        )
        expected_branch = view.expected_branch_by_leaf.get(evidence_id)
        if enforce_parser_ownership and bucket == "arm":
            if expected_branch is None:
                ownership_violation = True
                issues.add(
                    "shared_leaf_in_arm",
                    f"shared source leaf {evidence_id!r} is assigned to a branch arm",
                    evidence_ids=(evidence_id,),
                    source=_source(view.records.get(evidence_id)),
                )
            elif branch_id != expected_branch:
                ownership_violation = True
                issues.add(
                    "cross_arm_ownership",
                    f"source leaf {evidence_id!r} belongs to {expected_branch!r}, "
                    f"not {branch_id!r}",
                    evidence_ids=(
                        evidence_id,
                        expected_branch,
                        *(tuple() if branch_id is None else (branch_id,)),
                    ),
                    source=_source(view.records.get(evidence_id)),
                    details={"expected_branch_id": expected_branch, "actual_branch_id": branch_id},
                )
        elif enforce_parser_ownership and expected_branch is not None:
            ownership_violation = True
            issues.add(
                "arm_leaf_in_shared_scene",
                f"branch-owned source leaf {evidence_id!r} is outside its expected arm",
                evidence_ids=(evidence_id, expected_branch),
                source=_source(view.records.get(evidence_id)),
                details={"expected_branch_id": expected_branch, "actual_bucket": bucket},
            )
        target = exclusions if bucket == "excluded" else membership
        target[evidence_id].append(owner)
        if scene_id is not None and bucket in {"scene", "continuation"}:
            scene_leaves[scene_id].add(evidence_id)
        if scene_id is not None and bucket in {"scene", "arm", "continuation"}:
            scene_owned_leaves[scene_id].add(evidence_id)
        if arm_id is not None:
            arm_leaves[arm_id].add(evidence_id)

    def leaf_ids(raw: object, label: str) -> list[str]:
        ids = _text_ids(raw, issues, label)
        _report_duplicates(ids, "duplicate_membership", label, issues)
        return ids

    for scene_index, raw_scene in enumerate(scenes):
        scene_id = _text(raw_scene.get("id")) or f"scene-{scene_index}"
        scene_ids: list[str] = []
        if "line_evidence_ids" in raw_scene:
            scene_ids.extend(
                leaf_ids(raw_scene.get("line_evidence_ids"), f"scene {scene_id}.line_evidence_ids")
            )
        for evidence_id in scene_ids:
            own(evidence_id, f"scene:{scene_id}", bucket="scene", scene_id=scene_id)

        nested_choices = [
            item for item in _sequence(raw_scene.get("choices")) if isinstance(item, Mapping)
        ]
        for choice in nested_choices:
            for arm in _sequence(choice.get("arms")):
                if not isinstance(arm, Mapping):
                    continue
                arm_id = _text(arm.get("id")) or _choice_arm_id(arm, view) or "arm"
                nested_arm_leaf_ids: list[str] = []
                if "line_evidence_ids" in arm:
                    nested_arm_leaf_ids.extend(
                        leaf_ids(arm.get("line_evidence_ids"), f"arm {arm_id}.line_evidence_ids")
                    )
                for evidence_id in nested_arm_leaf_ids:
                    own(
                        evidence_id,
                        f"arm:{arm_id}",
                        bucket="arm",
                        scene_id=scene_id,
                        arm_id=arm_id,
                        branch_id=_choice_arm_id(arm, view),
                    )

    # Top-level canonical choices own arm body leaves independently of the shared scene body.
    for scene, choice, arm, _menu_id, inferred_arm_id in _choice_rows(value, view):
        if scene is None and not _text(choice.get("scene_id")):
            choice_scene_id: str | None = None
        else:
            choice_scene_id = (
                _text(scene.get("id"))
                if scene is not None
                else _text(choice.get("scene_id"))
            )
        choice_arm_id = _text(arm.get("id")) or inferred_arm_id
        if choice_arm_id is None:
            continue
        choice_arm_leaf_ids: list[str] = []
        if "line_evidence_ids" in arm:
            choice_arm_leaf_ids.extend(
                leaf_ids(arm.get("line_evidence_ids"), f"arm {choice_arm_id}.line_evidence_ids")
            )
        for evidence_id in choice_arm_leaf_ids:
            own(
                evidence_id,
                f"arm:{choice_arm_id}",
                bucket="arm",
                scene_id=choice_scene_id,
                arm_id=choice_arm_id,
                branch_id=inferred_arm_id,
            )

    for ordinal, raw in enumerate(_sequence(value.get("continuations"))):
        if not isinstance(raw, Mapping):
            issues.add("invalid_continuation", f"analysis continuation {ordinal} is not a mapping")
            continue
        continuation_id = _text(raw.get("id")) or f"continuation-{ordinal}"
        continuation_scene_id = _text(raw.get("scene_id"))
        if "line_evidence_ids" in raw:
            for evidence_id in leaf_ids(
                raw.get("line_evidence_ids"), f"continuation {continuation_id}.line_evidence_ids"
            ):
                own(
                    evidence_id,
                    f"continuation:{continuation_id}",
                    bucket="continuation",
                    scene_id=continuation_scene_id,
                )

    for ordinal, raw in enumerate(_sequence(value.get("unresolved"))):
        if not isinstance(raw, Mapping):
            continue
        unresolved_id = _text(raw.get("id")) or f"unresolved-{ordinal}"
        source_ids = _text_ids(raw.get("line_evidence_ids"), issues, f"unresolved {unresolved_id}")
        if raw.get("owns_evidence") is True and not source_ids:
            issues.add(
                "missing_membership_field",
                f"unresolved {unresolved_id} must use line_evidence_ids for owned source lines",
            )
        for evidence_id in source_ids:
            own(evidence_id, f"unresolved:{unresolved_id}", bucket="unresolved")

    for ordinal, raw in enumerate(_sequence(value.get("exclusions"))):
        if not isinstance(raw, Mapping):
            issues.add("invalid_exclusion", f"analysis exclusion {ordinal} is not a mapping")
            continue
        excluded_ids = _text_ids(raw.get("line_evidence_ids"), issues, f"exclusion {ordinal}")
        excluded_id = _text(raw.get("evidence_id", raw.get("id")))
        if excluded_id is not None:
            excluded_ids.append(excluded_id)
        if not excluded_ids:
            issues.add("invalid_exclusion", f"analysis exclusion {ordinal} has no evidence ID")
            continue
        owner = _text(raw.get("reason")) or f"exclusion-{ordinal}"
        for evidence_id in excluded_ids:
            own(evidence_id, owner, bucket="excluded")
            if not _is_unresolved(raw):
                issues.add(
                    "missing_uncertainty",
                    f"excluded evidence {evidence_id!r} must be explicitly unresolved",
                    evidence_ids=(evidence_id,),
                )
            if not _has_text(raw.get("uncertainty")):
                issues.add(
                    "missing_uncertainty",
                    f"excluded evidence {evidence_id!r} requires uncertainty text",
                    evidence_ids=(evidence_id,),
                )

    excluded_ids = _text_ids(value.get("excluded_evidence_ids"), issues, "excluded evidence IDs")
    if excluded_ids and not _sequence(value.get("exclusions")):
        for evidence_id in excluded_ids:
            own(evidence_id, "excluded_evidence_ids", bucket="excluded")
            issues.add(
                "missing_exclusion_detail",
                f"excluded evidence {evidence_id!r} needs an explicit exclusion or "
                "unresolved record",
                evidence_ids=(evidence_id,),
            )

    for evidence_id, owners in membership.items():
        if len(owners) > 1:
            duplicate_membership_ids.add(evidence_id)
            issues.add(
                "duplicate_membership",
                f"evidence {evidence_id!r} belongs to multiple story members",
                evidence_ids=(evidence_id,),
                details={"owners": owners},
                source=_source(view.records.get(evidence_id)),
            )
    for evidence_id, owners in exclusions.items():
        if len(owners) > 1 or evidence_id in membership:
            duplicate_membership_ids.add(evidence_id)
            issues.add(
                "duplicate_membership",
                f"evidence {evidence_id!r} is assigned to overlapping ownership buckets",
                evidence_ids=(evidence_id,),
                details={"owners": [*membership.get(evidence_id, []), *owners]},
                source=_source(view.records.get(evidence_id)),
            )

    covered = set(membership) & set(view.leaf_ids)
    excluded = set(exclusions) & set(view.leaf_ids)
    unaccounted = set(view.leaf_ids) - covered - excluded
    for evidence_id in sorted(unaccounted):
        issues.add(
            "unaccounted_source",
            f"source-ledger leaf {evidence_id!r} is not owned by a scene, arm, continuation, "
            "or exclusion",
            evidence_ids=(evidence_id,),
            source=_source(view.records.get(evidence_id)),
        )

    scene_report = []
    for scene in scenes:
        scene_id = _text(scene.get("id")) or "scene"
        owned = sorted(scene_leaves.get(scene_id, set()))
        branch_owned = sorted(
            evidence_id for evidence_id in owned if evidence_id in view.expected_branch_by_leaf
        )
        if branch_owned:
            issues.add(
                "scene_contains_branch_leaves",
                f"scene {scene_id!r} launders branch-owned leaves through its shared body",
                evidence_ids=tuple(branch_owned),
                details={"branch_line_evidence_ids": branch_owned},
            )
        all_owned = sorted(scene_owned_leaves.get(scene_id, set()))
        arm_owned = sorted(set(all_owned) - set(owned))
        scene_complete = bool(all_owned) or not view.leaf_ids
        if view.leaf_ids and not scene_complete:
            issues.add(
                "incomplete_scene_coverage",
                f"scene {scene_id!r} has no owned source-line evidence",
                details={"scene_id": scene_id},
            )
        scene_report.append(
            {
                "scene_id": scene_id,
                "line_evidence_ids": owned,
                "covered": len(all_owned),
                "covered_line_evidence_ids": all_owned,
                "arm_line_evidence_ids": arm_owned,
                "branch_line_evidence_ids": branch_owned,
                "complete": scene_complete and not branch_owned,
            }
        )
    arm_report = []
    observed_branches: set[str] = set()
    for _scene, _choice, arm, _menu, arm_evidence_id in _choice_rows(value, view):
        arm_id = _text(arm.get("id")) or arm_evidence_id or "arm"
        owned = sorted(arm_leaves.get(arm_id, set()))
        expected = sorted(view.expected_leaves_by_branch.get(arm_evidence_id or "", frozenset()))
        if arm_evidence_id is not None:
            observed_branches.add(arm_evidence_id)
        missing = sorted(set(expected) - set(owned))
        unexpected = sorted(set(owned) - set(expected))
        if missing or unexpected:
            issues.add(
                "incomplete_arm_coverage",
                f"arm {arm_id!r} does not match its parser-derived leaf set",
                evidence_ids=tuple(
                    dict.fromkeys(
                        [*missing, *unexpected, *([arm_evidence_id] if arm_evidence_id else [])]
                    )
                ),
                details={
                    "expected_line_evidence_ids": expected,
                    "actual_line_evidence_ids": owned,
                    "missing_line_evidence_ids": missing,
                    "unexpected_line_evidence_ids": unexpected,
                },
            )
        arm_report.append(
            {
                "arm_id": arm_id,
                "arm_evidence_id": arm_evidence_id,
                "expected_line_evidence_ids": expected,
                "line_evidence_ids": owned,
                "expected": len(expected),
                "actual": len(owned),
                "covered": len(owned),
                "missing_line_evidence_ids": missing,
                "unexpected_line_evidence_ids": unexpected,
                "complete": not expected or (not missing and not unexpected),
            }
        )

    for branch_id, expected_branch_leaves in sorted(view.expected_leaves_by_branch.items()):
        if branch_id not in observed_branches:
            issues.add(
                "missing_branch_ownership",
                f"analysis has no arm owner for parser branch {branch_id!r}",
                evidence_ids=(branch_id, *sorted(expected_branch_leaves)),
                source=_source(view.records.get(branch_id)),
                details={"expected_line_evidence_ids": sorted(expected_branch_leaves)},
            )

    duplicate_count = len(duplicate_membership_ids)
    incomplete_arms = sum(
        1
        for item in arm_report
        if isinstance(item, Mapping) and item.get("complete") is False
    )
    complete = (
        bool(view.leaf_ids)
        and not unaccounted
        and not duplicate_count
        and not incomplete_arms
        and not ownership_violation
        and not any(
            isinstance(item, Mapping) and item.get("complete") is False
            for item in scene_report
        )
    )
    coverage: dict[str, object] = {
        "expected": len(view.leaf_ids),
        "covered": len(covered),
        "excluded": len(excluded),
        "unaccounted": len(unaccounted),
        "duplicate_memberships": duplicate_count,
        "complete": complete,
    }
    if any(_text(record.get("kind")) == "source_line" for record in view.records.values()):
        coverage.update(
            {
                "incomplete_arms": incomplete_arms,
                "per_scene": scene_report,
                "per_arm": arm_report,
                "scenes": scene_report,
                "arms": arm_report,
            }
        )
    return coverage


def _visible_disagreements(
    profile: JsonObject,
    analysis: JsonObject,
    view: _IndexView,
    issues: _Issues,
) -> tuple[Mapping[str, object], ...]:
    disagreements: list[Mapping[str, object]] = []
    for owner, value in (("profile", profile), ("analysis", analysis)):
        for ordinal, raw in enumerate(_sequence(value.get("disagreements"))):
            if not isinstance(raw, Mapping):
                issues.add(
                    "invalid_disagreement",
                    f"{owner} disagreement {ordinal} is not a mapping",
                )
                continue
            evidence_ids = _text_ids(raw.get("evidence_ids"), issues, "disagreement evidence")
            _validate_claim_metadata(raw, f"{owner}.disagreements[{ordinal}]", view, issues)
            if raw.get("hidden") is True or raw.get("visible") is False:
                issues.add(
                    "hidden_disagreement",
                    f"{owner} disagreement {ordinal} is marked hidden",
                    evidence_ids=evidence_ids,
                )
            if not _has_text(raw.get("parser"), raw.get("parser_observation")):
                issues.add(
                    "invalid_disagreement",
                    f"{owner} disagreement {ordinal} lacks parser observation",
                    evidence_ids=evidence_ids,
                )
            if not _has_text(raw.get("ai"), raw.get("ai_interpretation")):
                issues.add(
                    "invalid_disagreement",
                    f"{owner} disagreement {ordinal} lacks AI interpretation",
                    evidence_ids=evidence_ids,
                )
            if _text(raw.get("resolution")) is None:
                issues.add(
                    "invalid_disagreement",
                    f"{owner} disagreement {ordinal} lacks resolution",
                    evidence_ids=evidence_ids,
                )
            else:
                issues.add(
                    "parser_ai_disagreement",
                    f"parser/AI disagreement {ordinal} remains visible",
                    severity="warning",
                    evidence_ids=evidence_ids,
                )
            disagreements.append(dict(raw))
    return tuple(disagreements)


def _unresolved_items(
    profile: JsonObject, analysis: JsonObject
) -> tuple[Mapping[str, object], ...]:
    result: list[Mapping[str, object]] = []
    for value in (profile, analysis):
        for raw in _sequence(value.get("unresolved")):
            if isinstance(raw, Mapping):
                result.append(dict(raw))
    return tuple(result)


def _validate_semantic_inference_objects(
    value: JsonObject,
    owner: str,
    view: _IndexView,
    issues: _Issues,
) -> None:
    """Validate the status contract on every canonical semantic inference object."""

    collections = (
        (
            "entry_points",
            "characters",
            "variables",
            "custom_constructs",
            "conventions",
            "ending_patterns",
            "unresolved",
        )
        if owner == "profile"
        else (
            "scenes",
            "choices",
            "transitions",
            "continuations",
            "claims",
            "unresolved",
            "exclusions",
            "disagreements",
        )
    )
    for collection_name in collections:
        raw_collection = value.get(collection_name)
        if collection_name == "unresolved" and isinstance(raw_collection, str):
            issues.add(
                "legacy_unresolved_field",
                f"{owner}.unresolved must be an array of canonical inference objects, not a string",
            )
        for ordinal, raw in enumerate(_sequence(raw_collection)):
            if not isinstance(raw, Mapping):
                issues.add(
                    "invalid_inference_object",
                    f"{owner}.{collection_name}[{ordinal}] must be a mapping",
                )
                continue
            label = f"{owner}.{collection_name}[{ordinal}]"
            _validate_claim_metadata(raw, label, view, issues)
            if collection_name == "scenes" and "line_evidence_ids" not in raw:
                issues.add(
                    "missing_membership_field",
                    f"{label} must declare line_evidence_ids, even when it is empty",
                )
            if collection_name == "choices":
                for arm_ordinal, arm in enumerate(_sequence(raw.get("arms"))):
                    if isinstance(arm, Mapping):
                        if "line_evidence_ids" not in arm:
                            issues.add(
                                "missing_membership_field",
                                f"{label}.arms[{arm_ordinal}] must declare "
                                "line_evidence_ids, even when it is empty",
                            )
                        _validate_claim_metadata(
                            arm,
                            f"{label}.arms[{arm_ordinal}]",
                            view,
                            issues,
                        )
                        consequence = arm.get("consequence")
                        if isinstance(consequence, Mapping):
                            _validate_claim_metadata(
                                consequence,
                                f"{label}.arms[{arm_ordinal}].consequence",
                                view,
                                issues,
                            )
            if collection_name == "scenes":
                for nested_key in ("choices", "branches", "transitions"):
                    if nested_key in raw:
                        issues.add(
                            "nested_story_objects",
                            f"{owner}.scenes[{ordinal}] contains nested {nested_key}; "
                            "choices and transitions must be top-level",
                        )
    # The document-level status describes the confidence of the profile/analysis as a whole.
    _validate_claim_metadata(
        value,
        owner,
        view,
        issues,
        require_evidence=False,
        require_confidence=False,
        reject_legacy_unresolved=False,
    )


def _claim_fields(
    value: object, path: tuple[str, ...] = ()
) -> Iterable[tuple[tuple[str, ...], JsonObject]]:
    if isinstance(value, Mapping):
        if (
            any(key in value for key in _CLAIM_EVIDENCE_KEYS)
            and "confidence" in value
            and ("unresolved" in value or "status" in value)
        ):
            yield path, value
        for key, child in value.items():
            yield from _claim_fields(child, (*path, str(key)))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for ordinal, child in enumerate(value):
            yield from _claim_fields(child, (*path, str(ordinal)))


def _validate_claim(
    claim: JsonObject,
    label: str,
    view: _IndexView,
    issues: _Issues,
) -> None:
    _validate_claim_metadata(claim, label, view, issues)


def _claim_evidence_ids(
    claim: JsonObject, issues: _Issues, label: str
) -> tuple[str, ...]:
    identifiers: list[str] = []
    for key in _CLAIM_EVIDENCE_KEYS:
        for evidence_id in _text_ids(claim.get(key), issues, f"{label}.{key}"):
            if evidence_id not in identifiers:
                identifiers.append(evidence_id)
    return tuple(identifiers)


def _validate_claim_metadata(
    claim: JsonObject,
    label: str,
    view: _IndexView,
    issues: _Issues,
    *,
    require_evidence: bool = True,
    require_confidence: bool = True,
    reject_legacy_unresolved: bool = True,
) -> None:
    evidence_ids = _claim_evidence_ids(claim, issues, label)
    canonical_evidence_ids = _text_ids_without_issues(claim.get("evidence_ids"))
    if require_evidence and not canonical_evidence_ids:
        issues.add(
            "missing_evidence",
            f"{label} must cite at least one evidence ID in canonical evidence_ids",
        )
    if reject_legacy_unresolved and "unresolved" in claim:
        issues.add(
            "legacy_unresolved_field",
            f"{label} must use status and uncertainty; legacy unresolved is not accepted",
            evidence_ids=evidence_ids,
        )
    confidence = _text(claim.get("confidence"))
    if confidence is None and require_confidence:
        issues.add("missing_confidence", f"{label} must declare confidence")
    elif confidence is not None and confidence not in _CONFIDENCE_VALUES:
        issues.add("invalid_confidence", f"{label} has unsupported confidence {confidence!r}")
    status = _status_of(claim)
    if status is None:
        issues.add(
            "missing_status" if "status" not in claim else "invalid_status",
            f"{label} must declare status as resolved, uncertain, unresolved, or excluded",
        )
        unresolved = False
    else:
        unresolved = status in {"uncertain", "unresolved", "excluded"}
    if "uncertainty" not in claim:
        issues.add("missing_uncertainty", f"{label} must declare uncertainty text or null")
    uncertainty = claim.get("uncertainty")
    if uncertainty is not None and not isinstance(uncertainty, str):
        issues.add("invalid_uncertainty", f"{label} uncertainty must be text or null")
    if unresolved and not _has_text(uncertainty):
        issues.add("missing_uncertainty", f"{label} requires uncertainty text when unresolved")
    if (
        not unresolved
        and isinstance(uncertainty, str)
        and not _has_text(uncertainty)
    ):
        issues.add("invalid_uncertainty", f"{label} has empty uncertainty text")
    dynamic_evidence_ids = tuple(
        evidence_id for evidence_id in evidence_ids if evidence_id in view.dynamic_ids
    )
    if dynamic_evidence_ids and status != "unresolved":
        issues.add(
            "dynamic_behavior_as_fact",
            f"{label} must be status=unresolved when it cites Python or runtime-computed evidence",
            evidence_ids=dynamic_evidence_ids,
        )
    custom_evidence_ids = tuple(
        evidence_id
        for evidence_id in evidence_ids
        if evidence_id in view.records
        and (
            _text(view.records[evidence_id].get("kind")) in {"custom", "unknown"}
            or _has_semantic_kind(view.records[evidence_id], {"custom", "unknown"})
        )
    )
    if custom_evidence_ids and not unresolved and not _has_text(
        claim.get("rationale"), claim.get("interpretation_rationale"), claim.get("reason")
    ):
        issues.add(
            "custom_interpretation_without_rationale",
            f"{label} interprets custom or unknown evidence without a rationale",
            evidence_ids=custom_evidence_ids,
        )
        issues.add(
            "dynamic_behavior_as_fact",
            f"{label} presents custom or unknown behavior as a fact without rationale",
            evidence_ids=custom_evidence_ids,
        )


def _status_of(claim: JsonObject) -> str | None:
    raw_status = claim.get("status")
    if isinstance(raw_status, str) and raw_status.strip():
        normalized = raw_status.strip().casefold()
        return normalized if normalized in _STATUS_VALUES else None
    return None


def _has_semantic_kind(record: JsonObject, wanted: set[str]) -> bool:
    facts = record.get("facts")
    facts_value: JsonObject = facts if isinstance(facts, Mapping) else record
    semantic_kinds = facts_value.get("semantic_kinds")
    if not isinstance(semantic_kinds, Sequence) or isinstance(
        semantic_kinds, (str, bytes, bytearray)
    ):
        return False
    return any(isinstance(item, str) and item in wanted for item in semantic_kinds)


def _is_unresolved(value: JsonObject) -> bool:
    return _status_of(value) in {"uncertain", "unresolved", "excluded"}


def _citation_fields(
    value: object, path: tuple[str, ...] = ()
) -> Iterable[tuple[tuple[str, ...], str, object]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            child_path = (*path, key_text)
            if _is_citation_key(key_text):
                yield path, key_text, child
            yield from _citation_fields(child, child_path)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for ordinal, child in enumerate(value):
            yield from _citation_fields(child, (*path, str(ordinal)))


def _is_citation_key(key: str) -> bool:
    normalized = key.casefold()
    return (
        normalized in _CITATION_KEYS
        or normalized.endswith("_evidence_id")
        or normalized.endswith("_evidence_ids")
        or normalized.endswith("_citation_id")
        or normalized.endswith("_citation_ids")
    )


def _text_ids(value: object, issues: _Issues, label: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        issues.add("invalid_citation_shape", f"{label} must be a string or sequence of strings")
        return []
    result: list[str] = []
    for ordinal, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            issues.add("invalid_citation_shape", f"{label}[{ordinal}] must be a non-empty string")
            continue
        result.append(item)
    return result


def _report_duplicates(
    ids: Sequence[str], code: str, owner: str, issues: _Issues
) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for evidence_id in ids:
        if evidence_id in seen:
            duplicates.append(evidence_id)
            issues.add(
                code,
                f"{owner} repeats evidence ID {evidence_id!r}",
                evidence_ids=(evidence_id,),
            )
        seen.add(evidence_id)
    return tuple(dict.fromkeys(duplicates))


def _choice_evidence(choice: JsonObject) -> tuple[str, ...]:
    return tuple(
        evidence_id
        for evidence_id in (
            _text(choice.get("menu_evidence_id", choice.get("menu_id"))),
            _text(choice.get("arm_evidence_id", choice.get("arm_id"))),
        )
        if evidence_id is not None
    )


def _is_dynamic_record(record: JsonObject) -> bool:
    kind = _text(record.get("kind"))
    if kind in _UNRESOLVED_KINDS:
        return True
    facts = record.get("facts")
    facts_value: JsonObject = facts if isinstance(facts, Mapping) else record
    semantic_kinds = facts_value.get("semantic_kinds")
    if (
        isinstance(semantic_kinds, Sequence)
        and not isinstance(semantic_kinds, (str, bytes, bytearray))
        and any(
            isinstance(item, str) and item in {"python", "runtime_dynamic"}
            for item in semantic_kinds
        )
    ):
        return True
    if facts_value.get("semantic_dynamic") is True:
        return True
    if facts_value.get("dynamic") is True or facts_value.get("dynamic_target") is True:
        return True
    if facts_value.get("unresolved") is True:
        return True
    target_kind = _text(facts_value.get("target_kind"))
    if target_kind in {"dynamic", "unresolved"}:
        return True
    if kind in {"jump", "call"}:
        target = facts_value.get("target")
        expression = facts_value.get("expression")
        return target is None and _has_text(expression)
    if kind == "assignment":
        return _text(facts_value.get("assignment_type")) == "inline_python"
    return False


def _source(record: JsonObject | None) -> Mapping[str, object] | None:
    if record is None:
        return None
    source = record.get("source", record.get("span"))
    if isinstance(source, Mapping):
        return dict(source)
    return None


def _facts(record: JsonObject) -> Mapping[str, object]:
    facts = record.get("facts", record.get("metadata"))
    return facts if isinstance(facts, Mapping) else {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _has_text(*values: object) -> bool:
    return any(isinstance(value, str) and value.strip() for value in values)


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()
