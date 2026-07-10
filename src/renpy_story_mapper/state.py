from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum

from renpy_story_mapper.model import (
    Call,
    If,
    LabelAnchor,
    Menu,
    Opaque,
    ScriptModule,
    Simple,
    SourceSpan,
    Statement,
)

type JsonScalar = str | int | float | bool | None


class FactStatus(StrEnum):
    PROVEN = "proven"
    POSSIBLE = "possible"
    UNRESOLVED = "unresolved"


class StateCategory(StrEnum):
    RELATIONSHIP = "relationship"
    SKILL = "skill"
    RESOURCE = "resource"
    ROLE = "role"
    FLAG = "flag"
    PROGRESSION = "progression"
    UNKNOWN = "unknown"


@dataclass(frozen=True, order=True)
class StateEvidence:
    source_file: str
    physical_line: int
    span: SourceSpan
    source_text: str

    @classmethod
    def from_statement(cls, span: SourceSpan, source_text: str) -> StateEvidence:
        return cls(span.path, span.start_line, span, source_text)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_file": self.source_file,
            "physical_line": self.physical_line,
            "source": self.span.to_dict(),
            "source_text": self.source_text,
        }


@dataclass(frozen=True)
class Requirement:
    original_expression: str
    variables: tuple[str, ...]
    status: FactStatus
    evidence: StateEvidence
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "original_expression": self.original_expression,
            "variables": list(self.variables),
            "status": self.status.value,
            "evidence": self.evidence.to_dict(),
        }
        if self.reason is not None:
            value["reason"] = self.reason
        return value


@dataclass(frozen=True)
class StateEffect:
    original_expression: str
    operation: str
    variable: str | None
    value: JsonScalar | tuple[JsonScalar, ...] | None
    status: FactStatus
    evidence: StateEvidence
    call_target: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "original_expression": self.original_expression,
            "operation": self.operation,
            "variable": self.variable,
            "value": list(self.value) if isinstance(self.value, tuple) else self.value,
            "status": self.status.value,
            "evidence": self.evidence.to_dict(),
        }
        if self.call_target is not None:
            value["call_target"] = self.call_target
        if self.reason is not None:
            value["reason"] = self.reason
        return value


@dataclass(frozen=True)
class StateVariable:
    original_name: str
    category: StateCategory
    display_name: str
    evidence: tuple[StateEvidence, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "original_name": self.original_name,
            "category": self.category.value,
            "display_name": self.display_name,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class StateAnalysis:
    requirements: tuple[Requirement, ...]
    effects: tuple[StateEffect, ...]
    variables: tuple[StateVariable, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "requirements": [item.to_dict() for item in self.requirements],
            "effects": [item.to_dict() for item in self.effects],
            "variables": [item.to_dict() for item in self.variables],
        }


_CATEGORY_TERMS: tuple[tuple[StateCategory, tuple[str, ...]], ...] = (
    (
        StateCategory.RELATIONSHIP,
        ("affection", "friend", "love", "lust", "relationship", "romance"),
    ),
    (
        StateCategory.SKILL,
        ("charisma", "intelligence", "skill", "strength", "wits", "wisdom"),
    ),
    (
        StateCategory.RESOURCE,
        ("cash", "coin", "gold", "inventory", "item", "money", "resource"),
    ),
    (
        StateCategory.ROLE,
        ("company", "job", "location", "member", "role", "workplace"),
    ),
    (
        StateCategory.FLAG,
        ("allegiance", "cheating", "dating", "event", "flag", "route"),
    ),
    (
        StateCategory.PROGRESSION,
        ("chapter", "day", "progress", "stage", "time", "week"),
    ),
)

_STATE_CALL_TERMS = (
    "add",
    "change",
    "decrease",
    "gain",
    "increase",
    "lose",
    "remove",
    "set",
    "stat",
    "update",
    "xp",
)


def infer_state_category(name: str) -> StateCategory:
    normalized = name.casefold()
    for category, terms in _CATEGORY_TERMS:
        if any(term in normalized for term in terms):
            return category
    return StateCategory.UNKNOWN


def default_display_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.replace(".", "_").split("_") if part)


