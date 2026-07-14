from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, order=True)
class SourceSpan:
    path: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "start": {"line": self.start_line, "column": self.start_column},
            "end": {"line": self.end_line, "column": self.end_column},
        }


@dataclass
class Statement:
    span: SourceSpan
    text: str


@dataclass
class Simple(Statement):
    kind: str = "statement"


@dataclass
class Jump(Statement):
    target: str | None = None
    expression: str | None = None


@dataclass
class Call(Statement):
    target: str | None = None
    expression: str | None = None


@dataclass
class Return(Statement):
    expression: str | None = None


@dataclass
class Opaque(Statement):
    reason: str = "unsupported_statement"
    body: list[Statement] = field(default_factory=list)


@dataclass
class LabelAnchor(Statement):
    name: str = ""
    body: list[Statement] = field(default_factory=list)


@dataclass
class MenuChoice:
    caption: str
    condition: str | None
    span: SourceSpan
    text: str
    body: list[Statement]


@dataclass
class MenuCaption:
    caption: str
    span: SourceSpan
    text: str


@dataclass
class Menu(Statement):
    choices: list[MenuChoice] = field(default_factory=list)
    captions: list[MenuCaption] = field(default_factory=list)
    availability_unresolved: bool = False


@dataclass
class IfBranch:
    condition: str | None
    span: SourceSpan
    text: str
    body: list[Statement]


@dataclass
class If(Statement):
    branches: list[IfBranch] = field(default_factory=list)


@dataclass
class Label:
    name: str
    span: SourceSpan
    text: str
    body: list[Statement]


@dataclass
class ScriptModule:
    path: str
    labels: list[Label]
    top_level: list[Statement]
    diagnostics: list[dict[str, object]]


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: str
    span: SourceSpan
    text: str
    label: str
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "source": self.span.to_dict(),
            "source_text": self.text,
        }
        if self.metadata:
            value["metadata"] = self.metadata
        return value


@dataclass(frozen=True, order=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    metadata_items: tuple[tuple[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
        }
        if self.metadata_items:
            value["metadata"] = dict(self.metadata_items)
        return value


type StatementType = Simple | Jump | Call | Return | Opaque | LabelAnchor | Menu | If
