"""Durable, generation-bound persistence for deterministic M11 results.

M11 uses the generic payload table deliberately: phase results are content-addressed
by their input hash, while a small state document owns the working and published
pointers.  The records contain only canonical provenance scalars and derived M11
payloads; they never acquire source dependencies or embed the M10 graph.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from renpy_story_mapper import storage
from renpy_story_mapper.canonical_graph_contract import (
    CANONICAL_GRAPH_SCHEMA,
    CANONICAL_GRAPH_SCHEMA_VERSION,
)
from renpy_story_mapper.project import PayloadRecord

if TYPE_CHECKING:
    from renpy_story_mapper.project import Project


M11_PHASES: Final = (
    "story_atoms",
    "scene_boundaries",
    "scene_assembly",
    "scene_presentation",
)

PHASE_RESULTS_COLLECTION: Final = "m11_phase_results"
ANALYSIS_STATE_COLLECTION: Final = "m11_analysis_state"
CORRECTIONS_COLLECTION: Final = "m11_corrections"
ANALYSIS_STATE_KEY: Final = "authoritative"

PHASE_RESULT_SCHEMA: Final = "m11-phase-result-v1"
ANALYSIS_STATE_SCHEMA: Final = "m11-analysis-state-v1"
CORRECTIONS_SCHEMA: Final = "m11-corrections-v1"

_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")


class M11PreconditionError(ValueError):
    """A caller attempted to publish or replace a result from stale state."""


class M11Availability(StrEnum):
    UNAVAILABLE = "unavailable"
    CURRENT_COMPLETE = "current_complete"


@dataclass(frozen=True)
class CanonicalBinding:
    """The indivisible M10 authority identity consumed by one M11 build."""

    source_generation: str
    canonical_schema: str
    canonical_hash: str

    def __post_init__(self) -> None:
        if not self.source_generation.strip():
            raise ValueError("source_generation cannot be empty")
        if self.canonical_schema != CANONICAL_GRAPH_SCHEMA:
            raise ValueError(
                f"canonical schema must be {CANONICAL_GRAPH_SCHEMA!r}, "
                f"not {self.canonical_schema!r}"
            )
        _require_hash(self.canonical_hash, "canonical_hash")

    @classmethod
    def from_payload(cls, canonical: Mapping[str, object]) -> CanonicalBinding:
        """Validate an M10 payload and bind its exact normalized bytes."""

        schema = canonical.get("schema")
        schema_version = canonical.get("schema_version")
        generation = canonical.get("source_generation")
        if schema != CANONICAL_GRAPH_SCHEMA:
            raise ValueError("M11 requires the M10 canonical graph schema")
        if schema_version != CANONICAL_GRAPH_SCHEMA_VERSION:
            raise ValueError("M11 canonical schema version is unsupported")
        if not isinstance(generation, str) or not generation.strip():
            raise ValueError("M10 canonical source_generation is missing")
        return cls(
            generation,
            str(schema),
            _content_hash(dict(canonical)),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "source_generation": self.source_generation,
            "canonical_schema": self.canonical_schema,
            "canonical_hash": self.canonical_hash,
        }


@dataclass(frozen=True)
class PhasePointer:
    phase: str
    input_hash: str
    record_key: str
    result_hash: str

    def __post_init__(self) -> None:
        _require_phase(self.phase)
        _require_hash(self.input_hash, "input_hash")
        _require_hash(self.result_hash, "result_hash")
        if self.record_key != phase_result_key(self.phase, self.input_hash):
            raise ValueError("phase result key does not match its phase and input hash")

    def to_dict(self) -> dict[str, str]:
        return {
            "phase": self.phase,
            "input_hash": self.input_hash,
            "record_key": self.record_key,
            "result_hash": self.result_hash,
        }


@dataclass(frozen=True)
class BuildBinding:
    canonical: CanonicalBinding
    phases: tuple[PhasePointer, ...]
    binding_hash: str

    def __post_init__(self) -> None:
        _validate_phase_prefix(self.phases)
        _require_hash(self.binding_hash, "binding_hash")
        if self.binding_hash != _build_binding_hash(self.canonical, self.phases):
            raise ValueError("M11 build binding hash does not match its pointers")

    @classmethod
    def create(
        cls,
        canonical: CanonicalBinding,
        phases: Sequence[PhasePointer],
    ) -> BuildBinding:
        materialized = tuple(phases)
        return cls(canonical, materialized, _build_binding_hash(canonical, materialized))

    @property
    def complete(self) -> bool:
        return len(self.phases) == len(M11_PHASES)

    def to_dict(self) -> dict[str, object]:
        return {
            **self.canonical.to_dict(),
            "phases": [item.to_dict() for item in self.phases],
            "binding_hash": self.binding_hash,
        }


@dataclass(frozen=True)
class PhaseCheckpoint:
    phase: str
    input_hash: str
    result_hash: str
    record_key: str
    working_hash: str
    reused: bool


@dataclass(frozen=True)
class Publication:
    canonical: CanonicalBinding
    model_hash: str
    phase_hashes: Mapping[str, str]
    pruned_results: int
    reused: bool


@dataclass(frozen=True)
class M11Selection:
    availability: M11Availability
    reason: str
    canonical: CanonicalBinding | None = None
    model_hash: str | None = None
    phase_results: Mapping[str, Mapping[str, object]] | None = None


@dataclass(frozen=True)
class CorrectionWrite:
    record_key: str
    corrections_hash: str
    reused: bool


@dataclass(frozen=True)
class _AnalysisState:
    working: BuildBinding
    published: BuildBinding | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": ANALYSIS_STATE_SCHEMA,
            "working": self.working.to_dict(),
            "published": None if self.published is None else self.published.to_dict(),
        }


def phase_result_key(phase: str, input_hash: str) -> str:
    """Return the stable generic-payload key for one phase input."""

    _require_phase(phase)
    _require_hash(input_hash, "input_hash")
    return f"{phase}:{input_hash}"


def phase_input_hash(value: Mapping[str, object]) -> str:
    """Hash a caller-owned normalized phase input contract."""

    return _content_hash(dict(value))


class M11Persistence:
    """Store M11 checkpoints and atomically select one complete publication."""

    def __init__(self, project: Project) -> None:
        self._project = project
        self._cached_payload: Mapping[str, object] | None = None
        self._cached_authority: CanonicalBinding | None = None

    def _authority(self, canonical: Mapping[str, object]) -> CanonicalBinding:
        if canonical is self._cached_payload and self._cached_authority is not None:
            return self._cached_authority
        authority = CanonicalBinding.from_payload(canonical)
        self._cached_payload = canonical
        self._cached_authority = authority
        return authority

    def cache_authority(
        self,
        canonical: Mapping[str, object],
        *,
        canonical_hash: str,
    ) -> CanonicalBinding:
        """Seed an exact hash already computed from this in-memory canonical payload."""

        _require_hash(canonical_hash, "canonical_hash")
        schema = canonical.get("schema")
        schema_version = canonical.get("schema_version")
        generation = canonical.get("source_generation")
        if (
            schema != CANONICAL_GRAPH_SCHEMA
            or schema_version != CANONICAL_GRAPH_SCHEMA_VERSION
            or not isinstance(generation, str)
            or not generation.strip()
        ):
            raise ValueError("M11 requires a valid generation-bound M10 canonical graph")
        authority = CanonicalBinding(generation, str(schema), canonical_hash)
        self._cached_payload = canonical
        self._cached_authority = authority
        return authority

    def checkpoint_phase(
        self,
        canonical: Mapping[str, object],
        phase: str,
        input_hash: str,
        result: Mapping[str, object],
        *,
        expected_working_hash: str | None = None,
    ) -> PhaseCheckpoint:
        """Commit one phase envelope and its working pointer in one transaction."""

        authority = self._authority(canonical)
        _require_phase(phase)
        _require_hash(input_hash, "input_hash")
        if expected_working_hash is not None:
            _require_hash(expected_working_hash, "expected_working_hash")
        result_value = dict(result)
        result_hash = _content_hash(result_value)
        pointer = PhasePointer(
            phase,
            input_hash,
            phase_result_key(phase, input_hash),
            result_hash,
        )

        state = self._read_state()
        reused = self._reused_checkpoint(
            state,
            authority,
            pointer,
            expected_working_hash,
        )
        if reused is not None:
            return reused

        connection = self._project._require_open()
        with storage.transaction(connection):
            state = self._read_state()
            published = None if state is None else state.published
            if expected_working_hash is not None:
                actual_hash = None if state is None else state.working.binding_hash
                if actual_hash != expected_working_hash:
                    raise M11PreconditionError("working M11 binding changed before checkpoint")

            if state is None or state.working.canonical != authority:
                if phase != M11_PHASES[0]:
                    raise M11PreconditionError(
                        "a new canonical binding must begin with story_atoms"
                    )
                prior: tuple[PhasePointer, ...] = ()
            else:
                prior = state.working.phases

            phase_index = M11_PHASES.index(phase)
            if phase_index > len(prior):
                raise M11PreconditionError("M11 phases must checkpoint in declared order")
            if phase_index < len(prior):
                prior_pointer = prior[phase_index]
                if prior_pointer == pointer:
                    self._load_phase_envelope(authority, pointer)
                    assert state is not None
                    return _checkpoint_value(pointer, state.working.binding_hash, reused=True)
                next_phases = (*prior[:phase_index], pointer)
            else:
                next_phases = (*prior, pointer)

            existing = self._project.payload(PHASE_RESULTS_COLLECTION, pointer.record_key)
            envelope = _phase_envelope(authority, pointer, result_value)
            records: list[PayloadRecord] = []
            if existing is None:
                records.append(
                    PayloadRecord(PHASE_RESULTS_COLLECTION, pointer.record_key, envelope)
                )
            else:
                existing_result = _decode_phase_envelope(existing, authority, pointer)
                if existing_result != result_value:
                    raise storage.ProjectCorruptError(
                        "M11 phase input hash resolves to different result content"
                    )

            working = BuildBinding.create(authority, next_phases)
            next_state = _AnalysisState(working, published)
            records.append(
                PayloadRecord(ANALYSIS_STATE_COLLECTION, ANALYSIS_STATE_KEY, next_state.to_dict())
            )
            self._project._write_payloads_in_transaction(records)

        return _checkpoint_value(pointer, working.binding_hash, reused=False)

    def phase_result(
        self,
        canonical: Mapping[str, object],
        phase: str,
        input_hash: str,
    ) -> Mapping[str, object] | None:
        """Load one coherent durable checkpoint without consulting other phases."""

        authority = self._authority(canonical)
        pointer_key = phase_result_key(phase, input_hash)
        raw = self._project.payload(PHASE_RESULTS_COLLECTION, pointer_key)
        if raw is None:
            return None
        root = _require_mapping(raw, "M11 phase envelope")
        result_hash = root.get("result_hash")
        if not isinstance(result_hash, str):
            raise storage.ProjectCorruptError("M11 phase envelope result_hash is invalid")
        try:
            pointer = PhasePointer(phase, input_hash, pointer_key, result_hash)
        except ValueError as exc:
            raise storage.ProjectCorruptError("M11 phase envelope pointer is invalid") from exc
        return _decode_phase_envelope(raw, authority, pointer)

    def publish(
        self,
        canonical: Mapping[str, object],
        *,
        expected_working_hash: str,
        expected_phase_hashes: Mapping[str, str],
    ) -> Publication:
        """Atomically publish a complete build and prune unreferenced phase envelopes."""

        authority = self._authority(canonical)
        _require_hash(expected_working_hash, "expected_working_hash")
        expected = _expected_phase_hashes(expected_phase_hashes)

        state = self._read_state()
        working = self._publication_binding_preconditions(
            state,
            authority,
            expected_working_hash,
            expected,
        )
        if (
            state is not None
            and state.published == working
            and not self._has_unreferenced_phase_results(working)
        ):
            return _publication_value(working, 0, reused=True)

        connection = self._project._require_open()
        with storage.transaction(connection):
            state = self._read_state()
            working = self._publication_binding_preconditions(
                state,
                authority,
                expected_working_hash,
                expected,
            )
            results = self._load_complete_results(working)
            next_state = _AnalysisState(working, working)
            self._project._write_payloads_in_transaction(
                (
                    PayloadRecord(
                        ANALYSIS_STATE_COLLECTION,
                        ANALYSIS_STATE_KEY,
                        next_state.to_dict(),
                    ),
                )
            )
            pruned = self._prune_phase_results(working)

        # Keep validation live in this method: publication never returns a pointer
        # whose four envelopes were merely assumed to exist.
        assert len(results) == len(M11_PHASES)
        return _publication_value(working, pruned, reused=False)

    def select(self, canonical: Mapping[str, object]) -> M11Selection:
        """Select only one coherent complete publication for the current M10 graph."""

        current = self._authority(canonical)
        try:
            state = self._read_state()
        except storage.ProjectStorageError:
            return M11Selection(M11Availability.UNAVAILABLE, "m11_state_invalid")
        if state is None or state.published is None:
            return M11Selection(M11Availability.UNAVAILABLE, "m11_not_published")
        published = state.published
        if published.canonical != current:
            return M11Selection(
                M11Availability.UNAVAILABLE,
                "canonical_binding_mismatch",
                published.canonical,
                published.binding_hash,
            )
        try:
            results = self._load_complete_results(published)
        except storage.ProjectStorageError:
            return M11Selection(
                M11Availability.UNAVAILABLE,
                "m11_published_result_invalid",
            )
        return M11Selection(
            M11Availability.CURRENT_COMPLETE,
            "current_complete",
            published.canonical,
            published.binding_hash,
            results,
        )

    def select_current(
        self,
        *,
        source_generation: str,
        canonical_schema: str,
        canonical_hash: str,
    ) -> M11Selection:
        """Select a current publication from scalar M10 identity fields only."""

        try:
            current = CanonicalBinding(
                source_generation,
                canonical_schema,
                canonical_hash,
            )
            state = self._read_state()
        except (ValueError, storage.ProjectStorageError):
            return M11Selection(M11Availability.UNAVAILABLE, "m11_state_invalid")
        if state is None or state.published is None:
            return M11Selection(M11Availability.UNAVAILABLE, "m11_not_published")
        published = state.published
        if published.canonical != current:
            return M11Selection(
                M11Availability.UNAVAILABLE,
                "canonical_binding_mismatch",
                published.canonical,
                published.binding_hash,
            )
        try:
            results = self._load_complete_results(published)
        except storage.ProjectStorageError:
            return M11Selection(M11Availability.UNAVAILABLE, "m11_published_result_invalid")
        return M11Selection(
            M11Availability.CURRENT_COMPLETE,
            "current_complete",
            published.canonical,
            published.binding_hash,
            results,
        )

    def analysis_state(self) -> Mapping[str, object] | None:
        """Return a validated state payload for progress reporting."""

        state = self._read_state()
        return None if state is None else state.to_dict()

    def has_current_publication(
        self,
        *,
        source_generation: str,
        canonical_schema: str,
        canonical_hash: str,
    ) -> bool:
        """Check the small persisted binding without decoding M10 or phase payloads.

        This is the unchanged-project fast path. Full envelope validation remains in
        :meth:`select` before a phase result is served.
        """

        try:
            current = CanonicalBinding(
                source_generation,
                canonical_schema,
                canonical_hash,
            )
            state = self._read_state()
        except (ValueError, storage.ProjectStorageError):
            return False
        if (
            state is None
            or state.published is None
            or state.published.canonical != current
            or not state.published.complete
        ):
            return False
        expected_keys = {pointer.record_key for pointer in state.published.phases}
        rows = self._project._require_open().execute(
            """SELECT record_key,payload_hash FROM payloads
                 WHERE collection=? ORDER BY record_key""",
            (PHASE_RESULTS_COLLECTION,),
        )
        actual: dict[str, str] = {
            str(row["record_key"]): str(row["payload_hash"]) for row in rows
        }
        return set(actual) == expected_keys and all(
            len(payload_hash) == 64 for payload_hash in actual.values()
        )

    def save_corrections(
        self,
        canonical: Mapping[str, object],
        corrections: Mapping[str, object],
        *,
        expected_corrections_hash: str | None = None,
    ) -> CorrectionWrite:
        """Persist a small overlay bound to the exact current published model."""

        if expected_corrections_hash is not None:
            _require_hash(expected_corrections_hash, "expected_corrections_hash")
        selection = self.select(canonical)
        if (
            selection.availability is not M11Availability.CURRENT_COMPLETE
            or selection.canonical is None
            or selection.model_hash is None
        ):
            raise M11PreconditionError("corrections require a current complete M11 publication")
        correction_value = dict(corrections)
        correction_hash = _content_hash(correction_value)
        record_key = selection.model_hash
        existing = self._project.payload(CORRECTIONS_COLLECTION, record_key)
        if existing is not None:
            prior = _decode_corrections(
                existing,
                selection.canonical,
                selection.model_hash,
            )
            prior_hash = _content_hash(prior)
            if (
                expected_corrections_hash is not None
                and prior_hash != expected_corrections_hash
            ):
                raise M11PreconditionError("correction overlay changed before replacement")
            if prior == correction_value:
                return CorrectionWrite(record_key, correction_hash, reused=True)
        elif expected_corrections_hash is not None:
            raise M11PreconditionError("correction overlay no longer exists")

        envelope = {
            "schema": CORRECTIONS_SCHEMA,
            **selection.canonical.to_dict(),
            "published_model_hash": selection.model_hash,
            "corrections_hash": correction_hash,
            "corrections": correction_value,
        }
        self._project.write_payloads(
            (PayloadRecord(CORRECTIONS_COLLECTION, record_key, envelope),)
        )
        return CorrectionWrite(record_key, correction_hash, reused=False)

    def corrections(
        self,
        canonical: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        """Load only the overlay bound to the exact current publication."""

        selection = self.select(canonical)
        if (
            selection.availability is not M11Availability.CURRENT_COMPLETE
            or selection.canonical is None
            or selection.model_hash is None
        ):
            return None
        raw = self._project.payload(CORRECTIONS_COLLECTION, selection.model_hash)
        if raw is None:
            return None
        return _decode_corrections(raw, selection.canonical, selection.model_hash)

    def _read_state(self) -> _AnalysisState | None:
        raw = self._project.payload(ANALYSIS_STATE_COLLECTION, ANALYSIS_STATE_KEY)
        if raw is None:
            return None
        try:
            root = _require_mapping(raw, "M11 analysis state")
            _require_exact_keys(root, {"schema", "working", "published"}, "M11 analysis state")
            if root["schema"] != ANALYSIS_STATE_SCHEMA:
                raise ValueError("M11 analysis state schema is unsupported")
            working = _decode_build_binding(root["working"], "working")
            published_value = root["published"]
            published = (
                None
                if published_value is None
                else _decode_build_binding(published_value, "published")
            )
            if published is not None and not published.complete:
                raise ValueError("published M11 binding is incomplete")
            return _AnalysisState(working, published)
        except (KeyError, TypeError, ValueError) as exc:
            raise storage.ProjectCorruptError("M11 analysis state is invalid") from exc

    def _reused_checkpoint(
        self,
        state: _AnalysisState | None,
        authority: CanonicalBinding,
        pointer: PhasePointer,
        expected_working_hash: str | None,
    ) -> PhaseCheckpoint | None:
        if state is None or state.working.canonical != authority:
            return None
        if (
            expected_working_hash is not None
            and state.working.binding_hash != expected_working_hash
        ):
            raise M11PreconditionError("working M11 binding changed before checkpoint")
        phase_index = M11_PHASES.index(pointer.phase)
        if phase_index >= len(state.working.phases):
            return None
        if state.working.phases[phase_index] != pointer:
            return None
        self._load_phase_envelope(authority, pointer)
        return _checkpoint_value(pointer, state.working.binding_hash, reused=True)

    def _publication_binding_preconditions(
        self,
        state: _AnalysisState | None,
        authority: CanonicalBinding,
        expected_working_hash: str,
        expected_phase_hashes: Mapping[str, str],
    ) -> BuildBinding:
        if state is None or state.working.canonical != authority:
            raise M11PreconditionError("no working M11 binding matches the canonical graph")
        working = state.working
        if working.binding_hash != expected_working_hash:
            raise M11PreconditionError("working M11 binding changed before publication")
        if not working.complete:
            raise M11PreconditionError("all four M11 phases must complete before publication")
        actual = {pointer.phase: pointer.result_hash for pointer in working.phases}
        if actual != dict(expected_phase_hashes):
            raise M11PreconditionError("M11 phase hash preconditions do not match working state")
        return working

    def _load_complete_results(
        self,
        binding: BuildBinding,
    ) -> Mapping[str, Mapping[str, object]]:
        if not binding.complete:
            raise storage.ProjectCorruptError("M11 published binding is incomplete")
        return {
            pointer.phase: self._load_phase_envelope(binding.canonical, pointer)
            for pointer in binding.phases
        }

    def _load_phase_envelope(
        self,
        authority: CanonicalBinding,
        pointer: PhasePointer,
    ) -> Mapping[str, object]:
        raw = self._project.payload(PHASE_RESULTS_COLLECTION, pointer.record_key)
        if raw is None:
            raise storage.ProjectCorruptError("M11 phase binding points to a missing result")
        return _decode_phase_envelope(raw, authority, pointer)

    def _prune_phase_results(self, binding: BuildBinding) -> int:
        referenced = tuple(pointer.record_key for pointer in binding.phases)
        placeholders = ",".join("?" for _ in referenced)
        cursor = self._project._require_open().execute(
            f"""DELETE FROM payloads
                 WHERE collection=? AND record_key NOT IN ({placeholders})""",
            (PHASE_RESULTS_COLLECTION, *referenced),
        )
        return max(0, cursor.rowcount)

    def _has_unreferenced_phase_results(self, binding: BuildBinding) -> bool:
        referenced = tuple(pointer.record_key for pointer in binding.phases)
        placeholders = ",".join("?" for _ in referenced)
        row = self._project._require_open().execute(
            f"""SELECT 1 FROM payloads
                 WHERE collection=? AND record_key NOT IN ({placeholders}) LIMIT 1""",
            (PHASE_RESULTS_COLLECTION, *referenced),
        ).fetchone()
        return row is not None


def _phase_envelope(
    authority: CanonicalBinding,
    pointer: PhasePointer,
    result: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema": PHASE_RESULT_SCHEMA,
        "phase": pointer.phase,
        "input_hash": pointer.input_hash,
        **authority.to_dict(),
        "result_hash": pointer.result_hash,
        "result": dict(result),
    }


def _decode_phase_envelope(
    value: object,
    authority: CanonicalBinding,
    pointer: PhasePointer,
) -> Mapping[str, object]:
    try:
        root = _require_mapping(value, "M11 phase envelope")
        _require_exact_keys(
            root,
            {
                "schema",
                "phase",
                "input_hash",
                "source_generation",
                "canonical_schema",
                "canonical_hash",
                "result_hash",
                "result",
            },
            "M11 phase envelope",
        )
        expected_scalars: Mapping[str, object] = {
            "schema": PHASE_RESULT_SCHEMA,
            "phase": pointer.phase,
            "input_hash": pointer.input_hash,
            **authority.to_dict(),
            "result_hash": pointer.result_hash,
        }
        if any(root.get(key) != expected for key, expected in expected_scalars.items()):
            raise ValueError("M11 phase envelope binding does not match its pointer")
        result = _require_mapping(root["result"], "M11 phase result")
        result_value = dict(result)
        if _content_hash(result_value) != pointer.result_hash:
            raise ValueError("M11 phase result hash does not match its content")
        return result_value
    except (KeyError, TypeError, ValueError) as exc:
        raise storage.ProjectCorruptError("M11 phase envelope is invalid") from exc


def _decode_build_binding(value: object, name: str) -> BuildBinding:
    root = _require_mapping(value, f"M11 {name} binding")
    _require_exact_keys(
        root,
        {
            "source_generation",
            "canonical_schema",
            "canonical_hash",
            "phases",
            "binding_hash",
        },
        f"M11 {name} binding",
    )
    generation = root["source_generation"]
    schema = root["canonical_schema"]
    canonical_hash = root["canonical_hash"]
    binding_hash = root["binding_hash"]
    identity = (generation, schema, canonical_hash, binding_hash)
    if not all(isinstance(item, str) for item in identity):
        raise ValueError(f"M11 {name} binding identity is invalid")
    canonical = CanonicalBinding(
        str(generation),
        str(schema),
        str(canonical_hash),
    )
    phase_values = root["phases"]
    if not isinstance(phase_values, list):
        raise ValueError(f"M11 {name} phases must be a list")
    phases = tuple(_decode_phase_pointer(item) for item in phase_values)
    return BuildBinding(canonical, phases, str(binding_hash))


def _decode_phase_pointer(value: object) -> PhasePointer:
    root = _require_mapping(value, "M11 phase pointer")
    _require_exact_keys(
        root,
        {"phase", "input_hash", "record_key", "result_hash"},
        "M11 phase pointer",
    )
    values = tuple(root[key] for key in ("phase", "input_hash", "record_key", "result_hash"))
    if not all(isinstance(item, str) for item in values):
        raise ValueError("M11 phase pointer fields must be strings")
    return PhasePointer(*(str(item) for item in values))


def _decode_corrections(
    value: object,
    authority: CanonicalBinding,
    model_hash: str,
) -> Mapping[str, object]:
    try:
        root = _require_mapping(value, "M11 corrections")
        _require_exact_keys(
            root,
            {
                "schema",
                "source_generation",
                "canonical_schema",
                "canonical_hash",
                "published_model_hash",
                "corrections_hash",
                "corrections",
            },
            "M11 corrections",
        )
        expected: Mapping[str, object] = {
            "schema": CORRECTIONS_SCHEMA,
            **authority.to_dict(),
            "published_model_hash": model_hash,
        }
        if any(root.get(key) != item for key, item in expected.items()):
            raise ValueError("M11 corrections are bound to a different publication")
        correction_hash = root["corrections_hash"]
        if not isinstance(correction_hash, str):
            raise ValueError("M11 corrections hash is invalid")
        _require_hash(correction_hash, "corrections_hash")
        corrections = dict(_require_mapping(root["corrections"], "M11 correction payload"))
        if _content_hash(corrections) != correction_hash:
            raise ValueError("M11 corrections hash does not match its content")
        return corrections
    except (KeyError, TypeError, ValueError) as exc:
        raise storage.ProjectCorruptError("M11 corrections are invalid") from exc


def _checkpoint_value(
    pointer: PhasePointer,
    working_hash: str,
    *,
    reused: bool,
) -> PhaseCheckpoint:
    return PhaseCheckpoint(
        pointer.phase,
        pointer.input_hash,
        pointer.result_hash,
        pointer.record_key,
        working_hash,
        reused,
    )


def _publication_value(
    binding: BuildBinding,
    pruned: int,
    *,
    reused: bool,
) -> Publication:
    return Publication(
        binding.canonical,
        binding.binding_hash,
        {pointer.phase: pointer.result_hash for pointer in binding.phases},
        pruned,
        reused,
    )


def _build_binding_hash(
    canonical: CanonicalBinding,
    phases: Sequence[PhasePointer],
) -> str:
    return _content_hash(
        {
            **canonical.to_dict(),
            "phases": [item.to_dict() for item in phases],
        }
    )


def _expected_phase_hashes(value: Mapping[str, str]) -> Mapping[str, str]:
    if set(value) != set(M11_PHASES):
        raise M11PreconditionError("phase hash preconditions must name exactly four M11 phases")
    result = {phase: value[phase] for phase in M11_PHASES}
    for phase, item in result.items():
        _require_hash(item, f"expected hash for {phase}")
    return result


def _validate_phase_prefix(phases: Sequence[PhasePointer]) -> None:
    actual = tuple(item.phase for item in phases)
    if actual != M11_PHASES[: len(actual)]:
        raise ValueError("M11 build phases must be an ordered prefix of the four declared phases")


def _require_phase(phase: str) -> None:
    if phase not in M11_PHASES:
        raise ValueError(f"unknown M11 phase {phase!r}")


def _require_hash(value: str, name: str) -> None:
    if not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _content_hash(value: object) -> str:
    return hashlib.sha256(storage.canonical_json(value)).hexdigest()


def _require_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    name: str,
) -> None:
    if set(value) != expected:
        raise ValueError(f"{name} fields are invalid")
