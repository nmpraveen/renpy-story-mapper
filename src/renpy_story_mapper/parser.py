from __future__ import annotations

import ast as python_ast
from collections.abc import Iterable
from dataclasses import dataclass

from renpy_story_mapper.errors import ScriptParseError
from renpy_story_mapper.model import (
    Call,
    If,
    IfBranch,
    Jump,
    Label,
    LabelAnchor,
    Menu,
    MenuCaption,
    MenuChoice,
    Opaque,
    Return,
    ScriptModule,
    Simple,
    SourceSpan,
    Statement,
)

# Generated declaration tables in real games can legitimately exceed Ren'Py's historical
# physical-line guard. This still provides a firm allocation bound while accepting the sample.
MAX_LOGICAL_LINE = 1024 * 1024


@dataclass(frozen=True)
class _LogicalLine:
    path: str
    start_line: int
    end_line: int
    indent: int
    code: str
    end_column: int

    @property
    def span(self) -> SourceSpan:
        return SourceSpan(
            self.path,
            self.start_line,
            self.indent + 1,
            self.end_line,
            self.end_column,
        )


@dataclass
class _ScanState:
    quote: str | None = None
    escaped: bool = False
    bracket_depth: int = 0


def _scan_code(text: str, state: _ScanState) -> str:
    """Return code before an unquoted comment and update lexical continuation state."""

    output: list[str] = []
    index = 0
    while index < len(text):
        if state.quote is not None:
            quote = state.quote
            if len(quote) == 3 and text.startswith(quote, index) and not state.escaped:
                output.extend(quote)
                index += 3
                state.quote = None
                continue
            char = text[index]
            output.append(char)
            if len(quote) == 1 and char == quote and not state.escaped:
                state.quote = None
            if char == "\\" and not state.escaped:
                state.escaped = True
            else:
                state.escaped = False
            index += 1
            continue

        if text.startswith("'''", index) or text.startswith('\"\"\"', index):
            state.quote = text[index : index + 3]
            state.escaped = False
            output.extend(state.quote)
            index += 3
            continue
        char = text[index]
        if char in ("'", '\"'):
            state.quote = char
            state.escaped = False
            output.append(char)
        elif char == "#":
            break
        else:
            output.append(char)
            if char in "([{":
                state.bracket_depth += 1
            elif char in ")]}" and state.bracket_depth:
                state.bracket_depth -= 1
        index += 1
    return "".join(output)


def _logical_lines(path: str, physical_lines: Iterable[str]) -> list[_LogicalLine]:
    logical: list[_LogicalLine] = []
    state = _ScanState()
    parts: list[str] = []
    start_line = 0
    indent = 0
    continuation = False
    end_column = 1

    for line_number, raw_line in enumerate(physical_lines, 1):
        line = raw_line.rstrip("\r\n")
        if not parts:
            prefix_length = len(line) - len(line.lstrip(" \t"))
            prefix = line[:prefix_length]
            if "\t" in prefix:
                raise ScriptParseError(f"{path}:{line_number}: tab indentation is not supported")
            indent = len(prefix)
            start_line = line_number
            content = line[indent:]
        else:
            content = line.lstrip()

        scanned = _scan_code(content, state)
        physical_indent = len(line) - len(line.lstrip(" "))
        end_column = physical_indent + len(scanned.rstrip()) + 1
        if parts or scanned.strip():
            parts.append(scanned.rstrip())
        continuation = scanned.rstrip().endswith("\\") and state.quote is None
        size = sum(len(part) + 1 for part in parts)
        if size > MAX_LOGICAL_LINE:
            raise ScriptParseError(
                f"{path}:{start_line}: logical line exceeds {MAX_LOGICAL_LINE} characters"
            )
        if parts and state.quote is None and state.bracket_depth == 0 and not continuation:
            code = "\n".join(parts).rstrip()
            if code.strip():
                logical.append(
                    _LogicalLine(path, start_line, line_number, indent, code, end_column)
                )
            parts = []
            state = _ScanState()

    if parts:
        if state.quote is not None or state.bracket_depth:
            raise ScriptParseError(f"{path}:{start_line}: unterminated string or bracket")
        code = "\n".join(parts).rstrip()
        if code.strip():
            logical.append(_LogicalLine(path, start_line, line_number, indent, code, end_column))
    return logical


