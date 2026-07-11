"""Transactional story-organization domain model over deterministic project facts.

This module stores organization, interpretation, and user-edit metadata only. Authoritative
connectivity, facts, evidence, and dialogue remain owned by the M01-M04 tables and payloads.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, cast

from renpy_story_mapper import storage

if TYPE_CHECKING:
    from renpy_story_mapper.project import Project

RunStatus = Literal["running", "completed", "failed", "cancelled"]
ApprovalState = Literal["pending", "approved", "rejected"]
DraftDecision = Literal["approved", "rejected"]
EditOperation = Literal["rename", "split", "merge", "move", "hide", "pin", "approve", "reject"]

_SHA256_LENGTH: Final = 64
_SUPPORTED_ORIGINS: Final = frozenset({"ai", "deterministic", "user"})
_REQUIRED_STORY_KINDS: Final = frozenset(
    {"narrative", "dialogue", "narration", "choice", "condition"}
)


@dataclass(frozen=True)
class CacheIdentity:
    provider_mode: str
    model_profile: str
    model_fingerprint: str
    prompt_version: str
    output_schema_version: str
    input_hash: str
    ordered_ids_hash: str

    @property
    def key(self) -> str:
        return _stable_id(
            "cache",
            self.provider_mode,
            self.model_profile,
            self.model_fingerprint,
            self.prompt_version,
            self.output_schema_version,
            self.input_hash,
            self.ordered_ids_hash,
        )


@dataclass(frozen=True)
class OrganizationRun:
    id: str
    provider_mode: str
    model_profile: str
    model_fingerprint: str | None
    prompt_version: str
    output_schema_version: str
    generation: str
    status: str
    started_utc: str
    completed_utc: str | None
    elapsed_ms: int | None
    usage: object
    sanitized_failure: str | None


@dataclass(frozen=True)
class OrganizationChunk:
    id: str
    run_id: str
    scope_id: str
    reconciliation_scope: str
    ordinal: int
    input_hash: str
    ordered_ids_hash: str
    cache_key: str | None
    cache_state: str
    status: str
    result: object | None


@dataclass(frozen=True)
class OrganizationDraft:
    id: str
    run_id: str
    generation: str
    status: str
    candidate: object
    created_utc: str
    resolved_utc: str | None


@dataclass(frozen=True)
class DraftReview:
    draft_id: str
    target_kind: str
    target_id: str
    decision: str
    reviewed_utc: str


@dataclass(frozen=True)
class StoryArc:
    id: str
    title: str
    summary: str
    order: int
    origin: str
    pinned: bool
    hidden: bool
    approval_state: str
    needs_review: bool
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class StoryEvent:
    id: str
    title: str
    summary: str
    order: int
    origin: str
    pinned: bool
    hidden: bool
    approval_state: str
    needs_review: bool
    beat_ids: tuple[str, ...]


@dataclass(frozen=True)
class StoryEdge:
    id: str
    source_id: str
    target_id: str
    kind: str
    transition_ids: tuple[str, ...]


@dataclass(frozen=True)
class AttachedFact:
    event_id: str
    fact_id: str
    fact_kind: str
    expression: str
    status: str
    source_path: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class StoryClaim:
    id: str
    event_id: str | None
    arc_id: str | None
    text: str
    kind: str
    status: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class StoryEdit:
    id: str
    operation: str
    target_kind: str
    target_id: str
    payload: object
    status: str
    created_utc: str


class StoryOrganizationService:
    """Normalized query and mutation API for schema-v4 organization data."""

    def __init__(self, project: Project) -> None:
        self._project = project

    @property
    def _connection(self) -> sqlite3.Connection:
        return self._project._require_open()

    def create_run(
        self,
        *,
        provider_mode: str,
        model_profile: str,
        model_fingerprint: str | None,
        prompt_version: str,
        output_schema_version: str,
        generation: str,
        run_id: str | None = None,
    ) -> str:
        values = (provider_mode, model_profile, prompt_version, output_schema_version, generation)
        if any(not value.strip() for value in values):
            raise ValueError("run identity values cannot be empty")
        identifier = run_id or uuid.uuid4().hex
        with storage.transaction(self._connection):
            self._connection.execute(
                """INSERT INTO organization_runs(
                    run_id,provider_mode,model_profile,model_fingerprint,prompt_version,
                    output_schema_version,generation,status,started_utc,usage_json
                ) VALUES (?,?,?,?,?,?,?,'running',?,?)""",
                (
                    identifier,
                    provider_mode,
                    model_profile,
                    model_fingerprint,
                    prompt_version,
                    output_schema_version,
                    generation,
                    storage.utc_now(),
                    storage.canonical_json({}),
                ),
            )
        return identifier

    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        *,
        elapsed_ms: int,
        usage: object | None = None,
        sanitized_failure: str | None = None,
    ) -> None:
        if status == "running":
            raise ValueError("finish_run requires a terminal status")
        if elapsed_ms < 0:
            raise ValueError("elapsed_ms cannot be negative")
        failure = _sanitize_failure(sanitized_failure)
        if status in {"failed", "cancelled"} and failure is None:
            failure = "Organization did not complete."
        with storage.transaction(self._connection):
            cursor = self._connection.execute(
                """UPDATE organization_runs SET status=?,completed_utc=?,elapsed_ms=?,
                    usage_json=?,sanitized_failure=? WHERE run_id=? AND status='running'""",
                (
                    status,
                    storage.utc_now(),
                    elapsed_ms,
                    storage.canonical_json({} if usage is None else usage),
                    failure,
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"running organization run does not exist: {run_id}")

    def runs(self) -> tuple[OrganizationRun, ...]:
        rows = self._connection.execute(
            "SELECT * FROM organization_runs ORDER BY started_utc,run_id"
        ).fetchall()
        return tuple(
            OrganizationRun(
                id=str(row["run_id"]),
                provider_mode=str(row["provider_mode"]),
                model_profile=str(row["model_profile"]),
                model_fingerprint=_optional_text(row["model_fingerprint"]),
                prompt_version=str(row["prompt_version"]),
                output_schema_version=str(row["output_schema_version"]),
                generation=str(row["generation"]),
                status=str(row["status"]),
                started_utc=str(row["started_utc"]),
                completed_utc=_optional_text(row["completed_utc"]),
                elapsed_ms=None if row["elapsed_ms"] is None else int(row["elapsed_ms"]),
                usage=storage.decode_json(row["usage_json"]),
                sanitized_failure=_optional_text(row["sanitized_failure"]),
            )
            for row in rows
        )

    def cache_identity(
        self,
        *,
        provider_mode: str,
        model_profile: str,
        model_fingerprint: str,
        prompt_version: str,
        output_schema_version: str,
        input_hash: str,
        ordered_ids: Sequence[str],
    ) -> CacheIdentity:
        _require_digest(input_hash, "input_hash")
        if not model_profile.strip():
            raise ValueError("model_profile cannot be empty")
        ordered_hash = hashlib.sha256(storage.canonical_json(list(ordered_ids))).hexdigest()
        return CacheIdentity(
            provider_mode,
            model_profile,
            model_fingerprint,
            prompt_version,
            output_schema_version,
            input_hash,
            ordered_hash,
        )

    def cache_result(self, identity: CacheIdentity) -> object | None:
        row = self._connection.execute(
            """SELECT result_json,result_hash FROM organization_cache
               WHERE cache_key=? AND provider_mode=? AND model_profile=? AND model_fingerprint=?
                 AND prompt_version=? AND output_schema_version=? AND input_hash=?
                 AND ordered_ids_hash=?""",
            (
                identity.key,
                identity.provider_mode,
                identity.model_profile,
                identity.model_fingerprint,
                identity.prompt_version,
                identity.output_schema_version,
                identity.input_hash,
                identity.ordered_ids_hash,
            ),
        ).fetchone()
        if row is None:
            return None
        payload = bytes(row["result_json"])
        if storage.payload_digest(payload) != str(row["result_hash"]):
            raise storage.ProjectCorruptError("organization cache checksum does not match")
        with storage.transaction(self._connection):
            self._connection.execute(
                "UPDATE organization_cache SET hit_count=hit_count+1,last_used_utc=? "
                "WHERE cache_key=?",
                (storage.utc_now(), identity.key),
            )
        return storage.decode_json(payload)

    def store_cache_result(self, identity: CacheIdentity, result: object) -> str:
        _reject_authority_fields(result)
        payload = storage.canonical_json(result)
        digest = storage.payload_digest(payload)
        now = storage.utc_now()
        with storage.transaction(self._connection):
            self._connection.execute(
                """INSERT INTO organization_cache(
                    cache_key,provider_mode,model_profile,model_fingerprint,prompt_version,
                    output_schema_version,
                    input_hash,ordered_ids_hash,result_json,result_hash,created_utc,last_used_utc,hit_count
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)
                ON CONFLICT(cache_key) DO UPDATE SET result_json=excluded.result_json,
                    result_hash=excluded.result_hash,last_used_utc=excluded.last_used_utc""",
                (
                    identity.key,
                    identity.provider_mode,
                    identity.model_profile,
                    identity.model_fingerprint,
                    identity.prompt_version,
                    identity.output_schema_version,
                    identity.input_hash,
                    identity.ordered_ids_hash,
                    payload,
                    digest,
                    now,
                    now,
                ),
            )
        return identity.key

    def record_chunk(
        self,
        *,
        run_id: str,
        scope_id: str,
        reconciliation_scope: str,
        ordinal: int,
        identity: CacheIdentity,
        cache_state: Literal["miss", "hit", "stored", "bypassed"],
        status: Literal["pending", "validated", "rejected", "failed", "cancelled"],
        result: object | None = None,
        chunk_id: str | None = None,
    ) -> str:
        if ordinal < 0:
            raise ValueError("chunk ordinal cannot be negative")
        if result is not None:
            _reject_authority_fields(result)
        payload = None if result is None else storage.canonical_json(result)
        digest = None if payload is None else storage.payload_digest(payload)
        identifier = chunk_id or _stable_id("chunk", run_id, str(ordinal), identity.input_hash)
        cache_key = identity.key if self._cache_exists(identity.key) else None
        with storage.transaction(self._connection):
            self._connection.execute(
                """INSERT INTO organization_chunks(
                    chunk_id,run_id,scope_id,reconciliation_scope,ordinal,input_hash,
                    ordered_ids_hash,cache_key,cache_state,status,result_json,result_hash
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    identifier,
                    run_id,
                    scope_id,
                    reconciliation_scope,
                    ordinal,
                    identity.input_hash,
                    identity.ordered_ids_hash,
                    cache_key,
                    cache_state,
                    status,
                    payload,
                    digest,
                ),
            )
        return identifier

    def chunks(self, run_id: str | None = None) -> tuple[OrganizationChunk, ...]:
        clause = "" if run_id is None else "WHERE run_id=?"
        parameters: tuple[object, ...] = () if run_id is None else (run_id,)
        rows = self._connection.execute(
            f"SELECT * FROM organization_chunks {clause} ORDER BY run_id,ordinal,chunk_id",
            parameters,
        ).fetchall()
        result: list[OrganizationChunk] = []
        for row in rows:
            payload = None if row["result_json"] is None else bytes(row["result_json"])
            if payload is not None and storage.payload_digest(payload) != str(row["result_hash"]):
                raise storage.ProjectCorruptError("organization chunk checksum does not match")
            result.append(
                OrganizationChunk(
                    str(row["chunk_id"]),
                    str(row["run_id"]),
                    str(row["scope_id"]),
                    str(row["reconciliation_scope"]),
                    int(row["ordinal"]),
                    str(row["input_hash"]),
                    str(row["ordered_ids_hash"]),
                    _optional_text(row["cache_key"]),
                    str(row["cache_state"]),
                    str(row["status"]),
                    None if payload is None else storage.decode_json(payload),
                )
            )
        return tuple(result)

    def create_draft(self, run_id: str, generation: str, candidate: Mapping[str, object]) -> str:
        payload = storage.canonical_json(dict(candidate))
        identifier = _stable_id("draft", run_id, storage.payload_digest(payload))
        with storage.transaction(self._connection):
            self._validate_candidate(candidate)
            self._connection.execute(
                """INSERT INTO organization_drafts(
                    draft_id,run_id,generation,status,candidate_json,candidate_hash,created_utc
                ) VALUES (?,?,?,'pending',?,?,?)""",
                (
                    identifier,
                    run_id,
                    generation,
                    payload,
                    storage.payload_digest(payload),
                    storage.utc_now(),
                ),
            )
        return identifier

    def discard_draft(self, draft_id: str) -> None:
        with storage.transaction(self._connection):
            cursor = self._connection.execute(
                """UPDATE organization_drafts SET status='discarded',resolved_utc=?
                   WHERE draft_id=? AND status='pending'""",
                (storage.utc_now(), draft_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"pending organization draft does not exist: {draft_id}")

    def drafts(self, *, status: str | None = None) -> tuple[OrganizationDraft, ...]:
        clause = "" if status is None else "WHERE status=?"
        parameters: tuple[object, ...] = () if status is None else (status,)
        rows = self._connection.execute(
            f"SELECT * FROM organization_drafts {clause} ORDER BY created_utc,draft_id",
            parameters,
        ).fetchall()
        result: list[OrganizationDraft] = []
        for row in rows:
            payload = bytes(row["candidate_json"])
            if storage.payload_digest(payload) != str(row["candidate_hash"]):
                raise storage.ProjectCorruptError("organization draft checksum does not match")
            result.append(
                OrganizationDraft(
                    str(row["draft_id"]),
                    str(row["run_id"]),
                    str(row["generation"]),
                    str(row["status"]),
                    storage.decode_json(payload),
                    str(row["created_utc"]),
                    _optional_text(row["resolved_utc"]),
                )
            )
        return tuple(result)

    def review_draft_group(
        self,
        draft_id: str,
        target_kind: Literal["arc", "event"],
        target_id: str,
        decision: DraftDecision,
    ) -> None:
        """Persist an explicit pre-apply decision for one candidate arc or event."""

        with storage.transaction(self._connection):
            candidate = self._pending_draft_candidate(draft_id)
            collection = "arcs" if target_kind == "arc" else "events"
            identifiers = {
                cast(str, item["id"])
                for item in _object_list(candidate.get(collection), collection)
            }
            if target_id not in identifiers:
                raise KeyError(f"candidate {target_kind} does not exist: {target_id}")
            self._connection.execute(
                """INSERT INTO organization_draft_reviews(
                    draft_id,target_kind,target_id,decision,reviewed_utc
                ) VALUES (?,?,?,?,?)
                ON CONFLICT(draft_id,target_kind,target_id) DO UPDATE SET
                    decision=excluded.decision,reviewed_utc=excluded.reviewed_utc""",
                (draft_id, target_kind, target_id, decision, storage.utc_now()),
            )

    def draft_reviews(self, draft_id: str) -> tuple[DraftReview, ...]:
        rows = self._connection.execute(
            """SELECT * FROM organization_draft_reviews WHERE draft_id=?
               ORDER BY target_kind,target_id""",
            (draft_id,),
        ).fetchall()
        return tuple(
            DraftReview(
                str(row["draft_id"]),
                str(row["target_kind"]),
                str(row["target_id"]),
                str(row["decision"]),
                str(row["reviewed_utc"]),
            )
            for row in rows
        )

    def apply_draft(self, draft_id: str) -> None:
        """Atomically replace unpinned accepted organization with a validated draft."""

        with storage.transaction(self._connection):
            row = self._connection.execute(
                """SELECT generation,candidate_json,candidate_hash FROM organization_drafts
                   WHERE draft_id=? AND status='pending'""",
                (draft_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"pending organization draft does not exist: {draft_id}")
            payload = bytes(row["candidate_json"])
            if storage.payload_digest(payload) != str(row["candidate_hash"]):
                raise storage.ProjectCorruptError("organization draft checksum does not match")
            candidate = _mapping(storage.decode_json(payload), "draft")
            self._validate_candidate(candidate)
            reviews = {
                (str(review["target_kind"]), str(review["target_id"])): str(review["decision"])
                for review in self._connection.execute(
                    "SELECT target_kind,target_id,decision FROM organization_draft_reviews "
                    "WHERE draft_id=?",
                    (draft_id,),
                )
            }
            reviewed = self._reviewed_candidate(candidate, reviews)
            self._apply_candidate(reviewed, str(row["generation"]))
            self._derive_event_edges()
            self._connection.execute(
                "UPDATE organization_drafts SET status='applied',resolved_utc=? WHERE draft_id=?",
                (storage.utc_now(), draft_id),
            )

    def arcs(self, *, include_hidden: bool = False) -> tuple[StoryArc, ...]:
        clause = "" if include_hidden else "WHERE a.hidden=0"
        rows = self._connection.execute(
            f"SELECT a.* FROM story_arcs a {clause} ORDER BY a.sort_order,a.arc_id"
        ).fetchall()
        return tuple(
            StoryArc(
                str(row["arc_id"]),
                str(row["title"]),
                str(row["summary"]),
                int(row["sort_order"]),
                str(row["origin"]),
                bool(row["pinned"]),
                bool(row["hidden"]),
                str(row["approval_state"]),
                bool(row["needs_review"]),
                self._arc_member_ids(str(row["arc_id"])),
            )
            for row in rows
        )

    def events(
        self, *, arc_id: str | None = None, include_hidden: bool = False
    ) -> tuple[StoryEvent, ...]:
        clauses: list[str] = []
        parameters: list[object] = []
        join = ""
        if arc_id is not None:
            join = "JOIN story_arc_members am ON am.event_id=e.event_id"
            clauses.append("am.arc_id=?")
            parameters.append(arc_id)
        if not include_hidden:
            clauses.append("e.hidden=0")
        where = "" if not clauses else "WHERE " + " AND ".join(clauses)
        order_by = "am.ordinal,e.event_id" if arc_id is not None else "e.sort_order,e.event_id"
        rows = self._connection.execute(
            f"""SELECT e.* FROM story_events e {join}
                {where} ORDER BY {order_by}""",
            parameters,
        ).fetchall()
        return tuple(
            StoryEvent(
                str(row["event_id"]),
                str(row["title"]),
                str(row["summary"]),
                int(row["sort_order"]),
                str(row["origin"]),
                bool(row["pinned"]),
                bool(row["hidden"]),
                str(row["approval_state"]),
                bool(row["needs_review"]),
                self._member_ids(str(row["event_id"])),
            )
            for row in rows
        )

    def event_edges(self) -> tuple[StoryEdge, ...]:
        rows = self._connection.execute(
            "SELECT * FROM story_event_edges ORDER BY source_event_id,target_event_id,kind"
        ).fetchall()
        return tuple(
            StoryEdge(
                str(row["edge_id"]),
                str(row["source_event_id"]),
                str(row["target_event_id"]),
                str(row["kind"]),
                tuple(cast(list[str], storage.decode_json(row["transition_ids_json"]))),
            )
            for row in rows
        )

    def arc_edges(self) -> tuple[StoryEdge, ...]:
        rows = self._connection.execute(
            """SELECT sm.arc_id AS source_id,tm.arc_id AS target_id,e.kind,
                      json_group_array(e.edge_id) AS edge_ids
               FROM story_event_edges e
               JOIN story_arc_members sm ON sm.event_id=e.source_event_id
               JOIN story_arc_members tm ON tm.event_id=e.target_event_id
               WHERE sm.arc_id<>tm.arc_id GROUP BY sm.arc_id,tm.arc_id,e.kind
               ORDER BY sm.arc_id,tm.arc_id,e.kind"""
        ).fetchall()
        return tuple(
            StoryEdge(
                _stable_id(
                    "arc-edge", str(row["source_id"]), str(row["target_id"]), str(row["kind"])
                ),
                str(row["source_id"]),
                str(row["target_id"]),
                str(row["kind"]),
                tuple(cast(list[str], storage.decode_json(str(row["edge_ids"])))),
            )
            for row in rows
        )

    def attached_facts(self, event_id: str | None = None) -> tuple[AttachedFact, ...]:
        clause = "" if event_id is None else "AND m.event_id=?"
        parameters: tuple[object, ...] = () if event_id is None else (event_id,)
        rows = self._connection.execute(
            f"""SELECT m.event_id,f.fact_id,f.fact_kind,f.expression,f.status,
                       f.source_path,f.start_line,f.end_line
                FROM story_event_members m JOIN presentation_facts f ON f.node_id=m.beat_id
                WHERE 1=1 {clause} ORDER BY m.event_id,m.ordinal,f.sort_key,f.fact_id""",
            parameters,
        ).fetchall()
        return tuple(
            AttachedFact(
                str(row["event_id"]),
                str(row["fact_id"]),
                str(row["fact_kind"]),
                str(row["expression"]),
                str(row["status"]),
                str(row["source_path"]),
                int(row["start_line"]),
                int(row["end_line"]),
            )
            for row in rows
        )

    def claims(self, *, event_id: str | None = None) -> tuple[StoryClaim, ...]:
        clause = "" if event_id is None else "WHERE c.event_id=?"
        parameters: tuple[object, ...] = () if event_id is None else (event_id,)
        rows = self._connection.execute(
            f"""SELECT c.* FROM story_claims c {clause}
                ORDER BY c.sort_order,c.claim_id""",
            parameters,
        ).fetchall()
        return tuple(
            StoryClaim(
                str(row["claim_id"]),
                _optional_text(row["event_id"]),
                _optional_text(row["arc_id"]),
                str(row["text"]),
                str(row["claim_kind"]),
                str(row["status"]),
                tuple(
                    str(item[0])
                    for item in self._connection.execute(
                        "SELECT evidence_id FROM story_claim_evidence "
                        "WHERE claim_id=? ORDER BY evidence_id",
                        (str(row["claim_id"]),),
                    )
                ),
            )
            for row in rows
        )

    def edits(self, target_id: str | None = None) -> tuple[StoryEdit, ...]:
        clause = "" if target_id is None else "WHERE target_id=?"
        parameters: tuple[object, ...] = () if target_id is None else (target_id,)
        rows = self._connection.execute(
            f"SELECT * FROM story_edits {clause} ORDER BY created_utc,edit_id", parameters
        ).fetchall()
        return tuple(
            StoryEdit(
                str(row["edit_id"]),
                str(row["operation"]),
                str(row["target_kind"]),
                str(row["target_id"]),
                storage.decode_json(row["payload_json"]),
                str(row["status"]),
                str(row["created_utc"]),
            )
            for row in rows
        )

    def cache_entry_count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) FROM organization_cache").fetchone()
        assert row is not None
        return int(row[0])

    def rename(self, target_kind: Literal["arc", "event"], target_id: str, title: str) -> None:
        if not title.strip() or len(title) > 80:
            raise ValueError("title must contain 1-80 characters")
        table, key = _target_table(target_kind)
        with storage.transaction(self._connection):
            cursor = self._connection.execute(
                f"UPDATE {table} SET title=?,pinned=1,updated_utc=? WHERE {key}=?",
                (title, storage.utc_now(), target_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"{target_kind} does not exist: {target_id}")
            self._insert_edit("rename", target_kind, target_id, {"title": title})

    def set_hidden(
        self, target_kind: Literal["arc", "event"], target_id: str, hidden: bool
    ) -> None:
        self._update_flag("hide", target_kind, target_id, "hidden", hidden)

    def set_pinned(
        self, target_kind: Literal["arc", "event"], target_id: str, pinned: bool
    ) -> None:
        self._update_flag("pin", target_kind, target_id, "pinned", pinned)

    def set_approval(
        self, target_kind: Literal["arc", "event"], target_id: str, state: ApprovalState
    ) -> None:
        operation: EditOperation = "reject" if state == "rejected" else "approve"
        table, key = _target_table(target_kind)
        with storage.transaction(self._connection):
            cursor = self._connection.execute(
                f"UPDATE {table} SET approval_state=?,updated_utc=? WHERE {key}=?",
                (state, storage.utc_now(), target_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"{target_kind} does not exist: {target_id}")
            self._insert_edit(operation, target_kind, target_id, {"state": state})

    def split_event(self, event_id: str, boundary_beat_id: str, *, new_title: str) -> str:
        """Split immediately before an existing deterministic beat boundary."""

        if not new_title.strip() or len(new_title) > 80:
            raise ValueError("new title must contain 1-80 characters")
        with storage.transaction(self._connection):
            event = self._connection.execute(
                "SELECT * FROM story_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if event is None:
                raise KeyError(f"event does not exist: {event_id}")
            members = self._member_ids(event_id)
            if boundary_beat_id not in members[1:]:
                raise ValueError("split must use an internal deterministic beat boundary")
            split_at = members.index(boundary_beat_id)
            left, right = members[:split_at], members[split_at:]
            new_id = _stable_id("user-event", event_id, boundary_beat_id)
            now = storage.utc_now()
            self._connection.execute(
                """INSERT INTO story_events VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    new_id,
                    new_title,
                    str(event["summary"]),
                    int(event["sort_order"]) + 1,
                    "user",
                    1,
                    0,
                    "approved",
                    0,
                    str(event["generation"]),
                    now,
                ),
            )
            self._replace_members(event_id, left)
            self._replace_members(new_id, right)
            arc = self._connection.execute(
                "SELECT arc_id,ordinal FROM story_arc_members WHERE event_id=?", (event_id,)
            ).fetchone()
            if arc is not None:
                self._shift_arc_members(str(arc["arc_id"]), int(arc["ordinal"]) + 1)
                self._connection.execute(
                    "INSERT INTO story_arc_members VALUES (?,?,?)",
                    (str(arc["arc_id"]), new_id, int(arc["ordinal"]) + 1),
                )
            self._connection.execute(
                "UPDATE story_events SET pinned=1,updated_utc=? WHERE event_id=?", (now, event_id)
            )
            self._insert_edit(
                "split", "event", event_id, {"boundary": boundary_beat_id, "new_id": new_id}
            )
            self._derive_event_edges()
        return new_id

    def merge_events(self, first_event_id: str, second_event_id: str, *, title: str) -> str:
        if first_event_id == second_event_id:
            raise ValueError("cannot merge an event with itself")
        if not title.strip() or len(title) > 80:
            raise ValueError("title must contain 1-80 characters")
        with storage.transaction(self._connection):
            rows = self._connection.execute(
                """SELECT arc_id,event_id,ordinal FROM story_arc_members
                   WHERE event_id IN (?,?) ORDER BY ordinal""",
                (first_event_id, second_event_id),
            ).fetchall()
            if len(rows) != 2 or str(rows[0]["arc_id"]) != str(rows[1]["arc_id"]):
                raise ValueError("events must belong to the same arc")
            if int(rows[1]["ordinal"]) != int(rows[0]["ordinal"]) + 1:
                raise ValueError("only contiguous events can be merged")
            keep = str(rows[0]["event_id"])
            remove = str(rows[1]["event_id"])
            members = (*self._member_ids(keep), *self._member_ids(remove))
            self._connection.execute("DELETE FROM story_arc_members WHERE event_id=?", (remove,))
            self._connection.execute("DELETE FROM story_events WHERE event_id=?", (remove,))
            self._replace_members(keep, members)
            self._connection.execute(
                "UPDATE story_events SET title=?,origin='user',pinned=1,updated_utc=? "
                "WHERE event_id=?",
                (title, storage.utc_now(), keep),
            )
            self._renumber_arc(str(rows[0]["arc_id"]))
            self._insert_edit("merge", "event", keep, {"removed_id": remove, "title": title})
            self._derive_event_edges()
        return keep

    def move_event(self, event_id: str, arc_id: str, ordinal: int) -> None:
        if ordinal < 0:
            raise ValueError("ordinal cannot be negative")
        with storage.transaction(self._connection):
            if (
                self._connection.execute(
                    "SELECT 1 FROM story_arcs WHERE arc_id=?", (arc_id,)
                ).fetchone()
                is None
            ):
                raise KeyError(f"arc does not exist: {arc_id}")
            old = self._connection.execute(
                "SELECT arc_id FROM story_arc_members WHERE event_id=?", (event_id,)
            ).fetchone()
            if old is None:
                raise KeyError(f"event does not belong to an arc: {event_id}")
            old_arc = str(old["arc_id"])
            self._connection.execute("DELETE FROM story_arc_members WHERE event_id=?", (event_id,))
            self._renumber_arc(old_arc)
            count_row = self._connection.execute(
                "SELECT COUNT(*) FROM story_arc_members WHERE arc_id=?", (arc_id,)
            ).fetchone()
            assert count_row is not None
            target = min(ordinal, int(count_row[0]))
            self._shift_arc_members(arc_id, target)
            self._connection.execute(
                "INSERT INTO story_arc_members VALUES (?,?,?)", (arc_id, event_id, target)
            )
            self._connection.execute(
                "UPDATE story_events SET pinned=1,updated_utc=? WHERE event_id=?",
                (storage.utc_now(), event_id),
            )
            self._insert_edit(
                "move", "event", event_id, {"from": old_arc, "to": arc_id, "ordinal": target}
            )

    def reconcile_after_refresh(self) -> tuple[str, ...]:
        """Retain broken edits and memberships while marking them for explicit review."""

        with storage.transaction(self._connection):
            rows = self._connection.execute(
                """SELECT DISTINCT m.event_id FROM story_event_members m
                   LEFT JOIN presentation_nodes n ON n.node_id=m.beat_id AND n.level=3
                   WHERE n.node_id IS NULL ORDER BY m.event_id"""
            ).fetchall()
            affected = tuple(str(row[0]) for row in rows)
            if affected:
                placeholders = ",".join("?" for _ in affected)
                self._connection.execute(
                    f"UPDATE story_events SET needs_review=1 WHERE event_id IN ({placeholders})",
                    affected,
                )
                self._connection.execute(
                    f"""UPDATE story_arcs SET needs_review=1 WHERE arc_id IN (
                        SELECT arc_id FROM story_arc_members WHERE event_id IN ({placeholders})
                    )""",
                    affected,
                )
                self._connection.execute(
                    f"""UPDATE story_edits SET status='needs_review' WHERE target_kind='event'
                        AND target_id IN ({placeholders})""",
                    affected,
                )
                self._connection.execute(
                    f"""UPDATE story_edits SET status='needs_review' WHERE target_kind='arc'
                        AND target_id IN (
                            SELECT arc_id FROM story_arc_members
                            WHERE event_id IN ({placeholders})
                        )""",
                    affected,
                )
            self._connection.execute(
                """UPDATE story_claims SET status='needs_review' WHERE claim_id IN (
                    SELECT ce.claim_id FROM story_claim_evidence ce
                    LEFT JOIN presentation_evidence e ON e.evidence_id=ce.evidence_id
                    WHERE e.evidence_id IS NULL
                )"""
            )
            self._derive_event_edges()
        return affected

    def query_plan(self, sql: str, parameters: Sequence[object] = ()) -> tuple[str, ...]:
        """Expose deterministic SQLite query-plan evidence for synthetic performance tests."""

        if not sql.lstrip().upper().startswith("SELECT"):
            raise ValueError("query plan is available only for SELECT statements")
        rows = self._connection.execute(f"EXPLAIN QUERY PLAN {sql}", parameters).fetchall()
        return tuple(str(row[3]) for row in rows)

    def _pending_draft_candidate(self, draft_id: str) -> dict[str, object]:
        row = self._connection.execute(
            """SELECT candidate_json,candidate_hash FROM organization_drafts
               WHERE draft_id=? AND status='pending'""",
            (draft_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"pending organization draft does not exist: {draft_id}")
        payload = bytes(row["candidate_json"])
        if storage.payload_digest(payload) != str(row["candidate_hash"]):
            raise storage.ProjectCorruptError("organization draft checksum does not match")
        return _mapping(storage.decode_json(payload), "draft")

    def _reviewed_candidate(
        self,
        candidate: Mapping[str, object],
        reviews: Mapping[tuple[str, str], str],
    ) -> dict[str, object]:
        arcs = _object_list(candidate.get("arcs"), "arcs")
        events = _object_list(candidate.get("events"), "events")
        expected = {("arc", cast(str, arc["id"])) for arc in arcs} | {
            ("event", cast(str, event["id"])) for event in events
        }
        missing = expected - set(reviews)
        if missing:
            labels = ", ".join(f"{kind}:{identifier}" for kind, identifier in sorted(missing))
            raise ValueError(
                f"all candidate arcs and events must be reviewed before apply: {labels}"
            )

        events_by_id = {cast(str, event["id"]): event for event in events}
        accepted_events: list[dict[str, object]] = []
        accepted_arcs: list[dict[str, object]] = []
        active_event_ids: set[str] = set()
        active_arc_ids: set[str] = set()
        for arc in arcs:
            arc_id = cast(str, arc["id"])
            arc_approved = reviews[("arc", arc_id)] == "approved"
            accepted_member_ids: list[str] = []
            for event_id in _string_list(arc["event_ids"], "arc event_ids"):
                event = events_by_id[event_id]
                event_approved = arc_approved and reviews[("event", event_id)] == "approved"
                if event_approved:
                    accepted_event = dict(event)
                    accepted_event["origin"] = _candidate_origin(event.get("origin"))
                    accepted_events.append(accepted_event)
                    accepted_member_ids.append(event_id)
                    active_event_ids.add(event_id)
                    continue
                fallback_id = _stable_id(
                    "fallback-event", event_id, *_string_list(event["beat_ids"], "event beat IDs")
                )
                accepted_events.append(
                    {
                        "id": fallback_id,
                        "title": "Technical event",
                        "summary": "Deterministic organization retained after review.",
                        "beat_ids": list(_string_list(event["beat_ids"], "event beat IDs")),
                        "origin": "deterministic",
                    }
                )
                accepted_member_ids.append(fallback_id)
            accepted_arc_id = arc_id if arc_approved else _stable_id("fallback-arc", arc_id)
            accepted_arcs.append(
                {
                    "id": accepted_arc_id,
                    "title": arc["title"] if arc_approved else "Technical story arc",
                    "summary": (
                        arc["summary"]
                        if arc_approved
                        else "Deterministic organization retained after review."
                    ),
                    "event_ids": accepted_member_ids,
                    "origin": _candidate_origin(arc.get("origin"))
                    if arc_approved
                    else "deterministic",
                }
            )
            if arc_approved:
                active_arc_ids.add(arc_id)

        ungrouped_event_ids: list[str] = []
        for beat_id in _string_list(candidate.get("ungrouped_beat_ids", []), "ungrouped beat IDs"):
            fallback_id = _stable_id("ungrouped-event", beat_id)
            accepted_events.append(
                {
                    "id": fallback_id,
                    "title": "Ungrouped technical event",
                    "summary": "Deterministic beat retained as technical fallback.",
                    "beat_ids": [beat_id],
                    "origin": "deterministic",
                }
            )
            ungrouped_event_ids.append(fallback_id)
        if ungrouped_event_ids:
            accepted_arcs.append(
                {
                    "id": _stable_id("ungrouped-arc", *ungrouped_event_ids),
                    "title": "Ungrouped technical story",
                    "summary": "Deterministic beats retained as technical fallback.",
                    "event_ids": ungrouped_event_ids,
                    "origin": "deterministic",
                }
            )

        accepted_claims = [
            dict(claim)
            for claim in _object_list(candidate.get("claims", []), "claims")
            if (
                isinstance(claim.get("event_id"), str) and claim.get("event_id") in active_event_ids
            )
            or (isinstance(claim.get("arc_id"), str) and claim.get("arc_id") in active_arc_ids)
        ]
        return {
            "events": accepted_events,
            "arcs": accepted_arcs,
            "claims": accepted_claims,
            "ungrouped_beat_ids": [],
        }

    def _validate_candidate(self, candidate: Mapping[str, object]) -> None:
        _require_keys(candidate, {"arcs", "events", "claims", "ungrouped_beat_ids"}, "draft")
        arcs = _object_list(candidate.get("arcs"), "arcs")
        events = _object_list(candidate.get("events"), "events")
        event_ids = _unique_ids(events, "events")
        arc_ids = _unique_ids(arcs, "arcs")
        beat_rows = self._connection.execute(
            "SELECT node_id,sort_key,kind FROM presentation_nodes WHERE level=3 "
            "ORDER BY sort_key,node_id"
        ).fetchall()
        known_beats = {str(row["node_id"]): index for index, row in enumerate(beat_rows)}
        required_beats = {
            str(row["node_id"]) for row in beat_rows if str(row["kind"]) in _REQUIRED_STORY_KINDS
        }
        used_beats: set[str] = set()
        event_order: dict[str, int] = {}
        previous_event_end = -1
        for event_index, event in enumerate(events):
            _require_keys(event, {"id", "title", "summary", "beat_ids", "origin"}, "event")
            _validate_text(event, "title", 80)
            _validate_text(event, "summary", 320)
            _candidate_origin(event.get("origin"))
            beat_ids = _string_list(event.get("beat_ids"), "event beat_ids")
            if not beat_ids:
                raise ValueError("story events must contain at least one beat")
            if len(set(beat_ids)) != len(beat_ids):
                raise ValueError("an event cannot contain duplicate beat IDs")
            unknown = set(beat_ids) - known_beats.keys()
            if unknown:
                raise ValueError(f"story event references unknown beat IDs: {sorted(unknown)!r}")
            if used_beats.intersection(beat_ids):
                raise ValueError("a deterministic beat cannot belong to multiple events")
            positions = [known_beats[item] for item in beat_ids]
            if positions != sorted(positions):
                raise ValueError("event membership must preserve deterministic beat order")
            if positions[0] <= previous_event_end:
                raise ValueError("candidate events must be globally ordered and non-crossing")
            previous_event_end = positions[-1]
            event_order[cast(str, event["id"])] = event_index
            used_beats.update(beat_ids)
        used_events: set[str] = set()
        previous_arc_end = -1
        for arc in arcs:
            _require_keys(arc, {"id", "title", "summary", "event_ids", "origin"}, "arc")
            _validate_text(arc, "title", 80)
            _validate_text(arc, "summary", 320)
            _candidate_origin(arc.get("origin"))
            members = _string_list(arc.get("event_ids"), "arc event_ids")
            if not members:
                raise ValueError("story arcs must contain at least one event")
            unknown = set(members) - event_ids
            if unknown:
                raise ValueError(f"story arc references unknown event IDs: {sorted(unknown)!r}")
            if used_events.intersection(members):
                raise ValueError("a story event cannot belong to multiple arcs")
            positions = [event_order[event_id] for event_id in members]
            if positions != sorted(positions):
                raise ValueError("events within an arc must be chronological")
            if positions[0] <= previous_arc_end:
                raise ValueError("candidate arcs must be chronological and non-crossing")
            previous_arc_end = positions[-1]
            used_events.update(members)
        if used_events != event_ids:
            raise ValueError("every candidate event must belong to exactly one arc")
        ungrouped = _string_list(candidate.get("ungrouped_beat_ids", []), "ungrouped beat IDs")
        if len(set(ungrouped)) != len(ungrouped):
            raise ValueError("ungrouped beat IDs cannot contain duplicates")
        if not set(ungrouped).issubset(known_beats):
            raise ValueError("ungrouped IDs must reference existing deterministic beats")
        if used_beats.intersection(ungrouped):
            raise ValueError("a beat cannot be both grouped and ungrouped")
        missing_required = required_beats - used_beats - set(ungrouped)
        if missing_required:
            raise ValueError(
                "required story beats must be grouped exactly once or explicitly ungrouped: "
                f"{sorted(missing_required)!r}"
            )
        claims = _object_list(candidate.get("claims", []), "claims")
        evidence_ids = {
            str(row[0])
            for row in self._connection.execute("SELECT evidence_id FROM presentation_evidence")
        }
        claim_ids = _unique_ids(claims, "claims")
        del claim_ids
        for claim in claims:
            _require_keys(
                claim,
                {"id", "event_id", "arc_id", "text", "kind", "evidence_ids"},
                "claim",
            )
            _validate_text(claim, "text", 320)
            target_event = claim.get("event_id")
            target_arc = claim.get("arc_id")
            if (isinstance(target_event, str)) == (isinstance(target_arc, str)):
                raise ValueError("a claim must target exactly one event or arc")
            if isinstance(target_event, str) and target_event not in event_ids:
                raise ValueError("claim references an unknown event")
            if isinstance(target_arc, str) and target_arc not in arc_ids:
                raise ValueError("claim references an unknown arc")
            if claim.get("kind", "interpretation") not in {"interpretation", "outcome", "warning"}:
                raise ValueError("claim kind is not supported")
            evidence = _string_list(claim.get("evidence_ids"), "claim evidence_ids")
            if not evidence or not set(evidence).issubset(evidence_ids):
                raise ValueError("interpretive claims require existing evidence IDs")

    def _apply_candidate(self, candidate: Mapping[str, object], generation: str) -> None:
        explicitly_pinned_arcs = {
            str(row[0])
            for row in self._connection.execute("SELECT arc_id FROM story_arcs WHERE pinned=1")
        }
        pinned_events = {
            str(row[0])
            for row in self._connection.execute(
                """SELECT event_id FROM story_events WHERE pinned=1
                   UNION SELECT event_id FROM story_arc_members
                   WHERE arc_id IN (SELECT arc_id FROM story_arcs WHERE pinned=1)"""
            )
        }
        pinned_arcs = explicitly_pinned_arcs | {
            str(row[0])
            for row in self._connection.execute(
                "SELECT arc_id FROM story_arc_members WHERE event_id IN "
                "(SELECT event_id FROM story_events WHERE pinned=1)"
            )
        }
        pinned_beats = {
            str(row[0])
            for row in self._connection.execute(
                "SELECT beat_id FROM story_event_members WHERE event_id IN "
                "(SELECT event_id FROM story_events WHERE pinned=1 UNION SELECT event_id "
                "FROM story_arc_members WHERE arc_id IN "
                "(SELECT arc_id FROM story_arcs WHERE pinned=1))"
            )
        }
        self._connection.execute(
            """DELETE FROM story_arcs WHERE pinned=0 AND arc_id NOT IN (
                SELECT arc_id FROM story_arc_members WHERE event_id IN (
                    SELECT event_id FROM story_events WHERE pinned=1
                )
            )"""
        )
        self._connection.execute(
            """DELETE FROM story_events WHERE pinned=0 AND event_id NOT IN (
                SELECT event_id FROM story_arc_members
                WHERE arc_id IN (SELECT arc_id FROM story_arcs WHERE pinned=1)
            )"""
        )
        now = storage.utc_now()
        events = _object_list(candidate["events"], "events")
        events_in_preserved_arcs = {
            event_id
            for arc in _object_list(candidate["arcs"], "arcs")
            if cast(str, arc["id"]) in pinned_arcs
            for event_id in _string_list(arc["event_ids"], "event_ids")
        }
        inserted_events: set[str] = set()
        for order, event in enumerate(events):
            event_id = cast(str, event["id"])
            beats = [
                beat
                for beat in _string_list(event["beat_ids"], "beat_ids")
                if beat not in pinned_beats
            ]
            if event_id in pinned_events or event_id in events_in_preserved_arcs or not beats:
                continue
            self._connection.execute(
                "INSERT INTO story_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    event["title"],
                    event["summary"],
                    order,
                    _candidate_origin(event.get("origin")),
                    0,
                    0,
                    "approved",
                    0,
                    generation,
                    now,
                ),
            )
            self._replace_members(event_id, beats)
            inserted_events.add(event_id)
        inserted_arcs: set[str] = set()
        for order, arc in enumerate(_object_list(candidate["arcs"], "arcs")):
            arc_id = cast(str, arc["id"])
            if arc_id in pinned_arcs:
                continue
            member_ids = [
                event_id
                for event_id in _string_list(arc["event_ids"], "event_ids")
                if event_id in inserted_events
            ]
            if not member_ids:
                continue
            self._connection.execute(
                "INSERT INTO story_arcs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    arc_id,
                    arc["title"],
                    arc["summary"],
                    order,
                    _candidate_origin(arc.get("origin")),
                    0,
                    0,
                    "approved",
                    0,
                    generation,
                    now,
                ),
            )
            inserted_arcs.add(arc_id)
            current = self._connection.execute(
                "SELECT COALESCE(MAX(ordinal)+1,0) FROM story_arc_members WHERE arc_id=?", (arc_id,)
            ).fetchone()
            assert current is not None
            next_order = int(current[0])
            for event_id in member_ids:
                self._connection.execute(
                    "INSERT INTO story_arc_members VALUES (?,?,?)",
                    (arc_id, event_id, next_order),
                )
                next_order += 1
        self._connection.execute(
            """DELETE FROM story_claims WHERE NOT (
                (event_id IS NOT NULL AND event_id IN (
                    SELECT event_id FROM story_events WHERE pinned=1
                    UNION SELECT event_id FROM story_arc_members
                    WHERE arc_id IN (SELECT arc_id FROM story_arcs WHERE pinned=1)
                )) OR
                (arc_id IS NOT NULL AND arc_id IN (
                    SELECT arc_id FROM story_arcs WHERE pinned=1
                    UNION SELECT arc_id FROM story_arc_members WHERE event_id IN (
                        SELECT event_id FROM story_events WHERE pinned=1
                    )
                ))
            )"""
        )
        for order, claim in enumerate(_object_list(candidate.get("claims", []), "claims")):
            claim_event_id = claim.get("event_id")
            claim_arc_id = claim.get("arc_id")
            if (
                isinstance(claim_event_id, str)
                and claim_event_id not in inserted_events
                and claim_event_id not in pinned_events
            ):
                continue
            if (
                isinstance(claim_arc_id, str)
                and claim_arc_id not in inserted_arcs
                and claim_arc_id not in pinned_arcs
            ):
                continue
            if (
                self._connection.execute(
                    "SELECT 1 FROM story_claims WHERE claim_id=?", (claim["id"],)
                ).fetchone()
                is not None
            ):
                continue
            self._connection.execute(
                "INSERT INTO story_claims VALUES (?,?,?,?,?,?,?)",
                (
                    claim["id"],
                    claim_event_id,
                    claim_arc_id,
                    claim["text"],
                    cast(str, claim.get("kind", "interpretation")),
                    "approved",
                    order,
                ),
            )
            self._connection.executemany(
                "INSERT INTO story_claim_evidence VALUES (?,?)",
                (
                    (claim["id"], evidence_id)
                    for evidence_id in _string_list(claim["evidence_ids"], "evidence_ids")
                ),
            )

    def _derive_event_edges(self) -> None:
        self._connection.execute("DELETE FROM story_event_edges")
        rows = self._connection.execute(
            """SELECT sm.event_id AS source_event,tm.event_id AS target_event,e.kind,e.edge_id
               FROM presentation_edges e
               JOIN story_event_members sm ON sm.beat_id=e.source_id
               JOIN story_event_members tm ON tm.beat_id=e.target_id
               WHERE e.level=3 AND sm.event_id<>tm.event_id
               ORDER BY sm.event_id,tm.event_id,e.kind,e.edge_id"""
        ).fetchall()
        grouped: dict[tuple[str, str, str], list[str]] = {}
        for row in rows:
            key = (str(row["source_event"]), str(row["target_event"]), str(row["kind"]))
            grouped.setdefault(key, []).append(str(row["edge_id"]))
        for (source, target, kind), transition_ids in grouped.items():
            self._connection.execute(
                "INSERT INTO story_event_edges VALUES (?,?,?,?,?,?)",
                (
                    _stable_id("event-edge", source, target, kind),
                    source,
                    target,
                    kind,
                    "deterministic_quotient",
                    storage.canonical_json(transition_ids),
                ),
            )

    def _member_ids(self, event_id: str) -> tuple[str, ...]:
        return tuple(
            str(row[0])
            for row in self._connection.execute(
                "SELECT beat_id FROM story_event_members WHERE event_id=? ORDER BY ordinal",
                (event_id,),
            )
        )

    def _arc_member_ids(self, arc_id: str) -> tuple[str, ...]:
        return tuple(
            str(row[0])
            for row in self._connection.execute(
                "SELECT event_id FROM story_arc_members WHERE arc_id=? ORDER BY ordinal",
                (arc_id,),
            )
        )

    def _replace_members(self, event_id: str, beat_ids: Iterable[str]) -> None:
        self._connection.execute("DELETE FROM story_event_members WHERE event_id=?", (event_id,))
        self._connection.executemany(
            "INSERT INTO story_event_members VALUES (?,?,?)",
            ((event_id, beat_id, ordinal) for ordinal, beat_id in enumerate(beat_ids)),
        )

    def _shift_arc_members(self, arc_id: str, from_ordinal: int) -> None:
        rows = self._connection.execute(
            "SELECT event_id,ordinal FROM story_arc_members WHERE arc_id=? AND ordinal>=? "
            "ORDER BY ordinal DESC",
            (arc_id, from_ordinal),
        ).fetchall()
        for row in rows:
            self._connection.execute(
                "UPDATE story_arc_members SET ordinal=? WHERE arc_id=? AND event_id=?",
                (int(row["ordinal"]) + 1, arc_id, str(row["event_id"])),
            )

    def _renumber_arc(self, arc_id: str) -> None:
        rows = self._connection.execute(
            "SELECT event_id FROM story_arc_members WHERE arc_id=? ORDER BY ordinal,event_id",
            (arc_id,),
        ).fetchall()
        offset = len(rows) + 1
        self._connection.execute(
            "UPDATE story_arc_members SET ordinal=ordinal+? WHERE arc_id=?", (offset, arc_id)
        )
        for ordinal, row in enumerate(rows):
            self._connection.execute(
                "UPDATE story_arc_members SET ordinal=? WHERE arc_id=? AND event_id=?",
                (ordinal, arc_id, str(row["event_id"])),
            )

    def _update_flag(
        self,
        operation: EditOperation,
        target_kind: Literal["arc", "event"],
        target_id: str,
        column: Literal["hidden", "pinned"],
        value: bool,
    ) -> None:
        table, key = _target_table(target_kind)
        with storage.transaction(self._connection):
            cursor = self._connection.execute(
                f"UPDATE {table} SET {column}=?,updated_utc=? WHERE {key}=?",
                (int(value), storage.utc_now(), target_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"{target_kind} does not exist: {target_id}")
            self._insert_edit(operation, target_kind, target_id, {column: value})

    def _insert_edit(
        self,
        operation: EditOperation,
        target_kind: Literal["arc", "event"],
        target_id: str,
        payload: Mapping[str, object],
    ) -> None:
        self._connection.execute(
            "INSERT INTO story_edits VALUES (?,?,?,?,?,'applied',?)",
            (
                uuid.uuid4().hex,
                operation,
                target_kind,
                target_id,
                storage.canonical_json(dict(payload)),
                storage.utc_now(),
            ),
        )

    def _cache_exists(self, cache_key: str) -> bool:
        return (
            self._connection.execute(
                "SELECT 1 FROM organization_cache WHERE cache_key=?", (cache_key,)
            ).fetchone()
            is not None
        )


def _stable_id(prefix: str, *values: str) -> str:
    digest = hashlib.sha256(storage.canonical_json(list(values))).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _require_digest(value: str, name: str) -> None:
    if len(value) != _SHA256_LENGTH or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _sanitize_failure(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.replace("\x00", "").split())[:500] or None


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _mapping(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise storage.ProjectCorruptError(f"{name} must be a JSON object")
    return cast(dict[str, object], value)


def _object_list(value: object, name: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{name} must be a list of objects")
    return cast(list[dict[str, object]], value)


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{name} must be a list of non-empty strings")
    return cast(list[str], value)


def _unique_ids(values: Sequence[Mapping[str, object]], name: str) -> set[str]:
    ids = [item.get("id") for item in values]
    if not all(isinstance(item, str) and item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError(f"{name} must have unique non-empty IDs")
    return cast(set[str], set(ids))


def _validate_text(
    value: Mapping[str, object], key: str, maximum: int, *, allow_empty: bool = False
) -> None:
    text = value.get(key)
    if not isinstance(text, str) or len(text) > maximum or (not allow_empty and not text.strip()):
        raise ValueError(f"{key} must contain {'0' if allow_empty else '1'}-{maximum} characters")


def _candidate_origin(value: object) -> str:
    origin = "ai" if value is None else value
    if not isinstance(origin, str) or origin not in _SUPPORTED_ORIGINS:
        allowed = ", ".join(sorted(_SUPPORTED_ORIGINS))
        raise ValueError(f"origin must be one of: {allowed}")
    return origin


def _require_keys(value: Mapping[str, object], allowed: set[str], name: str) -> None:
    unexpected = set(value) - allowed
    if unexpected:
        raise ValueError(f"{name} contains unsupported fields: {sorted(unexpected)!r}")


def _reject_authority_fields(value: object) -> None:
    forbidden = {
        "edges",
        "requirements",
        "effects",
        "dialogue",
        "narration",
        "source_text",
        "source_path",
        "source_locations",
    }
    if isinstance(value, Mapping):
        conflicts = forbidden.intersection(value)
        if conflicts:
            raise ValueError(
                f"organization result contains authoritative or raw fields: {sorted(conflicts)!r}"
            )
        for item in value.values():
            _reject_authority_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_authority_fields(item)


def _target_table(target_kind: Literal["arc", "event"]) -> tuple[str, str]:
    return ("story_arcs", "arc_id") if target_kind == "arc" else ("story_events", "event_id")
