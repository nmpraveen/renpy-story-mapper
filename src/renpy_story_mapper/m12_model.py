"""Immutable contracts for conservative M12 route-to-target solving.

The records in this module contain no operational timestamps, durations, or machine-derived
memory measurements.  Their normalized bytes are therefore suitable for deterministic cache
identity and replay comparisons.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from enum import StrEnum

from renpy_story_mapper.storage import canonical_json

M12_ROUTE_SCHEMA_VERSION = 1
M12_ROUTE_SCHEMA = f"m12-route-result-v{M12_ROUTE_SCHEMA_VERSION}"
M12_SOLVER_VERSION = "m12-static-solver-v1"
M12_LIMIT_PROFILE_VERSION = "m12-limits-v1"

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type StateScalar = str | int | float | bool | None


class DestinationKind(StrEnum):
    GENERIC_SCENE = "generic_scene"
    EXACT_OCCURRENCE = "exact_occurrence"
    TEMPORARY_OUTCOME = "temporary_outcome"
    PERSISTENT_LANE = "persistent_lane"
    TERMINAL = "terminal"
    REPEATABLE_EVENT = "repeatable_event"


class InitialValueKind(StrEnum):
    KNOWN = "known_initial_value"
    ENTRY_PRECONDITION = "entry_precondition"
    UNKNOWN = "unknown_initial_value"


class RequirementSource(StrEnum):
    PROVEN_EFFECT = "proven_effect"
    REPEATED_EVENT = "repeated_event"
    ENTRY_PRECONDITION = "entry_precondition"
    UNKNOWN = "unknown_or_unsupported"


class TechnicalStatus(StrEnum):
    CONFIRMED = "confirmed"
    PREREQUISITES = "route_with_prerequisites"
    BEST_KNOWN = "best_known_route"
    STATE_INFEASIBLE = "state_infeasible"
    NO_STATIC_ROUTE = "no_route_in_resolved_static_graph"
    DYNAMIC_POSSIBILITY = "dynamic_or_unknown_possibility"
    INCOMPLETE = "incomplete_solve"


class RouteBadge(StrEnum):
    CONFIRMED = "Confirmed route"
    PREREQUISITES = "Route with prerequisites"
    BEST_KNOWN = "Best known route"
    NO_PROVEN = "No proven route"


@dataclass(frozen=True, order=True)
class StateVariableIdentity:
    """Stable state identity without pretending missing M10 scope authority exists."""

    scope: str
    name: str
    persistent: bool | None

    @property
    def key(self) -> str:
        persistent = "persistent" if self.persistent is True else (
            "transient" if self.persistent is False else "persistent-unknown"
        )
        return f"{self.scope}:{self.name}:{persistent}"

    def to_dict(self) -> dict[str, JsonValue]:
        return {"scope": self.scope, "name": self.name, "persistent": self.persistent}


@dataclass(frozen=True)
class InitialStateValue:
    variable: StateVariableIdentity
    kind: InitialValueKind
    value: StateScalar = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind is InitialValueKind.UNKNOWN and self.value is not None:
            raise ValueError("unknown initial values cannot carry an assumed value")
        if self.kind is InitialValueKind.KNOWN and not self.evidence_ids:
            raise ValueError("a known initial value requires M10 evidence")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "variable": self.variable.to_dict(),
            "kind": self.kind.value,
            "value": self.value,
            "evidence_ids": list(sorted(self.evidence_ids)),
        }


@dataclass(frozen=True)
class DeterministicLimitProfile:
    """Versioned semantic limits. Wall-clock limits intentionally do not belong here."""

    version: str = M12_LIMIT_PROFILE_VERSION
    expanded_states: int = 20_000
    retained_states: int = 30_000
    frontier_states: int = 10_000
    prefix_records: int = 40_000
    call_depth: int = 32
    repetition_per_transition: int = 16
    alternatives: int = 3
    accounting_units: int = 250_000

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name != "version" and (not isinstance(value, int) or value < 1):
                raise ValueError(f"deterministic limit {name} must be a positive integer")

    def to_dict(self) -> dict[str, JsonValue]:
        return _json_mapping(asdict(self))


@dataclass(frozen=True)
class RouteDestination:
    kind: DestinationKind
    target_id: str

    def __post_init__(self) -> None:
        if not self.target_id:
            raise ValueError("route destinations require a stable target ID")

    def to_dict(self) -> dict[str, JsonValue]:
        return {"kind": self.kind.value, "target_id": self.target_id}


@dataclass(frozen=True)
class RouteRequest:
    source_generation: str
    canonical_schema: str
    canonical_hash: str
    scene_schema: str
    scene_hash: str
    start_node_id: str
    destination: RouteDestination
    initial_state: tuple[InitialStateValue, ...] = ()
    limits: DeterministicLimitProfile = DeterministicLimitProfile()
    solver_version: str = M12_SOLVER_VERSION

    def __post_init__(self) -> None:
        identities = [item.variable.key for item in self.initial_state]
        if len(identities) != len(set(identities)):
            raise ValueError("initial state identities must be unique")
        if not all(
            (
                self.source_generation,
                self.canonical_schema,
                self.canonical_hash,
                self.scene_schema,
                self.scene_hash,
                self.start_node_id,
                self.solver_version,
            )
        ):
            raise ValueError("route requests require exact M10/M11 and solver bindings")

    def normalized_dict(self) -> dict[str, JsonValue]:
        return {
            "solver_version": self.solver_version,
            "source_generation": self.source_generation,
            "canonical_schema": self.canonical_schema,
            "canonical_hash": self.canonical_hash,
            "scene_schema": self.scene_schema,
            "scene_hash": self.scene_hash,
            "start_node_id": self.start_node_id,
            "destination": self.destination.to_dict(),
            "initial_state": [
                item.to_dict()
                for item in sorted(self.initial_state, key=lambda item: item.variable)
            ],
            "limits": self.limits.to_dict(),
        }

    def normalized_bytes(self) -> bytes:
        return canonical_json(self.normalized_dict())

    @property
    def identity(self) -> str:
        return hashlib.sha256(self.normalized_bytes()).hexdigest()


@dataclass(frozen=True)
class RouteProvenance:
    node_ids: tuple[str, ...] = ()
    edge_ids: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    proof_ids: tuple[str, ...] = ()
    scene_ids: tuple[str, ...] = ()
    occurrence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            field: list(sorted(getattr(self, field)))
            for field in (
                "node_ids",
                "edge_ids",
                "fact_ids",
                "evidence_ids",
                "proof_ids",
                "scene_ids",
                "occurrence_ids",
            )
        }


@dataclass(frozen=True)
class RequirementAttribution:
    fact_id: str
    expression: str
    source: RequirementSource
    variable: StateVariableIdentity | None = None
    satisfying_effect_id: str | None = None
    repeated_count: int | None = None
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        links = sum(
            (
                self.satisfying_effect_id is not None,
                self.repeated_count is not None,
                self.source is RequirementSource.ENTRY_PRECONDITION,
                self.source is RequirementSource.UNKNOWN,
            )
        )
        if links != 1:
            raise ValueError("each material requirement must have exactly one attribution")
        if self.source is RequirementSource.PROVEN_EFFECT and self.satisfying_effect_id is None:
            raise ValueError("proven-effect attribution requires its fact ID")
        if self.source is RequirementSource.REPEATED_EVENT and self.repeated_count is None:
            raise ValueError("repeated-event attribution requires a count")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "fact_id": self.fact_id,
            "expression": self.expression,
            "source": self.source.value,
            "variable": self.variable.to_dict() if self.variable is not None else None,
            "satisfying_effect_id": self.satisfying_effect_id,
            "repeated_count": self.repeated_count,
            "evidence_ids": list(sorted(self.evidence_ids)),
        }


@dataclass(frozen=True)
class RouteInstruction:
    ordinal: int
    kind: str
    text: str
    scene_id: str | None = None
    edge_id: str | None = None
    fact_id: str | None = None
    lane_id: str | None = None
    node_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    proof_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return _json_mapping(asdict(self))


@dataclass(frozen=True)
class RouteClaim:
    text: str
    scene_id: str | None = None
    edge_id: str | None = None
    fact_id: str | None = None
    lane_id: str | None = None
    node_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    proof_ids: tuple[str, ...] = ()
    repeated_count: int | None = None

    def __post_init__(self) -> None:
        if not any((self.scene_id, self.edge_id, self.fact_id, self.lane_id, self.node_id)):
            raise ValueError("route claims require an exact source identifier")
        if not self.evidence_ids and not self.proof_ids:
            raise ValueError("route claims require exact evidence or proof identifiers")

    def to_dict(self) -> dict[str, JsonValue]:
        return _json_mapping(asdict(self))


@dataclass(frozen=True)
class RouteCallContext:
    call_site_id: str
    caller_node_id: str
    call_edge_id: str
    callee_entry_node_id: str
    return_edge_ids: tuple[str, ...]
    guard_fact_ids: tuple[str, ...]
    occurrence_id: str | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "call_site_id": self.call_site_id,
            "caller_node_id": self.caller_node_id,
            "call_edge_id": self.call_edge_id,
            "callee_entry_node_id": self.callee_entry_node_id,
            "return_edge_ids": list(sorted(self.return_edge_ids)),
            "guard_fact_ids": list(sorted(self.guard_fact_ids)),
            "occurrence_id": self.occurrence_id,
        }


@dataclass(frozen=True)
class RouteAlternative:
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]
    scene_ids: tuple[str, ...]
    scene_titles: tuple[str, ...]
    visible_choices: tuple[str, ...]
    requirements: tuple[RequirementAttribution, ...]
    persistent_lane_ids: tuple[str, ...]
    uncertainty_warnings: tuple[str, ...]
    instructions: tuple[RouteInstruction, ...]
    call_contexts: tuple[RouteCallContext, ...]
    selected_occurrence_id: str | None
    loop_count: int
    ranking_key: tuple[int | str, ...]
    provenance: RouteProvenance
    scene_claims: tuple[RouteClaim, ...] = ()
    visible_choice_claims: tuple[RouteClaim, ...] = ()
    satisfying_effect_claims: tuple[RouteClaim, ...] = ()
    repeated_action_claims: tuple[RouteClaim, ...] = ()
    persistent_commitment_claims: tuple[RouteClaim, ...] = ()
    uncertainty_claims: tuple[RouteClaim, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "node_ids": list(self.node_ids),
            "edge_ids": list(self.edge_ids),
            "scene_ids": list(self.scene_ids),
            "scene_titles": list(self.scene_titles),
            "visible_choices": list(self.visible_choices),
            "requirements": [item.to_dict() for item in self.requirements],
            "persistent_lane_ids": list(self.persistent_lane_ids),
            "uncertainty_warnings": list(self.uncertainty_warnings),
            "instructions": [item.to_dict() for item in self.instructions],
            "call_contexts": [item.to_dict() for item in self.call_contexts],
            "selected_occurrence_id": self.selected_occurrence_id,
            "loop_count": self.loop_count,
            "ranking_key": list(self.ranking_key),
            "provenance": self.provenance.to_dict(),
            "scene_claims": [item.to_dict() for item in self.scene_claims],
            "visible_choice_claims": [item.to_dict() for item in self.visible_choice_claims],
            "satisfying_effect_claims": [
                item.to_dict() for item in self.satisfying_effect_claims
            ],
            "repeated_action_claims": [
                item.to_dict() for item in self.repeated_action_claims
            ],
            "persistent_commitment_claims": [
                item.to_dict() for item in self.persistent_commitment_claims
            ],
            "uncertainty_claims": [item.to_dict() for item in self.uncertainty_claims],
        }


@dataclass(frozen=True)
class BudgetUsage:
    expanded_states: int
    retained_states: int
    peak_frontier_states: int
    prefix_records: int
    accounting_units: int
    limiting_dimension: str | None = None

    def to_dict(self) -> dict[str, JsonValue]:
        return _json_mapping(asdict(self))


@dataclass(frozen=True)
class RouteResult:
    request_identity: str
    status: TechnicalStatus
    badge: RouteBadge
    recommended: RouteAlternative | None
    alternatives: tuple[RouteAlternative, ...]
    complete: bool
    termination_reason: str
    exhaustive: bool
    closed_world: bool
    budget_usage: BudgetUsage
    negative_provenance: RouteProvenance | None
    diagnostics: tuple[str, ...]

    def __post_init__(self) -> None:
        complete_reasons = {"exhaustive", "best_route_proven"}
        if self.complete != (self.termination_reason in complete_reasons):
            raise ValueError("complete results require a deterministic completion reason")
        if self.exhaustive != (self.termination_reason == "exhaustive"):
            raise ValueError("exhaustive results require deterministic exhaustion")
        if self.exhaustive and not self.complete:
            raise ValueError("exhaustive results must be semantically complete")
        if self.status is TechnicalStatus.INCOMPLETE and self.complete:
            raise ValueError("an incomplete status cannot be semantically complete")
        if self.status in {
            TechnicalStatus.STATE_INFEASIBLE,
            TechnicalStatus.NO_STATIC_ROUTE,
        } and (not self.complete or not self.exhaustive or not self.closed_world):
            raise ValueError("negative conclusions require exhaustive closed-world completion")
        if self.status in {
            TechnicalStatus.STATE_INFEASIBLE,
            TechnicalStatus.NO_STATIC_ROUTE,
        }:
            if (
                self.negative_provenance is None
                or not self.negative_provenance.node_ids
                or not (
                    self.negative_provenance.evidence_ids
                    or self.negative_provenance.proof_ids
                )
            ):
                raise ValueError("negative conclusions require exact closure provenance")
            if (
                self.status is TechnicalStatus.STATE_INFEASIBLE
                and not self.negative_provenance.fact_ids
            ):
                raise ValueError("state-infeasible conclusions require contradiction facts")
        elif self.negative_provenance is not None:
            raise ValueError("only proven negative conclusions can carry negative provenance")

    def normalized_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": M12_ROUTE_SCHEMA_VERSION,
            "schema": M12_ROUTE_SCHEMA,
            "request_identity": self.request_identity,
            "status": self.status.value,
            "badge": self.badge.value,
            "recommended": self.recommended.to_dict() if self.recommended is not None else None,
            "alternatives": [item.to_dict() for item in self.alternatives],
            "complete": self.complete,
            "termination_reason": self.termination_reason,
            "exhaustive": self.exhaustive,
            "closed_world": self.closed_world,
            "budget_usage": self.budget_usage.to_dict(),
            "negative_provenance": (
                None
                if self.negative_provenance is None
                else self.negative_provenance.to_dict()
            ),
            "diagnostics": list(self.diagnostics),
        }

    def normalized_bytes(self) -> bytes:
        return canonical_json(self.normalized_dict())


@dataclass(frozen=True)
class SolveAttempt:
    """A core attempt. Cancellation intentionally yields no publishable result."""

    result: RouteResult | None
    cancelled: bool = False
    diagnostic: str | None = None


def badge_for_status(status: TechnicalStatus, *, has_route: bool) -> RouteBadge:
    if status is TechnicalStatus.CONFIRMED:
        return RouteBadge.CONFIRMED
    if status is TechnicalStatus.PREREQUISITES:
        return RouteBadge.PREREQUISITES
    if has_route:
        return RouteBadge.BEST_KNOWN
    return RouteBadge.NO_PROVEN


def _json_mapping(value: Mapping[str, object]) -> dict[str, JsonValue]:
    return {str(key): _json_value(item) for key, item in value.items()}


def _json_value(value: object) -> JsonValue:
    if isinstance(value, StrEnum):
        return value.value
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return _json_mapping(value)
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return _json_mapping(asdict(value))
    raise TypeError(f"unsupported M12 JSON value: {type(value).__name__}")
