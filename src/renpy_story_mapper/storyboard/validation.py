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
_DESTINATION_KINDS = frozenset({"label", "rejoin", "loop", "terminal", "unresolved"})
_UNRESOLVED_KINDS = frozenset({"dynamic_jump", "dynamic_call", "opaque", "unknown", "custom"})
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
        "member_evidence_ids",
        "choice_evidence_ids",
        "menu_evidence_id",
        "arm_evidence_id",
    }
)
_MEMBERSHIP_KEYS = frozenset({"member_evidence_ids", "line_evidence_ids", "choice_evidence_ids"})

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
    dynamic_ids: frozenset[str]


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

    _validate_revision(index, profile_value, analysis_value, issues)
    _validate_citations(profile_value, "profile", view, issues)
    _validate_citations(analysis_value, "analysis", view, issues)
    _validate_claims(profile_value, "profile", view, issues)
    _validate_claims(analysis_value, "analysis", view, issues)
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

    explicit_accountable = _text_ids(
        index.get("accountable_evidence_ids"), issues, "accountable IDs"
    )
    if explicit_accountable:
        accountable_ids = frozenset(explicit_accountable)
    else:
        declared = [record for record in records.values() if "accountable" in record]
        if declared:
            accountable_ids = frozenset(
                record_id
                for record_id, record in records.items()
                if record.get("accountable") is True
            )
        else:
            accountable_ids = frozenset(
                record_id
                for record_id, record in records.items()
                if _text(record.get("kind"))
                not in {"source_line", "blank", "comment", "diagnostic"}
            )
    for record_id in sorted(accountable_ids):
        if record_id not in records:
            issues.add(
                "invalid_accountable_id",
                f"accountable source record {record_id!r} is not indexed",
                evidence_ids=(record_id,),
            )

    dynamic_ids = frozenset(
        record_id for record_id, record in records.items() if _is_dynamic_record(record)
    )
    return _IndexView(records, menus, accountable_ids, dynamic_ids)


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
    for scene_index, raw_scene in enumerate(scenes):
        if not isinstance(raw_scene, Mapping):
            issues.add("invalid_scene", f"analysis scene {scene_index} is not a mapping")
            continue
        choices = _sequence(raw_scene.get("choices"))
        for choice_index, raw_choice in enumerate(choices):
            if not isinstance(raw_choice, Mapping):
                issues.add(
                    "invalid_choice",
                    f"scene {scene_index} choice {choice_index} is not a mapping",
                )
                continue
            menu_id = _text(raw_choice.get("menu_evidence_id", raw_choice.get("menu_id")))
            arm_id = _text(raw_choice.get("arm_evidence_id", raw_choice.get("arm_id")))
            if menu_id is None or arm_id is None:
                issues.add(
                    "invalid_choice_reference",
                    f"scene {scene_index} choice {choice_index} lacks menu and arm IDs",
                    evidence_ids=tuple(item for item in (menu_id, arm_id) if item is not None),
                )
            destination = raw_choice.get("destination")
            _validate_destination(destination, raw_choice, view, issues, scene_index, choice_index)


def _register_scene_membership(
    membership: dict[str, list[str]],
    scene_members: set[str],
    owner: str,
    evidence_id: str,
) -> None:
    if evidence_id not in scene_members:
        scene_members.add(evidence_id)
        membership[evidence_id].append(owner)


def _validate_destination(
    destination: object,
    choice: JsonObject,
    view: _IndexView,
    issues: _Issues,
    scene_index: int,
    choice_index: int,
) -> None:
    prefix = f"scene {scene_index} choice {choice_index} destination"
    if not isinstance(destination, Mapping):
        issues.add("invalid_destination", f"{prefix} must be a mapping")
        return
    kind = _text(destination.get("kind"))
    if kind not in _DESTINATION_KINDS:
        issues.add("invalid_destination", f"{prefix} has unsupported kind {kind!r}")
        return
    target_id = _text(destination.get("target_evidence_id", destination.get("target_id")))
    if kind == "unresolved":
        if destination.get("unresolved") is not True:
            issues.add(
                "dynamic_behavior_as_fact",
                f"{prefix} must set unresolved=true",
                evidence_ids=_choice_evidence(choice),
            )
        if not _has_text(destination.get("uncertainty")):
            issues.add("missing_uncertainty", f"{prefix} requires uncertainty text")
        if target_id is not None:
            issues.add(
                "invalid_destination",
                f"{prefix} cannot assert a concrete target while unresolved",
                evidence_ids=(target_id,),
            )
        return
    if destination.get("unresolved") is True:
        issues.add("invalid_destination", f"{prefix} marks a concrete destination unresolved")
    if target_id is None or target_id not in view.records:
        issues.add(
            "invalid_destination",
            f"{prefix} requires an indexed target_evidence_id",
            evidence_ids=tuple(item for item in (target_id,) if item is not None),
        )
        return
    target = view.records[target_id]
    if target_id in view.dynamic_ids:
        issues.add(
            "dynamic_behavior_as_fact",
            f"{prefix} promotes dynamic evidence {target_id!r} to a concrete destination",
            evidence_ids=(target_id,),
            source=_source(target),
        )
    if not _destination_target_kind_allowed(kind, _text(target.get("kind"))):
        issues.add(
            "invalid_destination",
            f"{prefix} target {target_id!r} is not valid for {kind!r}",
            evidence_ids=(target_id,),
            source=_source(target),
        )


