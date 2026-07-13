# ruff: noqa: E501
"""Bounded deterministic presentation queries over durable project data.

The presentation index is a derived, row-oriented projection.  Query methods never load the
monolithic M01 or M02 payloads and always enforce hard result limits.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Final

from renpy_story_mapper import storage
from renpy_story_mapper.project import Project

MAX_NODES: Final = 250
MAX_EDGES: Final = 500
MAX_RESULTS: Final = 100
EVENT_GROUP_SIZE: Final = 4


class PresentationLevel(IntEnum):
    OVERVIEW = 1
    EVENT = 2
    EVIDENCE = 3


@dataclass(frozen=True)
class PresentationRequest:
    level: PresentationLevel
    parent_ids: tuple[str, ...] = ()
    focus_ids: tuple[str, ...] = ()
    expanded_ids: tuple[str, ...] = ()
    collapsed_ids: tuple[str, ...] = ()
    after: str | None = None
    edge_after: str | None = None
    node_limit: int = 50
    edge_limit: int = 100
    include_technical: bool = False


@dataclass(frozen=True)
class Continuation:
    returned: int
    has_more: bool
    next_after: str | None


@dataclass(frozen=True)
class PresentationNode:
    id: str
    level: PresentationLevel
    parent_id: str | None
    kind: str
    name: str
    source_path: str | None
    start_line: int | None
    end_line: int | None
    technical: bool
    expandable: bool
    child_count: int
    payload: object


@dataclass(frozen=True)
class PresentationEdge:
    id: str
    level: PresentationLevel
    source_id: str
    target_id: str
    kind: str
    payload: object


@dataclass(frozen=True)
class PresentationPage:
    nodes: tuple[PresentationNode, ...]
    edges: tuple[PresentationEdge, ...]
    node_continuation: Continuation
    edge_continuation: Continuation
    selected_id: str | None = None


@dataclass(frozen=True)
class OrganizationConnectivity:
    """Authoritative deterministic facts for one complete organization scope."""

    beat_ids: tuple[str, ...]
    required_beat_ids: tuple[str, ...]
    edges: tuple[PresentationEdge, ...]


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    node_id: str
    kind: str
    source_path: str
    start_line: int
    end_line: int
    text: str
    payload: object


@dataclass(frozen=True)
class SearchHit:
    id: int
    node_id: str
    field: str
    text: str


@dataclass(frozen=True)
class FactRecord:
    id: str
    node_id: str | None
    kind: str
    variable: str | None
    category: str | None
    status: str
    expression: str
    source_path: str
    start_line: int
    end_line: int
    payload: object
    variable_display_name: str | None = None


@dataclass(frozen=True)
class StateVariableRecord:
    original_name: str
    display_name: str
    category: str
    user_override: bool
    default_value: object = None
    default_declared: bool = False
    metadata_source: str | None = None


@dataclass(frozen=True)
class ResultPage:
    items: tuple[EvidenceRecord | SearchHit | FactRecord | StateVariableRecord, ...]
    continuation: Continuation


class PresentationService:
    """Small non-UI service suitable for a desktop adapter."""

    def __init__(
        self,
        project: Project,
        *,
        owns_project: bool = False,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self._project = project
        self._owns_project = owns_project
        self._cancelled = cancelled
        _ensure_query_indexes(project._require_open())
        ensure_presentation_index(project, cancelled=cancelled)

    @classmethod
    def open(
        cls, path: str | Path, *, cancelled: Callable[[], bool] | None = None
    ) -> PresentationService:
        project = Project.open(path)
        try:
            return cls(project, owns_project=True, cancelled=cancelled)
        except BaseException:
            project.close()
            raise

    def close(self) -> None:
        if self._owns_project:
            self._project.close()
            self._owns_project = False

    def __enter__(self) -> PresentationService:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def view(self, request: PresentationRequest, *, selected_id: str | None = None) -> PresentationPage:
        node_limit = _bounded_limit(request.node_limit, MAX_NODES)
        edge_limit = _bounded_limit(request.edge_limit, MAX_EDGES)
        parents = tuple(sorted(set(request.parent_ids or request.expanded_ids)))
        focuses = tuple(sorted(set(request.focus_ids)))
        collapsed = set(request.collapsed_ids)
        if parents:
            parents = tuple(item for item in parents if item not in collapsed)
        connection = self._project._require_open()
        clauses = ["n.level = ?", "COALESCE(o.hidden, 0) = 0"]
        parameters: list[object] = [int(request.level)]
        if not request.include_technical:
            clauses.append("n.technical = 0")
        if focuses:
            placeholders = ",".join("?" for _ in focuses)
            clauses.append(f"n.node_id IN ({placeholders})")
            parameters.extend(focuses)
        elif parents:
            placeholders = ",".join("?" for _ in parents)
            clauses.append(f"n.parent_id IN ({placeholders})")
            parameters.extend(parents)
        elif request.level is not PresentationLevel.OVERVIEW:
            clauses.append("n.parent_id IS NULL")
        if request.after is not None:
            clauses.append("n.sort_key > ?")
            parameters.append(request.after)
        rows = connection.execute(
            f"""
            SELECT n.*, COALESCE(o.display_name, n.label) AS display_label,
                   (SELECT COUNT(*) FROM presentation_nodes c WHERE c.parent_id = n.node_id)
                       AS child_count
            FROM presentation_nodes n
            LEFT JOIN presentation_overrides o ON o.node_id = n.node_id
            WHERE {' AND '.join(clauses)}
            ORDER BY n.sort_key, n.node_id LIMIT ?
            """,
            (*parameters, node_limit + 1),
        ).fetchall()
        has_more = len(rows) > node_limit
        rows = rows[:node_limit]
        nodes = tuple(_node_from_row(row) for row in rows)
        node_ids = tuple(node.id for node in nodes)
        edges = self._edges(request.level, node_ids, edge_limit, request.edge_after)
        return PresentationPage(
            nodes,
            edges[0],
            Continuation(len(nodes), has_more, str(rows[-1]["sort_key"]) if has_more else None),
            edges[1],
            selected_id,
        )

    def edges_for_nodes(
        self,
        level: PresentationLevel,
        node_ids: Sequence[str],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[PresentationEdge, ...]:
        """Return all authoritative edges induced by a complete caller-supplied node set.

        Unknown IDs at the requested level are rejected rather than silently ignored. A temporary
        indexed selection table avoids SQLite parameter limits without modifying project tables.
        """

        if any(not isinstance(node_id, str) or not node_id for node_id in node_ids):
            raise ValueError("node_ids must contain non-empty strings")
        selected = tuple(sorted(set(node_ids)))
        if not selected:
            return ()
        connection = self._project._require_open()
        interrupted = False

        def cancel_sqlite_work() -> int:
            nonlocal interrupted
            if _query_cancel_requested(self._cancelled, cancelled):
                interrupted = True
                return 1
            return 0

        connection.set_progress_handler(cancel_sqlite_work, 10_000)
        try:
            _query_cancel(self._cancelled, cancelled)
            connection.execute(
                """CREATE TEMP TABLE IF NOT EXISTS selected_presentation_nodes(
                    node_id TEXT PRIMARY KEY
                ) WITHOUT ROWID"""
            )
            connection.execute("DELETE FROM selected_presentation_nodes")
            for offset in range(0, len(selected), 1000):
                _query_cancel(self._cancelled, cancelled)
                connection.executemany(
                    "INSERT INTO selected_presentation_nodes(node_id) VALUES (?)",
                    ((node_id,) for node_id in selected[offset : offset + 1000]),
                )
            unknown = connection.execute(
                """SELECT selected.node_id FROM selected_presentation_nodes selected
                   LEFT JOIN presentation_nodes node
                     ON node.node_id=selected.node_id AND node.level=?
                   WHERE node.node_id IS NULL ORDER BY selected.node_id LIMIT 1""",
                (int(level),),
            ).fetchone()
            if unknown is not None:
                raise ValueError(
                    f"unknown presentation node for level {int(level)}: {unknown['node_id']}"
                )
            _query_cancel(self._cancelled, cancelled)
            cursor = connection.execute(
                """SELECT edge.* FROM selected_presentation_nodes source
                   CROSS JOIN presentation_edges edge
                     INDEXED BY presentation_edges_source_idx
                   JOIN selected_presentation_nodes target ON target.node_id=edge.target_id
                   WHERE edge.source_id=source.node_id AND edge.level=?
                   ORDER BY edge.sort_key,edge.edge_id""",
                (int(level),),
            )
            result: list[PresentationEdge] = []
            try:
                while rows := cursor.fetchmany(500):
                    _query_cancel(self._cancelled, cancelled)
                    result.extend(
                        PresentationEdge(
                            str(row["edge_id"]),
                            PresentationLevel(int(row["level"])),
                            str(row["source_id"]),
                            str(row["target_id"]),
                            str(row["kind"]),
                            storage.decode_json(row["payload_json"]),
                        )
                        for row in rows
                    )
            finally:
                cursor.close()
            return tuple(result)
        except sqlite3.OperationalError as exc:
            if interrupted:
                raise storage.ProjectOperationCancelled(
                    "project operation was cancelled"
                ) from exc
            raise
        finally:
            connection.set_progress_handler(None, 0)
            connection.execute("DROP TABLE IF EXISTS selected_presentation_nodes")

    def evidence_for_nodes(
        self,
        node_ids: Sequence[str],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[EvidenceRecord, ...]:
        """Return evidence attached directly to an exact Level-3 node selection.

        This bulk path intentionally does not expand descendants. The indexed temporary
        selection keeps canonical-scale requests below SQLite's parameter limit and makes
        cancellation observable while rows are streamed.
        """

        selected = _validated_selected_node_ids(node_ids)
        if not selected:
            return ()
        connection = self._project._require_open()
        _query_cancel(self._cancelled, cancelled)
        connection.execute(
            """CREATE TEMP TABLE IF NOT EXISTS selected_presentation_evidence_nodes(
                node_id TEXT PRIMARY KEY
            ) WITHOUT ROWID"""
        )
        try:
            connection.execute("DELETE FROM selected_presentation_evidence_nodes")
            for offset in range(0, len(selected), 1000):
                _query_cancel(self._cancelled, cancelled)
                connection.executemany(
                    "INSERT INTO selected_presentation_evidence_nodes(node_id) VALUES (?)",
                    ((node_id,) for node_id in selected[offset : offset + 1000]),
                )
            _reject_unknown_level_three_nodes(
                connection,
                "selected_presentation_evidence_nodes",
                self._cancelled,
                cancelled,
            )
            cursor = connection.execute(
                """SELECT evidence.*
                   FROM selected_presentation_evidence_nodes selected
                   CROSS JOIN presentation_evidence evidence
                     INDEXED BY presentation_evidence_node_idx
                     ON evidence.node_id=selected.node_id
                   ORDER BY evidence.sort_key,evidence.evidence_id"""
            )
            records: list[EvidenceRecord] = []
            try:
                while rows := cursor.fetchmany(500):
                    _query_cancel(self._cancelled, cancelled)
                    records.extend(_evidence_from_row(row) for row in rows)
            finally:
                cursor.close()
            return tuple(records)
        finally:
            connection.execute(
                "DROP TABLE IF EXISTS selected_presentation_evidence_nodes"
            )

    def facts_for_nodes(
        self,
        node_ids: Sequence[str],
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[FactRecord, ...]:
        """Return facts attached directly to an exact Level-3 node selection."""

        selected = _validated_selected_node_ids(node_ids)
        if not selected:
            return ()
        connection = self._project._require_open()
        _query_cancel(self._cancelled, cancelled)
        connection.execute(
            """CREATE TEMP TABLE IF NOT EXISTS selected_presentation_fact_nodes(
                node_id TEXT PRIMARY KEY
            ) WITHOUT ROWID"""
        )
        try:
            connection.execute("DELETE FROM selected_presentation_fact_nodes")
            for offset in range(0, len(selected), 1000):
                _query_cancel(self._cancelled, cancelled)
                connection.executemany(
                    "INSERT INTO selected_presentation_fact_nodes(node_id) VALUES (?)",
                    ((node_id,) for node_id in selected[offset : offset + 1000]),
                )
            _reject_unknown_level_three_nodes(
                connection,
                "selected_presentation_fact_nodes",
                self._cancelled,
                cancelled,
            )
            cursor = connection.execute(
                """SELECT fact.*
                   FROM selected_presentation_fact_nodes selected
                   CROSS JOIN presentation_facts fact
                     INDEXED BY presentation_facts_node_idx
                     ON fact.node_id=selected.node_id
                   ORDER BY fact.sort_key,fact.fact_id"""
            )
            records: list[FactRecord] = []
            try:
                while rows := cursor.fetchmany(500):
                    _query_cancel(self._cancelled, cancelled)
                    records.extend(_fact_from_row(row) for row in rows)
            finally:
                cursor.close()
            return tuple(records)
        finally:
            connection.execute("DROP TABLE IF EXISTS selected_presentation_fact_nodes")

    def _edges(
        self,
        level: PresentationLevel,
        node_ids: tuple[str, ...],
        limit: int,
        after: str | None,
    ) -> tuple[tuple[PresentationEdge, ...], Continuation]:
        if not node_ids:
            return (), Continuation(0, False, None)
        placeholders = ",".join("?" for _ in node_ids)
        after_clause = " AND sort_key > ?" if after is not None else ""
        after_parameters: tuple[object, ...] = () if after is None else (after,)
        rows = self._project._require_open().execute(
            f"""
            SELECT * FROM presentation_edges
            WHERE level = ? AND source_id IN ({placeholders}) AND target_id IN ({placeholders})
              {after_clause}
            ORDER BY sort_key, edge_id LIMIT ?
            """,
            (int(level), *node_ids, *node_ids, *after_parameters, limit + 1),
        ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        values = tuple(
            PresentationEdge(
                str(row["edge_id"]),
                PresentationLevel(int(row["level"])),
                str(row["source_id"]),
                str(row["target_id"]),
                str(row["kind"]),
                storage.decode_json(row["payload_json"]),
            )
            for row in rows
        )
        return values, Continuation(
            len(values), has_more, str(rows[-1]["sort_key"]) if has_more else None
        )

    def organization_connectivity(self, beat_ids: Iterable[str]) -> OrganizationConnectivity:
        """Return every selected Level-3 beat and internal deterministic transition.

        This is intentionally independent of presentation pagination. Queries are chunked below
        SQLite's common variable limit and use the Level-3 node and source-edge indexes; target
        membership is checked in memory so a cross-page or cross-Level-1 edge is never lost.
        """

        selected = set(beat_ids)
        if not selected:
            return OrganizationConnectivity((), (), ())
        connection = self._project._require_open()
        node_rows: list[sqlite3.Row] = []
        for chunk in _chunks(tuple(sorted(selected)), 400):
            placeholders = ",".join("?" for _ in chunk)
            node_rows.extend(
                connection.execute(
                    f"""SELECT node_id,sort_key,kind FROM presentation_nodes
                    WHERE level=3 AND node_id IN ({placeholders})
                    ORDER BY sort_key,node_id""",
                    chunk,
                ).fetchall()
            )
        found = {str(row["node_id"]) for row in node_rows}
        unknown = selected - found
        if unknown:
            raise ValueError(f"selected scope references unknown Level-3 beat IDs: {sorted(unknown)!r}")
        node_rows.sort(key=lambda row: (str(row["sort_key"]), str(row["node_id"])))
        ordered = tuple(str(row["node_id"]) for row in node_rows)
        required = tuple(
            str(row["node_id"])
            for row in node_rows
            if str(row["kind"]) in {"narrative", "dialogue", "narration", "choice", "condition"}
        )

        edge_rows: list[sqlite3.Row] = []
        for chunk in _chunks(ordered, 400):
            placeholders = ",".join("?" for _ in chunk)
            edge_rows.extend(
                connection.execute(
                    f"""SELECT * FROM presentation_edges INDEXED BY presentation_edges_source_idx
                    WHERE level=3 AND source_id IN ({placeholders})
                    ORDER BY sort_key,edge_id""",
                    chunk,
                ).fetchall()
            )
        edge_rows = [row for row in edge_rows if str(row["target_id"]) in selected]
        edge_rows.sort(key=lambda row: (str(row["sort_key"]), str(row["edge_id"])))
        edges = tuple(
            PresentationEdge(
                str(row["edge_id"]),
                PresentationLevel.EVIDENCE,
                str(row["source_id"]),
                str(row["target_id"]),
                str(row["kind"]),
                storage.decode_json(row["payload_json"]),
            )
            for row in edge_rows
        )
        return OrganizationConnectivity(ordered, required, edges)

    def evidence(self, node_id: str, *, after: str | None = None, limit: int = 25) -> ResultPage:
        bounded = _bounded_limit(limit, MAX_RESULTS)
        clauses: list[str] = []
        parameters: list[object] = [node_id]
        if after is not None:
            clauses.append("e.sort_key > ?")
            parameters.append(after)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._project._require_open().execute(
            f"""WITH RECURSIVE descendants(node_id, depth) AS (
              SELECT ?, 0
              UNION ALL
              SELECT n.node_id, d.depth + 1 FROM presentation_nodes n
              JOIN descendants d ON n.parent_id=d.node_id WHERE d.depth < 2
            )
            SELECT e.* FROM descendants d
            CROSS JOIN presentation_evidence e INDEXED BY presentation_evidence_node_idx
              ON e.node_id=d.node_id
            {where} ORDER BY e.sort_key,e.evidence_id LIMIT ?""",
            (*parameters, bounded + 1),
        ).fetchall()
        has_more = len(rows) > bounded
        rows = rows[:bounded]
        items = tuple(_evidence_from_row(row) for row in rows)
        return ResultPage(
            items,
            Continuation(len(items), has_more, str(rows[-1]["sort_key"]) if has_more else None),
        )

    def search(
        self,
        query: str,
        *,
        fields: Iterable[str] = (),
        after: int | str | None = None,
        limit: int = 25,
    ) -> ResultPage:
        term = query.strip().casefold()
        if not term:
            raise ValueError("search query cannot be empty")
        bounded = _bounded_limit(limit, MAX_RESULTS)
        clauses = ["normalized LIKE ? ESCAPE '\\'"]
        parameters: list[object] = [f"%{_escape_like(term)}%"]
        selected = tuple(sorted(set(fields)))
        if selected:
            placeholders = ",".join("?" for _ in selected)
            clauses.append(f"field IN ({placeholders})")
            parameters.extend(selected)
        if after is not None:
            clauses.append("search_id > ?")
            parameters.append(int(after))
        rows = self._project._require_open().execute(
            f"""SELECT s.* FROM presentation_search s
            LEFT JOIN presentation_overrides o ON o.node_id=s.node_id
            WHERE {' AND '.join('s.' + clause if clause.startswith(('normalized', 'field', 'search_id')) else clause for clause in clauses)}
              AND COALESCE(o.hidden, 0)=0
            ORDER BY s.search_id LIMIT ?""",
            (*parameters, bounded + 1),
        ).fetchall()
        has_more = len(rows) > bounded
        rows = rows[:bounded]
        items = tuple(
            SearchHit(int(row["search_id"]), str(row["node_id"]), str(row["field"]), str(row["text"]))
            for row in rows
        )
        return ResultPage(
            items,
            Continuation(len(items), has_more, str(items[-1].id) if has_more else None),
        )

    def facts(
        self,
        *,
        kind: str | None = None,
        variable: str | None = None,
        category: str | None = None,
        node_id: str | None = None,
        after: str | None = None,
        limit: int = 25,
    ) -> ResultPage:
        bounded = _bounded_limit(limit, MAX_RESULTS)
        clauses: list[str] = []
        parameters: list[object] = []
        for column, value in (("fact_kind", kind), ("variable", variable), ("category", category)):
            if value is not None:
                clauses.append(f"f.{column} = ?")
                parameters.append(value)
        prefix = ""
        from_clause = "presentation_facts f"
        if node_id is not None:
            prefix = """WITH RECURSIVE descendants(node_id, depth) AS (
              SELECT ?, 0
              UNION ALL
              SELECT n.node_id, d.depth + 1 FROM presentation_nodes n
              JOIN descendants d ON n.parent_id=d.node_id WHERE d.depth < 2
            )"""
            from_clause = (
                "descendants d CROSS JOIN presentation_facts f "
                "INDEXED BY presentation_facts_node_idx ON f.node_id=d.node_id"
            )
            parameters.insert(0, node_id)
        if after is not None:
            clauses.append("f.sort_key > ?")
            parameters.append(after)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._project._require_open().execute(
            f"""{prefix} SELECT f.* FROM {from_clause} {where}
            ORDER BY f.sort_key,f.fact_id LIMIT ?""",
            (*parameters, bounded + 1),
        ).fetchall()
        has_more = len(rows) > bounded
        rows = rows[:bounded]
        items = tuple(_fact_from_row(row) for row in rows)
        return ResultPage(
            items,
            Continuation(len(items), has_more, str(rows[-1]["sort_key"]) if has_more else None),
        )

    def choice_outcome_facts(self, node_id: str, *, limit: int = 50) -> ResultPage:
        """Return bounded facts reachable from a Level-2 choice until branch termination."""

        bounded = _bounded_limit(limit, MAX_RESULTS)
        rows = self._project._require_open().execute(
            """WITH RECURSIVE context(scene_id) AS (
                 SELECT parent_id FROM presentation_nodes
                 WHERE node_id=? AND level=2 AND kind='choice_group'
               ), walk(node_id) AS (
                 SELECT node_id FROM presentation_nodes
                 WHERE parent_id=? AND level=3 AND kind='choice'
                 UNION
                 SELECT e.target_id
                 FROM walk w
                 JOIN presentation_nodes current ON current.node_id=w.node_id
                 CROSS JOIN presentation_edges e INDEXED BY presentation_edges_source_idx
                   ON e.level=3 AND e.source_id=w.node_id
                 JOIN presentation_nodes target ON target.node_id=e.target_id
                 JOIN presentation_nodes target_event ON target_event.node_id=target.parent_id
                 JOIN context c ON target_event.parent_id=c.scene_id
                 WHERE current.kind NOT IN ('jump','return','module_end','ending')
                 LIMIT 512
               )
               SELECT DISTINCT f.* FROM presentation_facts f
               JOIN walk w ON w.node_id=f.node_id
               ORDER BY f.sort_key,f.fact_id LIMIT ?""",
            (node_id, node_id, bounded + 1),
        ).fetchall()
        has_more = len(rows) > bounded
        rows = rows[:bounded]
        items = tuple(_fact_from_row(row) for row in rows)
        return ResultPage(
            items,
            Continuation(len(items), has_more, str(rows[-1]["sort_key"]) if has_more else None),
        )

    def variable_display_names(self, names: Iterable[str]) -> dict[str, str]:
        """Resolve a bounded set of original variable names to current display names."""

        selected = tuple(sorted(set(names)))
        if not selected:
            return {}
        if len(selected) > 1000:
            raise ValueError("too many variable display names requested")
        placeholders = ",".join("?" for _ in selected)
        rows = self._project._require_open().execute(
            f"""SELECT json_extract(v.value,'$.original_name') AS original_name,
                       COALESCE(json_extract(v.value,'$.display_name'),
                                json_extract(v.value,'$.original_name')) AS display_name
                FROM payloads p,json_each(CAST(p.payload_json AS TEXT)) v
                WHERE p.collection='state_registry' AND p.record_key='authoritative'
                  AND json_extract(v.value,'$.original_name') IN ({placeholders})""",
            selected,
        ).fetchall()
        return {str(row["original_name"]): str(row["display_name"]) for row in rows}

    def lineage(self, node_id: str) -> tuple[PresentationNode, ...]:
        """Return the bounded root-to-node lineage for search-driven navigation."""

        connection = self._project._require_open()
        lineage: list[PresentationNode] = []
        current: str | None = node_id
        while current is not None and len(lineage) < 3:
            row = connection.execute(
                """SELECT n.*, COALESCE(o.display_name, n.label) AS display_label,
                          (SELECT COUNT(*) FROM presentation_nodes c WHERE c.parent_id=n.node_id)
                              AS child_count
                   FROM presentation_nodes n
                   LEFT JOIN presentation_overrides o ON o.node_id=n.node_id
                   WHERE n.node_id=? AND COALESCE(o.hidden, 0)=0""",
                (current,),
            ).fetchone()
            if row is None:
                break
            node = _node_from_row(row)
            lineage.append(node)
            current = node.parent_id
        return tuple(reversed(lineage))

    def state_variables(
        self, *, after: str | None = None, limit: int = 50
    ) -> ResultPage:
        """Return a bounded alphabetical slice of user-editable state metadata."""

        bounded = _bounded_limit(limit, MAX_RESULTS)
        clauses = [
            "p.collection='state_registry'",
            "p.record_key='authoritative'",
        ]
        parameters: list[object] = []
        if after is not None:
            clauses.append("json_extract(v.value,'$.original_name') > ?")
            parameters.append(after)
        rows = self._project._require_open().execute(
            f"""SELECT json_extract(v.value,'$.original_name') AS original_name,
                       COALESCE(json_extract(v.value,'$.display_name'),
                                json_extract(v.value,'$.original_name')) AS display_name,
                       COALESCE(json_extract(v.value,'$.category'),'uncategorized') AS category,
                       COALESCE(json_extract(v.value,'$.user_override'),0) AS user_override,
                       json_extract(v.value,'$.default_value') AS default_value,
                       COALESCE(json_extract(v.value,'$.default_declared'),0) AS default_declared,
                       json_extract(v.value,'$.metadata_source') AS metadata_source
                FROM payloads p, json_each(CAST(p.payload_json AS TEXT)) v
                WHERE {' AND '.join(clauses)}
                ORDER BY original_name LIMIT ?""",
            (*parameters, bounded + 1),
        ).fetchall()
        has_more = len(rows) > bounded
        rows = rows[:bounded]
        items = tuple(
            StateVariableRecord(
                str(row["original_name"]),
                str(row["display_name"]),
                str(row["category"]),
                bool(row["user_override"]),
                row["default_value"],
                bool(row["default_declared"]),
                None if row["metadata_source"] is None else str(row["metadata_source"]),
            )
            for row in rows
        )
        return ResultPage(
            items,
            Continuation(
                len(items), has_more, items[-1].original_name if has_more else None
            ),
        )

    def update_state_variable(
        self,
        original_name: str,
        *,
        display_name: str | None = None,
        category: str | None = None,
    ) -> None:
        self._project.update_state_variable(
            original_name, display_name=display_name, category=category
        )
        ensure_presentation_index(self._project)

    def rename_node(self, node_id: str, name: str | None) -> None:
        if name is not None and not name.strip():
            raise ValueError("presentation node name cannot be empty")
        self._update_override(node_id, display_name=name)

    def set_hidden(self, node_id: str, hidden: bool) -> None:
        self._update_override(node_id, hidden=hidden)

    def _update_override(
        self, node_id: str, *, display_name: str | None | object = ..., hidden: bool | object = ...
    ) -> None:
        connection = self._project._require_open()
        node = connection.execute(
            "SELECT level, label FROM presentation_nodes WHERE node_id = ?", (node_id,)
        ).fetchone()
        if node is None:
            raise KeyError(f"presentation node does not exist: {node_id}")
        old = connection.execute(
            "SELECT display_name, hidden FROM presentation_overrides WHERE node_id = ?", (node_id,)
        ).fetchone()
        new_name = (None if old is None else old[0]) if display_name is ... else display_name
        new_hidden = (False if old is None else bool(old[1])) if hidden is ... else bool(hidden)
        with storage.transaction(connection):
            connection.execute(
                """INSERT INTO presentation_overrides(node_id, display_name, hidden, updated_utc)
                VALUES (?, ?, ?, ?) ON CONFLICT(node_id) DO UPDATE SET
                display_name=excluded.display_name, hidden=excluded.hidden,
                updated_utc=excluded.updated_utc""",
                (node_id, new_name, int(new_hidden), storage.utc_now()),
            )
            if display_name is not ... and int(node["level"]) in {1, 2}:
                field = "label" if int(node["level"]) == 1 else "event_title"
                title = str(node["label"]) if new_name is None else str(new_name)
                connection.execute(
                    "DELETE FROM presentation_search WHERE node_id = ? AND field = ?",
                    (node_id, field),
                )
                connection.execute(
                    """INSERT INTO presentation_search(node_id, field, text, normalized)
                    VALUES (?, ?, ?, ?)""",
                    (node_id, field, title, title.casefold()),
                )


def ensure_presentation_index(
    project: Project, *, cancelled: Callable[[], bool] | None = None
) -> None:
    connection = project._require_open()
    row = connection.execute(
        "SELECT generation FROM presentation_index_state WHERE singleton = 1"
    ).fetchone()
    expected = _presentation_generation(connection)
    if row is None or str(row["generation"]) != expected:
        rebuild_presentation_index(project, cancelled=cancelled)


def rebuild_presentation_index(
    project: Project, *, cancelled: Callable[[], bool] | None = None
) -> None:
    """Build the complete derived index using SQLite JSON streaming in one transaction."""

    connection = project._require_open()
    _cancel(cancelled)
    _ensure_query_indexes(connection)
    generation = _presentation_generation(connection)
    statements = _index_statements()
    with storage.transaction(connection):
        for table in (
            "presentation_search",
            "presentation_evidence",
            "presentation_facts",
            "presentation_edges",
            "presentation_nodes",
            "presentation_index_state",
        ):
            connection.execute(f"DELETE FROM {table}")
        for statement in statements:
            _cancel(cancelled)
            connection.execute(statement)
        _apply_story_metadata_to_presentation(project)
        connection.execute(
            "INSERT INTO presentation_index_state(singleton, generation) VALUES (1, ?)",
            (generation,),
        )
        _cancel(cancelled)


def _index_statements() -> tuple[str, ...]:
    semantic = "(SELECT CAST(payload_json AS TEXT) FROM payloads WHERE collection='m02_semantic' AND record_key='authoritative')"
    return (
        f"""INSERT INTO presentation_nodes
        SELECT json_extract(j.value,'$.id'), 1, NULL, printf('%012d', CAST(j.key AS INTEGER)),
               'label', json_extract(j.value,'$.label'), json_extract(j.value,'$.source.path'),
               json_extract(j.value,'$.source.start.line'), json_extract(j.value,'$.source.end.line'),
               0, CAST(j.value AS BLOB)
        FROM json_each({semantic}, '$.scenes') j""",
        f"""INSERT INTO presentation_nodes
        WITH beats AS (
          SELECT j.value AS value, CAST(j.key AS INTEGER) AS ordinal,
                 json_extract(j.value,'$.scene_id') AS scene_id,
                 row_number() OVER (PARTITION BY json_extract(j.value,'$.scene_id')
                                    ORDER BY CAST(j.key AS INTEGER)) - 1 AS scene_ordinal
          FROM json_each({semantic}, '$.beats') j
        ), groups AS (
          SELECT scene_id, CAST(scene_ordinal / {EVENT_GROUP_SIZE} AS INTEGER) AS group_no,
                 min(ordinal) AS first_ordinal, min(json_extract(value,'$.source.path')) AS path,
                 min(json_extract(value,'$.source.start.line')) AS start_line,
                 max(json_extract(value,'$.source.end.line')) AS end_line,
                 max(CASE WHEN json_extract(value,'$.kind')='choice' THEN 1 ELSE 0 END) AS choice,
                 max(CASE WHEN json_extract(value,'$.kind')='condition' THEN 1 ELSE 0 END) AS condition
          FROM beats GROUP BY scene_id, CAST(scene_ordinal / {EVENT_GROUP_SIZE} AS INTEGER)
        )
        SELECT 'event:' || scene_id || ':' || printf('%08d',group_no), 2, scene_id,
               printf('%012d',first_ordinal),
               CASE WHEN choice=1 THEN 'choice_group' WHEN condition=1 THEN 'condition_group'
                    ELSE 'structural_group' END,
               CASE WHEN choice=1 THEN 'Choice group ' WHEN condition=1 THEN 'Condition group '
                    ELSE 'Structural group ' END || (group_no + 1), path, start_line, end_line, 0,
               CAST(json_object('deterministic',1,'group',group_no,'human_scene',0) AS BLOB)
        FROM groups""",
        f"""INSERT INTO presentation_nodes
        WITH beats AS (
          SELECT j.value AS value, CAST(j.key AS INTEGER) AS ordinal,
                 json_extract(j.value,'$.scene_id') AS scene_id,
                 row_number() OVER (PARTITION BY json_extract(j.value,'$.scene_id')
                                    ORDER BY CAST(j.key AS INTEGER)) - 1 AS scene_ordinal
          FROM json_each({semantic}, '$.beats') j
        )
        SELECT json_extract(value,'$.id'), 3,
               'event:' || scene_id || ':' || printf('%08d',CAST(scene_ordinal / {EVENT_GROUP_SIZE} AS INTEGER)),
               printf('%012d',ordinal), json_extract(value,'$.kind'),
               COALESCE(json_extract(value,'$.choices[0].caption'),
                        json_extract(value,'$.content[0].text'),
                        json_extract(value,'$.source_text'), json_extract(value,'$.kind')),
               json_extract(value,'$.source.path'), json_extract(value,'$.source.start.line'),
               json_extract(value,'$.source.end.line'),
               CASE WHEN json_extract(value,'$.kind') IN ('opaque','statement','module_end') THEN 1 ELSE 0 END,
               CAST(value AS BLOB) FROM beats""",
        f"""INSERT INTO presentation_edges
        SELECT 'l1:' || json_extract(j.value,'$.id'), 1,
               json_extract(j.value,'$.source_scene_id'), json_extract(j.value,'$.target_scene_id'),
               printf('%012d',CAST(j.key AS INTEGER)), json_extract(j.value,'$.kind'), CAST(j.value AS BLOB)
        FROM json_each({semantic}, '$.transitions') j
        WHERE json_extract(j.value,'$.source_scene_id') IS NOT NULL
          AND json_extract(j.value,'$.target_scene_id') IS NOT NULL
        GROUP BY json_extract(j.value,'$.source_scene_id'), json_extract(j.value,'$.target_scene_id'),
                 json_extract(j.value,'$.kind')""",
        f"""INSERT INTO presentation_edges
        SELECT 'l3:' || json_extract(j.value,'$.id'), 3,
               json_extract(j.value,'$.source_beat_id'), json_extract(j.value,'$.target_beat_id'),
               printf('%012d',CAST(j.key AS INTEGER)), json_extract(j.value,'$.kind'), CAST(j.value AS BLOB)
        FROM json_each({semantic}, '$.transitions') j
        WHERE json_extract(j.value,'$.source_beat_id') IS NOT NULL
          AND json_extract(j.value,'$.target_beat_id') IS NOT NULL""",
        """INSERT INTO presentation_edges
        SELECT 'l2:' || e.edge_id, 2, s.parent_id, t.parent_id, e.sort_key, e.kind, e.payload_json
        FROM presentation_edges e JOIN presentation_nodes s ON s.node_id=e.source_id
        JOIN presentation_nodes t ON t.node_id=e.target_id
        WHERE e.level=3 AND s.parent_id<>t.parent_id GROUP BY s.parent_id,t.parent_id,e.kind""",
        """INSERT INTO presentation_evidence
        SELECT 'beat:' || node_id, node_id, sort_key, kind, source_path, start_line, end_line,
               label, payload_json FROM presentation_nodes WHERE level=3""",
        _facts_insert_sql("gates", "gate"),
        _facts_insert_sql("effects", "effect"),
        """INSERT INTO presentation_search(node_id,field,text,normalized)
        SELECT n.node_id,CASE WHEN n.level=1 THEN 'label' ELSE 'event_title' END,
               COALESCE(o.display_name,n.label),lower(COALESCE(o.display_name,n.label))
        FROM presentation_nodes n LEFT JOIN presentation_overrides o ON o.node_id=n.node_id
        WHERE n.level IN (1,2)""",
        """INSERT INTO presentation_search(node_id,field,text,normalized)
        SELECT n.node_id,'source_evidence',e.text,lower(e.text) FROM presentation_evidence e
        JOIN presentation_nodes n ON n.node_id=e.node_id""",
        """INSERT INTO presentation_search(node_id,field,text,normalized)
        SELECT node_id,CASE WHEN json_extract(c.value,'$.kind')='dialogue' THEN 'dialogue' ELSE 'narration' END,
               json_extract(c.value,'$.text'),lower(json_extract(c.value,'$.text'))
        FROM presentation_nodes n,json_each(CAST(n.payload_json AS TEXT),'$.content') c
        WHERE n.level=3 AND json_extract(c.value,'$.text') IS NOT NULL""",
        """INSERT INTO presentation_search(node_id,field,text,normalized)
        SELECT node_id,'choice',json_extract(c.value,'$.caption'),lower(json_extract(c.value,'$.caption'))
        FROM presentation_nodes n,json_each(CAST(n.payload_json AS TEXT),'$.choices') c
        WHERE n.level=3 AND json_extract(c.value,'$.caption') IS NOT NULL""",
        """INSERT INTO presentation_search(node_id,field,text,normalized)
        SELECT node_id,'condition',json_extract(c.value,'$.condition'),lower(json_extract(c.value,'$.condition'))
        FROM presentation_nodes n,json_each(CAST(n.payload_json AS TEXT),'$.choices') c
        WHERE n.level=3 AND json_extract(c.value,'$.condition') IS NOT NULL""",
        """INSERT INTO presentation_search(node_id,field,text,normalized)
        SELECT node_id,'condition',json_extract(c.value,'$.condition'),lower(json_extract(c.value,'$.condition'))
        FROM presentation_nodes n,json_each(CAST(n.payload_json AS TEXT),'$.branches') c
        WHERE n.level=3 AND json_extract(c.value,'$.condition') IS NOT NULL""",
        """INSERT INTO presentation_search(node_id,field,text,normalized)
        SELECT COALESCE(node_id,fact_id),CASE WHEN variable IS NULL THEN 'source_evidence' ELSE 'variable' END,
               COALESCE(variable,expression),lower(COALESCE(variable,expression)) FROM presentation_facts""",
        """INSERT INTO presentation_search(node_id,field,text,normalized)
        SELECT COALESCE(node_id,fact_id),'source_evidence',expression,lower(expression)
        FROM presentation_facts""",
        """INSERT INTO presentation_search(node_id,field,text,normalized)
        SELECT COALESCE(node_id,fact_id),'source_evidence',source_path,lower(source_path)
        FROM presentation_facts""",
    )


def _facts_insert_sql(collection: str, kind: str) -> str:
    return f"""WITH registry(original_name, category) AS MATERIALIZED (
      SELECT json_extract(v.value,'$.original_name'), json_extract(v.value,'$.category')
      FROM payloads p2, json_each(CAST(p2.payload_json AS TEXT)) v
      WHERE p2.collection='state_registry' AND p2.record_key='authoritative'
    )
    INSERT INTO presentation_facts
    SELECT json_extract(j.value,'$.id'),
           (SELECT n.node_id FROM presentation_nodes n
            WHERE n.level=3 AND n.source_path=json_extract(j.value,'$.evidence.source_path')
              AND n.start_line<=json_extract(j.value,'$.evidence.start_line')
              AND n.end_line>=json_extract(j.value,'$.evidence.start_line')
            ORDER BY n.start_line DESC,n.end_line,n.sort_key LIMIT 1),
           '{kind}', COALESCE(json_extract(j.value,'$.variable'),json_extract(j.value,'$.variables[0]')),
           r.category,
           json_extract(j.value,'$.status'), json_extract(j.value,'$.original_expression'),
           json_extract(j.value,'$.evidence.source_path'),json_extract(j.value,'$.evidence.start_line'),
           json_extract(j.value,'$.evidence.end_line'),
           json_extract(j.value,'$.evidence.source_path') || ':' ||
             printf('%09d',json_extract(j.value,'$.evidence.start_line')) || ':' || json_extract(j.value,'$.id'),
           CAST(j.value AS BLOB)
    FROM payloads p,json_each(CAST(p.payload_json AS TEXT)) j
    LEFT JOIN registry r ON r.original_name=
      COALESCE(json_extract(j.value,'$.variable'),json_extract(j.value,'$.variables[0]'))
    WHERE p.collection='{collection}'"""


def _apply_story_metadata_to_presentation(project: Project) -> None:
    """Apply only exact advisory matches to the derived presentation index."""

    raw = project.payload("story_metadata", "authoritative")
    if not isinstance(raw, Mapping) or raw.get("schema_version") != 1:
        return
    connection = project._require_open()
    aliases = _metadata_text_map(raw.get("characters"), "alias", "display_name")
    titles = _metadata_text_map(raw.get("scene_titles"), "key", "title")
    title_sources = _metadata_text_map(raw.get("scene_titles"), "key", "source")

    for row in connection.execute(
        "SELECT node_id,label,payload_json FROM presentation_nodes WHERE level=1"
    ).fetchall():
        node_id = str(row["node_id"])
        label = str(row["label"])
        if label not in titles:
            continue
        key = label
        payload = storage.decode_json(row["payload_json"])
        if not isinstance(payload, dict):
            continue
        enriched = dict(payload)
        enriched["metadata_title"] = {
            "key": key,
            "title": titles[key],
            "source": title_sources.get(key),
        }
        connection.execute(
            "UPDATE presentation_nodes SET label=?,payload_json=? WHERE node_id=?",
            (titles[key], storage.canonical_json(enriched), node_id),
        )

    character_search: set[tuple[str, str]] = set()
    for row in connection.execute(
        "SELECT node_id,payload_json FROM presentation_nodes WHERE level=3"
    ).fetchall():
        payload = storage.decode_json(row["payload_json"])
        if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
            continue
        changed = False
        content: list[object] = []
        for raw_item in payload["content"]:
            if not isinstance(raw_item, dict):
                content.append(raw_item)
                continue
            item = dict(raw_item)
            speaker = item.get("speaker")
            display_name = aliases.get(speaker) if isinstance(speaker, str) else None
            if display_name is not None:
                item["speaker_display_name"] = display_name
                character_search.add((str(row["node_id"]), display_name))
                changed = True
            content.append(item)
        if changed:
            enriched = dict(payload)
            enriched["content"] = content
            connection.execute(
                "UPDATE presentation_nodes SET payload_json=? WHERE node_id=?",
                (storage.canonical_json(enriched), str(row["node_id"])),
            )

    connection.execute(
        """UPDATE presentation_evidence
           SET payload_json=(SELECT n.payload_json FROM presentation_nodes n
                             WHERE n.node_id=presentation_evidence.node_id)
           WHERE node_id IN (SELECT node_id FROM presentation_nodes WHERE level=3)"""
    )

    registry = project.payload("state_registry", "authoritative")
    display_names = {
        str(value["original_name"]): str(value["display_name"])
        for value in registry
        if isinstance(value, dict)
        and isinstance(value.get("original_name"), str)
        and isinstance(value.get("display_name"), str)
    } if isinstance(registry, list) else {}
    for row in connection.execute(
        "SELECT fact_id,variable,payload_json FROM presentation_facts WHERE variable IS NOT NULL"
    ).fetchall():
        display_name = display_names.get(str(row["variable"]))
        payload = storage.decode_json(row["payload_json"])
        if display_name is None or not isinstance(payload, dict):
            continue
        enriched = dict(payload)
        enriched["variable_display_name"] = display_name
        connection.execute(
            "UPDATE presentation_facts SET payload_json=? WHERE fact_id=?",
            (storage.canonical_json(enriched), str(row["fact_id"])),
        )

    connection.execute(
        "DELETE FROM presentation_search WHERE field IN ('label','event_title','character')"
    )
    connection.execute(
        """INSERT INTO presentation_search(node_id,field,text,normalized)
           SELECT n.node_id,CASE WHEN n.level=1 THEN 'label' ELSE 'event_title' END,
                  COALESCE(o.display_name,n.label),lower(COALESCE(o.display_name,n.label))
           FROM presentation_nodes n LEFT JOIN presentation_overrides o ON o.node_id=n.node_id
           WHERE n.level IN (1,2)"""
    )
    connection.executemany(
        """INSERT INTO presentation_search(node_id,field,text,normalized)
           VALUES (?,'character',?,?)""",
        ((node_id, name, name.casefold()) for node_id, name in sorted(character_search)),
    )


def _metadata_text_map(
    value: object, key_field: str, value_field: str
) -> dict[str, str]:
    result: dict[str, str] = {}
    duplicates: set[str] = set()
    if not isinstance(value, list):
        return result
    for raw in value:
        if not isinstance(raw, dict):
            continue
        key = raw.get(key_field)
        text = raw.get(value_field)
        if not isinstance(key, str) or not key or not isinstance(text, str) or not text:
            continue
        if key in result or key in duplicates:
            result.pop(key, None)
            duplicates.add(key)
            continue
        result[key] = text
    return result


def _node_from_row(row: sqlite3.Row) -> PresentationNode:
    child_count = int(row["child_count"])
    return PresentationNode(
        str(row["node_id"]), PresentationLevel(int(row["level"])),
        None if row["parent_id"] is None else str(row["parent_id"]), str(row["kind"]),
        str(row["display_label"]), None if row["source_path"] is None else str(row["source_path"]),
        None if row["start_line"] is None else int(row["start_line"]),
        None if row["end_line"] is None else int(row["end_line"]), bool(row["technical"]),
        child_count > 0, child_count, storage.decode_json(row["payload_json"]),
    )


def _evidence_from_row(row: sqlite3.Row) -> EvidenceRecord:
    return EvidenceRecord(
        str(row["evidence_id"]), str(row["node_id"]), str(row["kind"]),
        str(row["source_path"]), int(row["start_line"]), int(row["end_line"]),
        str(row["text"]), storage.decode_json(row["payload_json"]),
    )


def _fact_from_row(row: sqlite3.Row) -> FactRecord:
    payload = storage.decode_json(row["payload_json"])
    display_name = (
        str(payload["variable_display_name"])
        if isinstance(payload, dict) and isinstance(payload.get("variable_display_name"), str)
        else None
    )
    return FactRecord(
        str(row["fact_id"]), None if row["node_id"] is None else str(row["node_id"]),
        str(row["fact_kind"]), None if row["variable"] is None else str(row["variable"]),
        None if row["category"] is None else str(row["category"]), str(row["status"]),
        str(row["expression"]), str(row["source_path"]), int(row["start_line"]),
        int(row["end_line"]), payload, display_name,
    )


def _bounded_limit(value: int, maximum: int) -> int:
    if value <= 0:
        raise ValueError("result limit must be positive")
    return min(value, maximum)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _presentation_generation(connection: sqlite3.Connection) -> str:
    """Hash every canonical payload row that contributes to the derived index."""

    rows = connection.execute(
        """SELECT collection, record_key, payload_hash FROM payloads
        WHERE collection IN (
          'm02_semantic', 'gates', 'effects', 'state_registry', 'story_metadata'
        )
        ORDER BY collection, record_key"""
    )
    digest = hashlib.sha256()
    for row in rows:
        for value in (str(row["collection"]), str(row["record_key"]), str(row["payload_hash"])):
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
    return digest.hexdigest()


def _ensure_query_indexes(connection: sqlite3.Connection) -> None:
    for statement in (
        """CREATE INDEX IF NOT EXISTS presentation_nodes_parent_lookup_idx
        ON presentation_nodes(parent_id, node_id)""",
        """CREATE INDEX IF NOT EXISTS presentation_nodes_source_idx
        ON presentation_nodes(level, source_path, start_line, end_line, sort_key)""",
        """CREATE INDEX IF NOT EXISTS presentation_edges_source_idx
        ON presentation_edges(level, source_id, target_id, edge_id)""",
        """CREATE INDEX IF NOT EXISTS presentation_facts_node_idx
        ON presentation_facts(node_id, sort_key, fact_id)""",
    ):
        connection.execute(statement)


def _cancel(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise storage.ProjectOperationCancelled("project operation was cancelled")


def _query_cancel(
    service_cancelled: Callable[[], bool] | None,
    call_cancelled: Callable[[], bool] | None,
) -> None:
    if _query_cancel_requested(service_cancelled, call_cancelled):
        raise storage.ProjectOperationCancelled("project operation was cancelled")


def _query_cancel_requested(
    service_cancelled: Callable[[], bool] | None,
    call_cancelled: Callable[[], bool] | None,
) -> bool:
    if service_cancelled is not None and service_cancelled():
        return True
    return (
        call_cancelled is not None
        and call_cancelled is not service_cancelled
        and call_cancelled()
    )


def _validated_selected_node_ids(node_ids: Sequence[str]) -> tuple[str, ...]:
    if isinstance(node_ids, (str, bytes)) or any(
        not isinstance(node_id, str) or not node_id for node_id in node_ids
    ):
        raise ValueError("node_ids must contain non-empty strings")
    return tuple(sorted(set(node_ids)))


def _reject_unknown_level_three_nodes(
    connection: sqlite3.Connection,
    selection_table: str,
    service_cancelled: Callable[[], bool] | None,
    call_cancelled: Callable[[], bool] | None,
) -> None:
    if selection_table not in {
        "selected_presentation_evidence_nodes",
        "selected_presentation_fact_nodes",
    }:
        raise AssertionError("unexpected temporary node-selection table")
    _query_cancel(service_cancelled, call_cancelled)
    unknown = connection.execute(
        f"""SELECT selected.node_id FROM {selection_table} selected
            LEFT JOIN presentation_nodes node
              ON node.node_id=selected.node_id AND node.level=3
            WHERE node.node_id IS NULL ORDER BY selected.node_id LIMIT 1"""
    ).fetchone()
    if unknown is not None:
        raise ValueError(
            f"unknown Level-3 presentation node: {unknown['node_id']}"
        )
    _query_cancel(service_cancelled, call_cancelled)


def deterministic_id(prefix: str, values: Iterable[str]) -> str:
    """Return a stable presentation ID for callers creating deterministic extensions."""

    digest = hashlib.sha256("\0".join(values).encode()).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _chunks(values: tuple[str, ...], size: int) -> Iterable[tuple[str, ...]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]
