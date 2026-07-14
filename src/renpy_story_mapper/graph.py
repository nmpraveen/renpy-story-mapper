from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass

from renpy_story_mapper.errors import ScriptParseError
from renpy_story_mapper.model import (
    Call,
    GraphEdge,
    GraphNode,
    If,
    Jump,
    Label,
    LabelAnchor,
    Menu,
    Opaque,
    Return,
    ScriptModule,
    Simple,
    SourceSpan,
    Statement,
)


@dataclass(frozen=True)
class _Transfer:
    node_id: str
    target: str | None
    expression: str | None
    continuation: str | None
    label: str
    kind: str


class GraphBuilder:
    def __init__(
        self,
        modules: list[ScriptModule],
        *,
        entry_label: str = "start",
        scope_paths: set[str] | None = None,
    ) -> None:
        self.modules = modules
        self.entry_label = entry_label
        self.scope_paths = scope_paths
        self.labels: dict[str, Label] = {}
        for module in modules:
            for label in module.labels:
                if label.name in self.labels:
                    other = self.labels[label.name]
                    raise ScriptParseError(
                        f"duplicate label {label.name!r} at {other.span.path}:"
                        f"{other.span.start_line} and {label.span.path}:{label.span.start_line}"
                    )
                self.labels[label.name] = label
        if entry_label not in self.labels:
            raise ScriptParseError(f"entry label {entry_label!r} was not found")

        self.allowed = {
            name
            for name, label in self.labels.items()
            if scope_paths is None or label.span.path in scope_paths or name == entry_label
        }
        self.nodes: dict[str, GraphNode] = {}
        self.edges: set[GraphEdge] = set()
        self.label_node_ids: dict[str, str] = {}
        self.return_ids: dict[str, list[str]] = defaultdict(list)
        self.transfers: list[_Transfer] = []

    def build(self) -> dict[str, object]:
        for name in sorted(self.allowed):
            label = self.labels[name]
            label_node = self._node("label", label.span, label.text, name, {"name": name})
            self.label_node_ids[name] = label_node

        for module in sorted(self.modules, key=lambda item: item.path):
            statements = [
                statement
                for statement in module.top_level
                if not isinstance(statement, LabelAnchor) or statement.name in self.allowed
            ]
            if not statements:
                continue
            end_span = statements[-1].span
            module_end = self._node(
                "module_end",
                end_span,
                "<end of source module>",
                f"<module:{module.path}>",
                {"path": module.path},
                "module_end",
            )
            self._build_block(statements, module_end, f"<module:{module.path}>")

        self._resolve_transfers()
        self._connect_returns()
        reachable = self._reachable(self.label_node_ids[self.entry_label])
        included = self._included_nodes()
        nodes = [self.nodes[node_id] for node_id in included]
        edges = [edge for edge in self.edges if edge.source in included and edge.target in included]
        nodes.sort(key=lambda node: node.id)
        edges.sort(
            key=lambda edge: (
                edge.source,
                edge.target,
                edge.kind,
                repr(edge.metadata_items),
            )
        )
        unresolved = [node for node in nodes if node.kind == "unresolved"]
        reachable_labels = sorted(
            str(node.metadata["name"])
            for node in nodes
            if node.id in reachable and node.kind == "label" and "name" in node.metadata
        )
        node_values = []
        for node in nodes:
            value = node.to_dict()
            value["reachable_from_entry"] = node.id in reachable
            node_values.append(value)
        return {
            "schema_version": 1,
            "entry_label": self.entry_label,
            "scope": {
                "mode": "source_paths" if self.scope_paths is not None else "all_sources",
                "source_paths": sorted(self.scope_paths) if self.scope_paths is not None else None,
            },
            "semantics": {
                "expressions_evaluated": False,
                "creator_code_executed": False,
                "call_continuation_edges_are_summary_edges": True,
                "menu_no_choice_fallthrough_preserved": True,
            },
            "counts": {
                "nodes": len(nodes),
                "edges": len(edges),
                "unresolved": len(unresolved),
                "reachable_labels": len(reachable_labels),
                "labels_in_scope": len(self.allowed),
                "nodes_reachable_from_entry": len(reachable),
            },
            "reachable_labels": reachable_labels,
            "nodes": node_values,
            "edges": [edge.to_dict() for edge in edges],
        }

    def _build_block(self, statements: list[Statement], continuation: str, label: str) -> str:
        next_node = continuation
        for ordinal, statement in reversed(list(enumerate(statements))):
            next_node = self._build_statement(statement, next_node, label, ordinal)
        return next_node

    def _build_statement(
        self, statement: Statement, continuation: str, label: str, ordinal: int
    ) -> str:
        discriminator = str(ordinal)
        if isinstance(statement, Jump):
            node = self._node(
                "jump", statement.span, statement.text, label, discriminator=discriminator
            )
            self.transfers.append(
                _Transfer(node, statement.target, statement.expression, None, label, "jump")
            )
            return node
        if isinstance(statement, Call):
            node = self._node(
                "call", statement.span, statement.text, label, discriminator=discriminator
            )
            self._edge(
                node,
                continuation,
                "call_continuation",
                {"semantic": "return_site_not_immediate_fallthrough"},
            )
            self.transfers.append(
                _Transfer(node, statement.target, statement.expression, continuation, label, "call")
            )
            return node
        if isinstance(statement, Return):
            node = self._node(
                "return",
                statement.span,
                statement.text,
                label,
                {"expression": statement.expression},
                discriminator,
            )
            self.return_ids[label].append(node)
            return node
        if isinstance(statement, LabelAnchor):
            if statement.name not in self.allowed:
                boundary = self._node(
                    "scope_boundary",
                    statement.span,
                    statement.text,
                    label,
                    {"target_label": statement.name},
                    f"anchor:{statement.name}",
                )
                self._edge(boundary, continuation, "fallthrough")
                return boundary
            anchor = self.label_node_ids[statement.name]
            body_entry = self._build_block(statement.body, continuation, statement.name)
            self._edge(anchor, body_entry, "label_entry")
            return anchor
        if isinstance(statement, Menu):
            merge = self._node(
                "merge",
                statement.span,
                statement.text,
                label,
                {"control": "menu"},
                f"{ordinal}:merge",
            )
            self._edge(merge, continuation, "fallthrough")
            menu_metadata: dict[str, object] = {
                "captions": [
                    {"text": caption.caption, "source": caption.span.to_dict()}
                    for caption in statement.captions
                ]
            }
            if statement.availability_unresolved:
                menu_metadata["availability_unresolved"] = True
            menu = self._node(
                "menu",
                statement.span,
                statement.text,
                label,
                menu_metadata,
                discriminator,
            )
            no_choice_metadata: dict[str, object] | None = (
                {"availability_unresolved": True}
                if statement.availability_unresolved
                else None
            )
            self._edge(menu, merge, "menu_no_choice", no_choice_metadata)
            for choice_index, choice in enumerate(statement.choices):
                choice_node = self._node(
                    "menu_choice",
                    choice.span,
                    choice.text,
                    label,
                    {"caption": choice.caption, "condition": choice.condition},
                    f"{ordinal}:choice:{choice_index}",
                )
                body_entry = self._build_block(choice.body, merge, label)
                self._edge(
                    menu,
                    choice_node,
                    "menu_choice",
                    {"choice_index": choice_index, "condition": choice.condition},
                )
                self._edge(choice_node, body_entry, "choice_body")
            return menu
        if isinstance(statement, If):
            merge = self._node(
                "merge",
                statement.span,
                statement.text,
                label,
                {"control": "if"},
                f"{ordinal}:merge",
            )
            self._edge(merge, continuation, "fallthrough")
            if_node = self._node(
                "if", statement.span, statement.text, label, discriminator=discriminator
            )
            has_else = False
            for branch_index, branch in enumerate(statement.branches):
                branch_node = self._node(
                    "if_branch",
                    branch.span,
                    branch.text,
                    label,
                    {"condition": branch.condition},
                    f"{ordinal}:branch:{branch_index}",
                )
                body_entry = self._build_block(branch.body, merge, label)
                self._edge(
                    if_node,
                    branch_node,
                    "condition",
                    {"branch_index": branch_index, "condition": branch.condition},
                )
                self._edge(branch_node, body_entry, "branch_body")
                has_else = has_else or branch.condition is None
            if not has_else:
                self._edge(if_node, merge, "condition_false")
            return if_node
        if isinstance(statement, Opaque):
            node = self._node(
                "opaque",
                statement.span,
                statement.text,
                label,
                {"reason": statement.reason, "executed": False},
                discriminator,
            )
            self._edge(node, continuation, "fallthrough")
            if statement.reason in (
                "unsupported_control_flow",
                "creator_or_unsupported_block",
                "interactive_screen_call",
            ):
                unresolved = self._unresolved(
                    statement.span,
                    statement.text,
                    label,
                    statement.reason,
                    f"opaque:{node}",
                )
                self._edge(node, unresolved, "unresolved_behavior")
            return node
        if isinstance(statement, Simple):
            node = self._node(
                statement.kind,
                statement.span,
                statement.text,
                label,
                discriminator=discriminator,
            )
            self._edge(node, continuation, "fallthrough")
            return node
        raise TypeError(f"unsupported statement node: {type(statement).__name__}")

    def _resolve_transfers(self) -> None:
        for transfer in self.transfers:
            if transfer.expression is not None:
                unresolved = self._unresolved(
                    self.nodes[transfer.node_id].span,
                    self.nodes[transfer.node_id].text,
                    transfer.label,
                    f"dynamic_{transfer.kind}_target",
                    transfer.node_id,
                    {"expression": transfer.expression},
                )
                self._edge(transfer.node_id, unresolved, f"dynamic_{transfer.kind}")
                continue
            assert transfer.target is not None
            if transfer.target in self.allowed:
                self._edge(transfer.node_id, self.label_node_ids[transfer.target], transfer.kind)
            elif transfer.target in self.labels:
                label = self.labels[transfer.target]
                external = self._node(
                    "scope_boundary",
                    label.span,
                    label.text,
                    transfer.label,
                    {"target_label": transfer.target},
                    f"scope:{transfer.target}",
                )
                self._edge(transfer.node_id, external, f"{transfer.kind}_out_of_scope")
            else:
                unresolved = self._unresolved(
                    self.nodes[transfer.node_id].span,
                    self.nodes[transfer.node_id].text,
                    transfer.label,
                    "missing_label",
                    transfer.node_id,
                    {"target_label": transfer.target, "transfer": transfer.kind},
                )
                self._edge(transfer.node_id, unresolved, f"missing_{transfer.kind}")

    def _connect_returns(self) -> None:
        call_sites: dict[str, list[str]] = defaultdict(list)
        for transfer in self.transfers:
            if (
                transfer.kind == "call"
                and transfer.expression is None
                and transfer.target in self.allowed
                and transfer.continuation is not None
            ):
                call_sites[transfer.target].append(transfer.continuation)
        for target, continuations in call_sites.items():
            return_nodes = list(self.return_ids[target])
            for return_node in return_nodes:
                for continuation in sorted(set(continuations)):
                    self._edge(
                        return_node,
                        continuation,
                        "return",
                        {"called_label": target},
                    )

    def _node(
        self,
        kind: str,
        span: SourceSpan,
        text: str,
        label: str,
        metadata: dict[str, object] | None = None,
        discriminator: str = "",
    ) -> str:
        identity = (
            f"{kind}\0{span.path}\0{span.start_line}\0{span.start_column}\0"
            f"{span.end_line}\0{span.end_column}\0{label}\0{discriminator}"
        )
        node_id = f"n_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}"
        candidate = GraphNode(node_id, kind, span, text, label, metadata or {})
        existing = self.nodes.get(node_id)
        if existing is not None and existing != candidate:
            raise ScriptParseError(f"deterministic node id collision for {node_id}")
        self.nodes[node_id] = candidate
        return node_id

    def _unresolved(
        self,
        span: SourceSpan,
        text: str,
        label: str,
        reason: str,
        discriminator: str,
        metadata: dict[str, object] | None = None,
    ) -> str:
        values: dict[str, object] = {"reason": reason}
        if metadata:
            values.update(metadata)
        return self._node("unresolved", span, text, label, values, discriminator)

    def _edge(
        self,
        source: str,
        target: str,
        kind: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        items = tuple(sorted((metadata or {}).items()))
        self.edges.add(GraphEdge(source, target, kind, items))

    def _reachable(self, entry: str) -> set[str]:
        return self._reachable_from((entry,))

    def _reachable_from(self, entries: Iterable[str]) -> set[str]:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in self.edges:
            adjacency[edge.source].append(edge.target)
        seen: set[str] = set()
        pending = deque(sorted(entries))
        while pending:
            node = pending.popleft()
            if node in seen:
                continue
            seen.add(node)
            pending.extend(sorted(adjacency[node]))
        return seen

    def _included_nodes(self) -> set[str]:
        """All scoped label CFGs plus boundary/unresolved nodes directly attached to them."""

        roots = (self.label_node_ids[name] for name in sorted(self.allowed))
        return self._reachable_from(roots)


def build_graph(
    modules: list[ScriptModule],
    *,
    entry_label: str = "start",
    scope_paths: set[str] | None = None,
) -> dict[str, object]:
    return GraphBuilder(modules, entry_label=entry_label, scope_paths=scope_paths).build()