def _validate_menu_coverage(value: JsonObject, view: _IndexView, issues: _Issues) -> None:
    observed: dict[str, list[str]] = defaultdict(list)
    for scene in _sequence(value.get("scenes")):
        if not isinstance(scene, Mapping):
            continue
        for choice in _sequence(scene.get("choices")):
            if not isinstance(choice, Mapping):
                continue
            menu_id = _text(choice.get("menu_evidence_id", choice.get("menu_id")))
            arm_id = _text(choice.get("arm_evidence_id", choice.get("arm_id")))
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
    duplicate_membership_ids: set[str] = set()
    scenes = _sequence(value.get("scenes"))
    for scene_index, raw_scene in enumerate(scenes):
        if not isinstance(raw_scene, Mapping):
            continue
        owner = _text(raw_scene.get("id")) or f"scene-{scene_index}"
        scene_members: set[str] = set()

        for key in _MEMBERSHIP_KEYS:
            ids = _text_ids(raw_scene.get(key), issues, f"scene {owner}.{key}")
            duplicate_membership_ids.update(
                _report_duplicates(ids, "duplicate_membership", owner, issues)
            )
            for evidence_id in ids:
                _register_scene_membership(membership, scene_members, owner, evidence_id)
        for line in _sequence(raw_scene.get("lines")):
            if isinstance(line, Mapping):
                line_evidence_id = _text(line.get("evidence_id", line.get("id")))
                if line_evidence_id is not None:
                    _register_scene_membership(
                        membership, scene_members, owner, line_evidence_id
                    )
        for choice in _sequence(raw_scene.get("choices")):
            if not isinstance(choice, Mapping):
                continue
            for key in ("menu_evidence_id", "arm_evidence_id"):
                choice_evidence_id = _text(choice.get(key))
                if choice_evidence_id is not None:
                    _register_scene_membership(
                        membership, scene_members, owner, choice_evidence_id
                    )

    exclusions: dict[str, list[str]] = defaultdict(list)
    for ordinal, raw in enumerate(_sequence(value.get("exclusions"))):
        if not isinstance(raw, Mapping):
            issues.add("invalid_exclusion", f"analysis exclusion {ordinal} is not a mapping")
            continue
        excluded_evidence_id = _text(raw.get("evidence_id", raw.get("id")))
        if excluded_evidence_id is None:
            issues.add("invalid_exclusion", f"analysis exclusion {ordinal} has no evidence ID")
            continue
        owner = _text(raw.get("reason")) or f"exclusion-{ordinal}"
        exclusions[excluded_evidence_id].append(owner)
        if raw.get("unresolved") is not True:
            issues.add(
                "missing_uncertainty",
                f"excluded evidence {excluded_evidence_id!r} must be explicitly unresolved",
                evidence_ids=(excluded_evidence_id,),
            )
        if not _has_text(raw.get("uncertainty")):
            issues.add(
                "missing_uncertainty",
                f"excluded evidence {excluded_evidence_id!r} requires uncertainty text",
                evidence_ids=(excluded_evidence_id,),
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
        if len(owners) > 1:
            duplicate_membership_ids.add(evidence_id)
            issues.add(
                "duplicate_membership",
                f"evidence {evidence_id!r} is excluded more than once",
                evidence_ids=(evidence_id,),
                details={"owners": owners},
                source=_source(view.records.get(evidence_id)),
            )
        if evidence_id in membership:
            duplicate_membership_ids.add(evidence_id)
            issues.add(
                "duplicate_membership",
                f"evidence {evidence_id!r} is both included and excluded",
                evidence_ids=(evidence_id,),
                source=_source(view.records.get(evidence_id)),
            )

    covered = set(membership) & set(view.records)
    excluded = set(exclusions) & set(view.records)
    unaccounted = set(view.accountable_ids) - covered - excluded
    for evidence_id in sorted(unaccounted):
        issues.add(
            "unaccounted_source",
            f"accountable source record {evidence_id!r} is not covered or explicitly excluded",
            evidence_ids=(evidence_id,),
            source=_source(view.records.get(evidence_id)),
        )
    unknown_members = (set(membership) | set(exclusions)) - set(view.records)
    for evidence_id in sorted(unknown_members):
        issues.add(
            "unknown_evidence_id",
            f"coverage references unknown evidence ID {evidence_id!r}",
            evidence_ids=(evidence_id,),
        )

    duplicate_count = len(duplicate_membership_ids)
    complete = not unaccounted and not unknown_members and duplicate_count == 0
    return {
        "expected": len(view.accountable_ids),
        "covered": len(covered),
        "excluded": len(excluded),
        "unaccounted": len(unaccounted),
        "duplicate_memberships": duplicate_count,
        "complete": complete,
    }


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


def _claim_fields(value: object) -> Iterable[tuple[tuple[str, ...], JsonObject]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = (str(key),)
            if key in {"claims", "outcomes", "consequences"}:
                for ordinal, item in enumerate(_sequence(child)):
                    if isinstance(item, Mapping):
                        yield (*path, str(ordinal)), item
            elif key in {"consequence", "outcome", "destination"} and isinstance(child, Mapping):
                yield path, child
            elif key == "unresolved":
                for ordinal, item in enumerate(_sequence(child)):
                    if isinstance(item, Mapping):
                        yield (*path, str(ordinal)), item
            yield from _claim_fields(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _claim_fields(child)


def _validate_claim(
    claim: JsonObject,
    label: str,
    view: _IndexView,
    issues: _Issues,
) -> None:
    _validate_claim_metadata(claim, label, view, issues)


def _validate_claim_metadata(
    claim: JsonObject,
    label: str,
    view: _IndexView,
    issues: _Issues,
    *,
    require_evidence: bool = True,
) -> None:
    evidence_ids = _text_ids(claim.get("evidence_ids"), issues, f"{label}.evidence_ids")
    if require_evidence and not evidence_ids:
        issues.add("missing_evidence", f"{label} must cite at least one evidence ID")
    confidence = _text(claim.get("confidence"))
    if confidence is None:
        issues.add("missing_confidence", f"{label} must declare confidence")
    elif confidence not in _CONFIDENCE_VALUES:
        issues.add("invalid_confidence", f"{label} has unsupported confidence {confidence!r}")
    unresolved = claim.get("unresolved") is True
    if unresolved and not _has_text(claim.get("uncertainty")):
        issues.add("missing_uncertainty", f"{label} requires uncertainty text when unresolved")
    if (
        not unresolved
        and claim.get("uncertainty") is not None
        and not _has_text(claim.get("uncertainty"))
    ):
        issues.add("invalid_uncertainty", f"{label} has empty uncertainty text")
    dynamic_evidence_ids = tuple(
        evidence_id for evidence_id in evidence_ids if evidence_id in view.dynamic_ids
    )
    if dynamic_evidence_ids and not unresolved:
        issues.add(
            "dynamic_behavior_as_fact",
            f"{label} uses dynamic evidence as a resolved fact",
            evidence_ids=dynamic_evidence_ids,
        )


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


def _destination_target_kind_allowed(destination_kind: str, target_kind: str | None) -> bool:
    if target_kind is None:
        return False
    if destination_kind == "label":
        return target_kind in {"label", "scene", "entry_point"}
    if destination_kind in {"rejoin", "loop"}:
        return target_kind in {"label", "scene", "merge", "rejoin"}
    if destination_kind == "terminal":
        return target_kind in {"label", "scene", "terminal", "ending", "return"}
    return False


def _is_dynamic_record(record: JsonObject) -> bool:
    kind = _text(record.get("kind"))
    if kind in _UNRESOLVED_KINDS:
        return True
    facts = record.get("facts")
    facts_value: JsonObject = facts if isinstance(facts, Mapping) else record
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
    return False


def _source(record: JsonObject | None) -> Mapping[str, object] | None:
    if record is None:
        return None
    source = record.get("source", record.get("span"))
    if isinstance(source, Mapping):
        return dict(source)
    return None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _has_text(*values: object) -> bool:
    return any(isinstance(value, str) and value.strip() for value in values)


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()