def _head(text: str) -> tuple[str, str]:
    stripped = text.lstrip()
    if stripped.startswith("$"):
        return "$", stripped[1:].lstrip()
    index = 0
    while index < len(stripped) and (stripped[index].isalnum() or stripped[index] == "_"):
        index += 1
    return stripped[:index], stripped[index:].lstrip()


def _remove_terminal_colon(text: str) -> str | None:
    stripped = text.rstrip()
    if not stripped.endswith(":"):
        return None
    return stripped[:-1].rstrip()


def _static_name(text: str) -> tuple[str | None, str]:
    stripped = text.strip()
    index = 0
    if stripped.startswith("."):
        index = 1
    while index < len(stripped) and (
        stripped[index].isalnum() or stripped[index] in ("_", ".")
    ):
        index += 1
    name = stripped[:index]
    return (name or None), stripped[index:].strip()


def _resolve_local(name: str | None, current_global: str) -> str | None:
    if name is None:
        return None
    if name.startswith("."):
        return f"{current_global}{name}" if current_global else name
    return name


def _parse_string_literal_prefix(source: str) -> tuple[str, str] | None:
    source = source.lstrip()
    if not source or source[0] not in ("'", '\"'):
        return None
    quote = source[0]
    triple = source.startswith(quote * 3)
    delimiter = quote * (3 if triple else 1)
    index = len(delimiter)
    escaped = False
    while index < len(source):
        if source.startswith(delimiter, index) and not escaped:
            index += len(delimiter)
            break
        char = source[index]
        escaped = char == "\\" and not escaped
        index += 1
    else:
        return None
    literal = source[:index]
    try:
        caption = python_ast.literal_eval(literal)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(caption, str):
        return None
    remainder = source[index:].strip()
    return caption, remainder


def _parse_choice_header(text: str) -> tuple[str, str | None] | None:
    without_colon = _remove_terminal_colon(text)
    if without_colon is None:
        return None
    parsed = _parse_string_literal_prefix(without_colon)
    if parsed is None:
        return None
    caption, remainder = parsed
    condition = None
    if remainder:
        keyword, tail = _head(remainder)
        if keyword != "if" or not tail:
            return None
        condition = tail
    return caption, condition


def _parse_menu_caption(text: str) -> str | None:
    if _remove_terminal_colon(text) is not None:
        return None
    keyword, tail = _head(text)
    candidate = tail if keyword else text
    parsed = _parse_string_literal_prefix(candidate)
    if parsed is None:
        return None
    caption, remainder = parsed
    return caption if not remainder else None