def extract_state(modules: list[ScriptModule]) -> StateAnalysis:
    requirements: list[Requirement] = []
    effects: list[StateEffect] = []
    for module in sorted(modules, key=lambda item: item.path):
        _walk_statements(module.top_level, requirements, effects)

    requirements.sort(key=lambda item: _record_key(item.evidence, item.original_expression))
    effects.sort(key=lambda item: _record_key(item.evidence, item.original_expression))
    evidence_by_name: dict[str, dict[tuple[object, ...], StateEvidence]] = {}
    for requirement in requirements:
        for name in requirement.variables:
            evidence_by_name.setdefault(name, {})[_evidence_key(requirement.evidence)] = (
                requirement.evidence
            )
    for effect in effects:
        if effect.variable is not None:
            evidence_by_name.setdefault(effect.variable, {})[_evidence_key(effect.evidence)] = (
                effect.evidence
            )
    variables = tuple(
        StateVariable(
            name,
            infer_state_category(name),
            default_display_name(name),
            tuple(sorted(items.values(), key=_evidence_key)),
        )
        for name, items in sorted(evidence_by_name.items())
    )
    return StateAnalysis(tuple(requirements), tuple(effects), variables)


def _walk_statements(
    statements: list[Statement],
    requirements: list[Requirement],
    effects: list[StateEffect],
) -> None:
    for statement in statements:
        if isinstance(statement, LabelAnchor):
            _walk_statements(statement.body, requirements, effects)
        elif isinstance(statement, If):
            for branch in statement.branches:
                if branch.condition is not None:
                    requirements.append(
                        _extract_requirement(
                            branch.condition,
                            StateEvidence.from_statement(branch.span, branch.text),
                        )
                    )
                _walk_statements(branch.body, requirements, effects)
        elif isinstance(statement, Menu):
            for choice in statement.choices:
                if choice.condition is not None:
                    requirements.append(
                        _extract_requirement(
                            choice.condition,
                            StateEvidence.from_statement(choice.span, choice.text),
                        )
                    )
                _walk_statements(choice.body, requirements, effects)
        elif isinstance(statement, Call):
            effect = _extract_renpy_call(statement)
            if effect is not None:
                effects.append(effect)
        elif isinstance(statement, (Simple, Opaque)):
            effect = _extract_statement_effect(statement.text, statement.span)
            if effect is not None:
                effects.append(effect)


def _extract_requirement(expression: str, evidence: StateEvidence) -> Requirement:
    try:
        parsed = ast.parse(expression, mode="eval").body
    except SyntaxError:
        return Requirement(expression, (), FactStatus.UNRESOLVED, evidence, "invalid_expression")
    names = tuple(sorted(_names_in(parsed)))
    reason = _safe_condition(parsed)
    if reason is None:
        return Requirement(expression, names, FactStatus.PROVEN, evidence)
    return Requirement(expression, names, FactStatus.UNRESOLVED, evidence, reason)


def _safe_condition(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, bool | None):
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _safe_condition(node.operand)
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And | ast.Or):
        return next((reason for value in node.values if (reason := _safe_condition(value))), None)
    if isinstance(node, ast.Compare):
        if not all(
            isinstance(operator, ast.Eq | ast.NotEq | ast.Lt | ast.LtE | ast.Gt | ast.GtE)
            for operator in node.ops
        ):
            return "unsupported_comparison_operator"
        operands = [node.left, *node.comparators]
        if all(_safe_condition_operand(operand) for operand in operands):
            return None
        return "computed_comparison_operand"
    return "unsupported_or_dynamic_condition"


def _safe_condition_operand(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) or _literal_scalar(node)[0]


def _extract_statement_effect(text: str, span: SourceSpan) -> StateEffect | None:
    expression = text.strip()
    if expression.startswith("$"):
        expression = expression[1:].lstrip()
    try:
        parsed = ast.parse(expression, mode="exec")
    except SyntaxError:
        return None
    if len(parsed.body) != 1:
        return None
    evidence = StateEvidence.from_statement(span, text)
    node = parsed.body[0]
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return StateEffect(
                expression,
                "assignment",
                None,
                None,
                FactStatus.UNRESOLVED,
                evidence,
                reason="dynamic_or_unsupported_assignment_target",
            )
        variable = node.targets[0].id
        literal, value = _literal_scalar(node.value)
        if literal:
            return StateEffect(
                expression, "assignment", variable, value, FactStatus.PROVEN, evidence
            )
        return StateEffect(
            expression,
            "assignment",
            variable,
            None,
            FactStatus.UNRESOLVED,
            evidence,
            reason="computed_assignment_value",
        )
    if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
        operation = "increment" if isinstance(node.op, ast.Add) else "decrement"
        if not isinstance(node.op, ast.Add | ast.Sub):
            return StateEffect(
                expression,
                "augmented_assignment",
                node.target.id,
                None,
                FactStatus.UNRESOLVED,
                evidence,
                reason="unsupported_augmented_operator",
            )
        literal, value = _literal_scalar(node.value)
        if literal and isinstance(value, int | float) and not isinstance(value, bool):
            return StateEffect(
                expression, operation, node.target.id, value, FactStatus.PROVEN, evidence
            )
        return StateEffect(
            expression,
            operation,
            node.target.id,
            None,
            FactStatus.UNRESOLVED,
            evidence,
            reason="computed_or_non_numeric_delta",
        )
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        return _extract_call(expression, node.value, evidence)
    return None


def _extract_renpy_call(statement: Call) -> StateEffect | None:
    tail = statement.text.removeprefix("call").strip()
    if " from " in tail:
        tail = tail.rsplit(" from ", 1)[0].rstrip()
    try:
        parsed = ast.parse(tail, mode="eval").body
    except SyntaxError:
        if statement.expression is None:
            return None
        return StateEffect(
            tail,
            "call",
            None,
            None,
            FactStatus.UNRESOLVED,
            StateEvidence.from_statement(statement.span, statement.text),
            reason="dynamic_call_target",
        )
    if not isinstance(parsed, ast.Call):
        return None
    return _extract_call(
        tail, parsed, StateEvidence.from_statement(statement.span, statement.text)
    )


def _extract_call(
    expression: str, node: ast.Call, evidence: StateEvidence
) -> StateEffect | None:
    target = _static_callable_name(node.func)
    if target is None:
        return StateEffect(
            expression,
            "call",
            None,
            None,
            FactStatus.UNRESOLVED,
            evidence,
            reason="dynamic_call_target",
        )
    relevant = any(term in target.casefold() for term in _STATE_CALL_TERMS)
    if node.keywords:
        if not relevant:
            return None
        return StateEffect(
            expression,
            "call",
            None,
            None,
            FactStatus.UNRESOLVED,
            evidence,
            call_target=target,
            reason="keyword_call_arguments_not_supported",
        )
    values: list[JsonScalar] = []
    for argument in node.args:
        literal, value = _literal_scalar(argument)
        if not literal:
            if not relevant:
                return None
            return StateEffect(
                expression,
                "call",
                None,
                None,
                FactStatus.UNRESOLVED,
                evidence,
                call_target=target,
                reason="computed_call_argument",
            )
        values.append(value)
    variable = next(
        (
            value
            for value in values
            if isinstance(value, str)
            and infer_state_category(value) != StateCategory.UNKNOWN
        ),
        None,
    )
    if not relevant and variable is None:
        return None
    if not relevant:
        return StateEffect(
            expression,
            "call",
            variable,
            tuple(values),
            FactStatus.UNRESOLVED,
            evidence,
            call_target=target,
            reason="unknown_call_semantics",
        )
    return StateEffect(
        expression,
        "call",
        variable,
        tuple(values),
        FactStatus.POSSIBLE,
        evidence,
        call_target=target,
        reason="creator_call_not_executed",
    )


def _static_callable_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _static_callable_name(node.value)
        return f"{parent}.{node.attr}" if parent is not None else None
    return None


def _literal_scalar(node: ast.expr) -> tuple[bool, JsonScalar]:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return False, None
    if value is None or isinstance(value, str | int | float | bool):
        return True, value
    return False, None


def _names_in(node: ast.AST) -> set[str]:
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}


def _record_key(evidence: StateEvidence, expression: str) -> tuple[object, ...]:
    return (*_evidence_key(evidence), expression)


def _evidence_key(evidence: StateEvidence) -> tuple[object, ...]:
    span = evidence.span
    return (
        evidence.source_file,
        span.start_line,
        span.start_column,
        span.end_line,
        span.end_column,
        evidence.source_text,
    )