class RenpySubsetParser:
    """Inert parser for built-in control-flow statements; never executes script code."""

    def __init__(self, path: str, physical_lines: Iterable[str]) -> None:
        self.path = path
        self.lines = _logical_lines(path, physical_lines)
        self.diagnostics: list[dict[str, object]] = []
        self.labels: list[Label] = []

    def parse(self) -> ScriptModule:
        index = 0
        current_global = ""
        top_level: list[Statement] = []
        while index < len(self.lines):
            line = self.lines[index]
            keyword, _tail = _head(line.code)
            if keyword != "label":
                index = self._skip_statement(index)
                continue
            anchor, index, current_global = self._parse_label(index, current_global)
            top_level.append(anchor)
        return ScriptModule(self.path, self.labels, top_level, self.diagnostics)

    def _parse_suite(
        self, index: int, parent_indent: int, current_global: str
    ) -> tuple[list[Statement], int]:
        if index >= len(self.lines) or self.lines[index].indent <= parent_indent:
            return [], index
        indent = self.lines[index].indent
        statements: list[Statement] = []
        while index < len(self.lines):
            line = self.lines[index]
            if line.indent < indent or line.indent <= parent_indent:
                break
            if line.indent > indent:
                self._diagnose(
                    line, "unexpected_indent", "unexpected nested line treated as opaque"
                )
                index = self._skip_statement(index)
                continue
            keyword, _ = _head(line.code)
            statement: Statement
            if keyword == "label":
                statement, index, current_global = self._parse_label(index, current_global)
            else:
                statement, index = self._parse_statement(index, current_global)
            statements.append(statement)
        return statements, index

    def _parse_label(
        self, index: int, current_global: str
    ) -> tuple[LabelAnchor, int, str]:
        line = self.lines[index]
        _, tail = _head(line.code)
        header = _remove_terminal_colon(tail)
        if header is None:
            raise ScriptParseError(
                f"{self.path}:{line.start_line}: label is missing a terminal colon"
            )
        name, remainder = _static_name(header)
        if name is None or (remainder and not remainder.startswith("(")):
            raise ScriptParseError(
                f"{self.path}:{line.start_line}: label name is not statically supported"
            )
        resolved = _resolve_local(name, current_global)
        assert resolved is not None
        label_global = resolved if not name.startswith(".") else current_global
        body, next_index = self._parse_suite(index + 1, line.indent, label_global)
        label = Label(resolved, line.span, line.code.strip(), body)
        self.labels.append(label)
        anchor = LabelAnchor(line.span, line.code.strip(), resolved, body)
        return anchor, next_index, label_global

    def _parse_statement(self, index: int, current_global: str) -> tuple[Statement, int]:
        line = self.lines[index]
        keyword, tail = _head(line.code)

        if keyword == "jump":
            target, expression = self._parse_transfer(tail, current_global)
            return Jump(line.span, line.code.strip(), target, expression), index + 1
        if keyword == "call" and _head(tail)[0] == "screen":
            return Opaque(
                line.span, line.code.strip(), reason="interactive_screen_call"
            ), index + 1
        if keyword == "call":
            target, expression = self._parse_transfer(tail, current_global, is_call=True)
            return Call(line.span, line.code.strip(), target, expression), index + 1
        if keyword == "return":
            return Return(line.span, line.code.strip(), tail or None), index + 1
        if keyword == "if":
            return self._parse_if(index, current_global)
        if keyword == "menu":
            return self._parse_menu(index, current_global)

        block_header = _remove_terminal_colon(line.code) is not None
        if keyword in ("python", "$", "init"):
            next_index = self._skip_statement(index) if block_header else index + 1
            return Opaque(
                line.span, line.code.strip(), reason="embedded_python_not_executed"
            ), next_index
        if block_header:
            next_index = self._skip_statement(index)
            reason = (
                "unsupported_control_flow"
                if keyword in ("while", "for")
                else "creator_or_unsupported_block"
            )
            return Opaque(line.span, line.code.strip(), reason=reason), next_index

        known_kind = keyword if keyword in {
            "scene",
            "show",
            "hide",
            "play",
            "stop",
            "queue",
            "voice",
            "with",
            "pause",
            "pass",
            "window",
        } else "statement"
        return Simple(line.span, line.code.strip(), known_kind), index + 1

    def _parse_if(self, index: int, current_global: str) -> tuple[If, int]:
        first = self.lines[index]
        branches: list[IfBranch] = []
        cursor = index
        while cursor < len(self.lines):
            line = self.lines[cursor]
            if line.indent != first.indent:
                break
            keyword, tail = _head(line.code)
            if keyword not in ("if", "elif", "else"):
                break
            header = _remove_terminal_colon(tail)
            if header is None:
                self._diagnose(line, "malformed_if", "branch is missing a terminal colon")
                condition = tail or None
            elif keyword == "else":
                condition = None
            else:
                condition = header
            body, cursor = self._parse_suite(cursor + 1, line.indent, current_global)
            branches.append(IfBranch(condition, line.span, line.code.strip(), body))
            if keyword == "else":
                break
        return If(first.span, first.code.strip(), branches), cursor

    def _parse_menu(self, index: int, current_global: str) -> tuple[Statement, int]:
        line = self.lines[index]
        _, menu_tail = _head(line.code)
        menu_header = _remove_terminal_colon(menu_tail)
        menu_name: str | None = None
        availability_unresolved = menu_header is None
        if menu_header:
            static_name, remainder = _static_name(menu_header)
            if static_name is not None and not remainder:
                menu_name = _resolve_local(static_name, current_global)
            else:
                availability_unresolved = True
        cursor = index + 1
        choices: list[MenuChoice] = []
        captions: list[MenuCaption] = []
        if cursor >= len(self.lines) or self.lines[cursor].indent <= line.indent:
            self._diagnose(line, "empty_menu", "menu has no indented choices")
            menu = Menu(line.span, line.code.strip(), choices, captions, True)
            return self._anchor_named_menu(menu, menu_name), cursor
        choice_indent = self.lines[cursor].indent
        while cursor < len(self.lines):
            choice_line = self.lines[cursor]
            if choice_line.indent <= line.indent:
                break
            if choice_line.indent != choice_indent:
                availability_unresolved = True
                self._diagnose(
                    choice_line, "unexpected_menu_indent", "menu line treated as opaque"
                )
                cursor = self._skip_statement(cursor)
                continue
            keyword, tail = _head(choice_line.code)
            if keyword == "set" and tail:
                availability_unresolved = True
                cursor += 1
                continue
            header = _parse_choice_header(choice_line.code)
            if header is None:
                caption = _parse_menu_caption(choice_line.code)
                if caption is not None:
                    captions.append(
                        MenuCaption(caption, choice_line.span, choice_line.code.strip())
                    )
                    cursor += 1
                    continue
                availability_unresolved = True
                self._diagnose(
                    choice_line, "unsupported_menu_line", "menu caption is not a string choice"
                )
                cursor = self._skip_statement(cursor)
                continue
            caption, condition = header
            body, cursor = self._parse_suite(cursor + 1, choice_line.indent, current_global)
            choices.append(
                MenuChoice(
                    caption,
                    condition,
                    choice_line.span,
                    choice_line.code.strip(),
                    body,
                )
            )
        menu = Menu(
            line.span,
            line.code.strip(),
            choices,
            captions,
            availability_unresolved,
        )
        return self._anchor_named_menu(menu, menu_name), cursor

    def _anchor_named_menu(self, menu: Menu, name: str | None) -> Statement:
        if name is None:
            return menu
        body: list[Statement] = [menu]
        self.labels.append(Label(name, menu.span, menu.text, body))
        return LabelAnchor(menu.span, menu.text, name, body)

    def _parse_transfer(
        self, tail: str, current_global: str, *, is_call: bool = False
    ) -> tuple[str | None, str | None]:
        keyword, expression_tail = _head(tail)
        if keyword == "expression":
            return None, expression_tail or "<empty expression>"
        name, remainder = _static_name(tail)
        if name is None:
            return None, tail or "<missing target>"
        if is_call and remainder:
            from_keyword, _ = _head(remainder)
            if from_keyword != "from" and not remainder.startswith("("):
                return None, tail
        elif remainder:
            return None, tail
        return _resolve_local(name, current_global), None

    def _skip_statement(self, index: int) -> int:
        indent = self.lines[index].indent
        cursor = index + 1
        while cursor < len(self.lines) and self.lines[cursor].indent > indent:
            cursor += 1
        return cursor

    def _diagnose(self, line: _LogicalLine, code: str, message: str) -> None:
        self.diagnostics.append(
            {"code": code, "message": message, "source": line.span.to_dict()}
        )


def parse_script(path: str, physical_lines: Iterable[str]) -> ScriptModule:
    return RenpySubsetParser(path, physical_lines).parse()
