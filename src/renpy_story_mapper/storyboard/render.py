"""Render a small, dependency-free AI-first storyboard document.

The renderer deliberately treats the supplied mappings as data.  AI-authored
titles, summaries, relationships, and uncertainty notes are displayed as
editorial content, while exact source lines can only come from evidence records
referenced by ID in the analysis mapping.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from html import escape

__all__ = ["render_storyboard", "render_storyboard_html"]


@dataclass(frozen=True)
class _Evidence:
    identifier: str
    source_text: str | None
    path: str | None
    start_line: int | None
    end_line: int | None
    start_column: int | None
    ordinal: int

    @property
    def order_key(self) -> tuple[int, str, int, int, int, int]:
        return (
            0 if self.path else 1,
            self.path.casefold() if self.path else "",
            0 if self.start_line is not None else 1,
            self.start_line or 0,
            self.start_column or 0,
            self.ordinal,
        )

    @property
    def location(self) -> str:
        if not self.path:
            return "source location unavailable"
        if self.start_line is None:
            return self.path
        if self.end_line is not None and self.end_line != self.start_line:
            return f"{self.path}:{self.start_line}-{self.end_line}"
        return f"{self.path}:{self.start_line}"


@dataclass
class _RenderState:
    evidence: dict[str, _Evidence]
    missing_evidence: list[str]
    _missing_seen: set[str]

    def missing(self, identifier: str) -> None:
        if identifier not in self._missing_seen:
            self._missing_seen.add(identifier)
            self.missing_evidence.append(identifier)


def render_storyboard_html(
    evidence: Mapping[str, object],
    profile: Mapping[str, object],
    analysis: Mapping[str, object],
    report: Mapping[str, object],
) -> str:
    """Return a directly openable HTML storyboard for four JSON-like mappings.

    ``evidence`` is expected to contain an ``evidence``/``records`` collection
    whose records have an ID, exact ``source_text``, and source location.  A
    scene uses ``line_evidence_ids`` (with a few equivalent aliases) to select
    exact lines.  ``profile``, ``analysis``, and ``report`` may be any
    ``Mapping`` implementation; missing optional fields render as visible
    uncertainty rather than causing a fabricated story fact.
    """

    evidence_records = _build_evidence_index(evidence)
    state = _RenderState(evidence_records, [], set())
    title = _story_title(profile, analysis)
    scenes = _records(analysis, ("scenes", "sections"))
    summary = _first_text(analysis, "summary", "overview", "description")

    content: list[str] = [
        '<header class="story-header">',
        '<p class="eyebrow">Storyboard</p>',
        f"<h1>{_escape(title)}</h1>",
    ]
    if summary:
        content.append(f'<p class="story-summary">{_escape(summary)}</p>')
    content.append("</header>")

    profile_notes = _notes_from(
        profile, ("unresolved", "unresolved_items", "uncertainty"), "Profile"
    )
    if profile_notes:
        content.append(_render_notes("Profile uncertainty", profile_notes, state))

    if scenes:
        content.append('<section class="scenes" aria-label="Scenes">')
        for scene_index, scene in enumerate(scenes):
            content.append(_render_scene(scene, scene_index, state))
        content.append("</section>")
    else:
        content.append('<p class="uncertainty">No AI scenes were supplied.</p>')

    top_level_lines = _evidence_ids(
        analysis,
        ("line_evidence_ids", "exact_line_evidence_ids", "source_evidence_ids"),
    )
    if top_level_lines:
        content.append(_render_exact_lines("Source lines", top_level_lines, state))

    top_level_menus = _records(analysis, ("menus", "menu_points", "choice_points"))
    if top_level_menus:
        content.append('<section class="menus" aria-label="Choices">')
        content.append("<h2>Choices</h2>")
        for menu_index, menu in enumerate(_ordered_records(top_level_menus, state.evidence)):
            content.append(_render_menu(menu, menu_index, state))
        content.append("</section>")

    analysis_notes = _notes_from(
        analysis,
        ("unresolved", "unresolved_items", "uncertainty", "uncertainties"),
        "Analysis",
    )
    if analysis_notes:
        content.append(_render_notes("Unresolved behavior", analysis_notes, state))

    analysis_disagreements = _notes_from(
        analysis,
        ("disagreements", "conflicts", "parser_ai_disagreements"),
        "Analysis",
    )
    if analysis_disagreements:
        content.append(_render_notes("Parser/AI disagreements", analysis_disagreements, state))

    report_notes = _notes_from(
        report,
        ("errors", "issues", "warnings", "unresolved", "unresolved_items"),
        "Validation",
    )
    report_disagreements = _notes_from(
        report,
        ("disagreements", "conflicts", "parser_ai_disagreements"),
        "Validation",
    )
    report_status = _first_text(report, "status", "result", "decision")
    if report_status or report_notes:
        validation_title = "Validation"
        if report_status:
            validation_title = f"Validation: {report_status}"
        content.append(_render_notes(validation_title, report_notes, state))
    if report_disagreements:
        content.append(_render_notes("Validation disagreements", report_disagreements, state))

    if state.missing_evidence:
        missing_notes = tuple(
            {"message": f"Missing evidence reference: {identifier}", "kind": "unresolved"}
            for identifier in state.missing_evidence
        )
        content.append(_render_notes("Unresolved evidence", missing_notes, state))

    body = "\n".join(content)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_escape(title)}</title>
<style>
:root {{
  color-scheme: light;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  color: #20242a;
  background: #f5f6f8;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #f5f6f8; line-height: 1.5; }}
main {{ max-width: 980px; margin: 0 auto; padding: 3rem 2rem 5rem; }}
.story-header {{ margin-bottom: 2.5rem; }}
.eyebrow {{
  margin: 0 0 .35rem;
  color: #5b6470;
  font-size: .78rem;
  font-weight: 700;
  letter-spacing: .12em;
  text-transform: uppercase;
}}
h1, h2, h3 {{ line-height: 1.2; margin: 0; }}
h1 {{ font-size: 2.35rem; }}
h2 {{ font-size: 1.45rem; margin-bottom: .9rem; }}
h3 {{ font-size: 1.05rem; }}
.story-summary, .summary {{ color: #4b5563; max-width: 70ch; }}
.scene {{ border-top: 1px solid #d8dce2; padding: 2rem 0; }}
.scene:first-child {{ border-top: 0; padding-top: 0; }}
.confidence, .source-id, .source-location, .note-kind {{ color: #5b6470; font-size: .82rem; }}
.confidence {{ margin-left: .5rem; }}
.exact-lines, .arms, .notes {{ list-style: none; margin: .8rem 0 0; padding: 0; }}
.exact-line, .arm, .note {{
  background: #fff;
  border: 1px solid #e0e3e8;
  border-radius: .55rem;
  margin: .55rem 0;
  padding: .75rem .9rem;
}}
.exact-line-text {{ display: block; white-space: pre-wrap; }}
.source-line {{ display: block; margin-top: .3rem; }}
.menu, .branch {{ border-left: 3px solid #b8c4d6; margin: 1.25rem 0; padding: .1rem 0 .1rem 1rem; }}
.menu-title, .branch-title {{ margin-bottom: .45rem; }}
.arm-caption {{ font-weight: 700; }}
.detail {{ margin: .3rem 0 0; }}
.detail-label {{ color: #5b6470; font-size: .82rem; font-weight: 700; margin-right: .35rem; }}
.uncertainty {{
  background: #fff8df;
  border-left: 3px solid #c18a00;
  color: #644d00;
  margin: .7rem 0;
  padding: .6rem .8rem;
}}
.notes-section {{ margin-top: 1.5rem; }}
.note-kind {{ font-weight: 700; margin-right: .35rem; text-transform: capitalize; }}
.evidence-ref {{ display: block; margin-top: .35rem; }}
.evidence-text {{ color: #4b5563; display: block; margin-top: .25rem; white-space: pre-wrap; }}
.terminal {{ color: #6b2c4c; font-weight: 700; }}
</style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""


def render_storyboard(
    evidence: Mapping[str, object],
    profile: Mapping[str, object],
    analysis: Mapping[str, object],
    report: Mapping[str, object],
) -> str:
    """Compatibility name for :func:`render_storyboard_html`."""

    return render_storyboard_html(evidence, profile, analysis, report)


def _build_evidence_index(data: Mapping[str, object]) -> dict[str, _Evidence]:
    nested = data.get("evidence_index")
    source = nested if isinstance(nested, Mapping) else data
    raw_records = _raw_collection(source, ("evidence", "records", "items", "entries"))
    result: dict[str, _Evidence] = {}
    for ordinal, raw in enumerate(raw_records):
        if not isinstance(raw, Mapping):
            continue
        identifier = _first_text(raw, "id", "evidence_id", "evidenceId")
        if not identifier or identifier in result:
            continue
        source_text = _first_text(raw, "source_text", "exact_text", "sourceText", "text")
        location = _location_mapping(raw)
        path = _first_text(location, "path", "relative_path", "source_path", "file")
        start_line = _line_value(location, ("start_line", "line"))
        end_line = _line_value(location, ("end_line",))
        start = location.get("start")
        if isinstance(start, Mapping):
            start_line = start_line or _line_value(start, ("line", "start_line"))
        end = location.get("end")
        if isinstance(end, Mapping):
            end_line = end_line or _line_value(end, ("line", "end_line"))
        if end_line is None:
            end_line = start_line
        start_column = _line_value(location, ("start_column", "column"))
        if isinstance(start, Mapping):
            start_column = start_column or _integer(start.get("column"))
        result[identifier] = _Evidence(
            identifier,
            source_text,
            path,
            start_line,
            end_line,
            start_column,
            ordinal,
        )
    return result


def _location_mapping(record: Mapping[str, object]) -> Mapping[str, object]:
    for key in ("source", "provenance", "location"):
        value = record.get(key)
        if isinstance(value, Mapping):
            combined = {
                item_key: item_value
                for item_key, item_value in record.items()
                if item_key not in {"source", "provenance", "location"}
            }
            combined.update(value)
            return combined
    return record


def _render_scene(scene: Mapping[str, object], scene_index: int, state: _RenderState) -> str:
    title = _first_text(scene, "title", "name", "label") or f"Scene {scene_index + 1}"
    summary = _first_text(scene, "summary", "description", "overview")
    confidence = _first_text(scene, "confidence", "certainty")
    lines = _evidence_ids(
        scene,
        (
            "line_evidence_ids",
            "exact_line_evidence_ids",
            "source_evidence_ids",
        ),
    )
    evidence_ids = _evidence_ids(scene, ("evidence_ids",))
    parts = [f'<article class="scene" id="scene-{scene_index}">', f"<h2>{_escape(title)}"]
    if confidence:
        parts[-1] += f' <span class="confidence">{_escape(confidence)}</span>'
    parts[-1] += "</h2>"
    if summary:
        parts.append(f'<p class="summary">{_escape(summary)}</p>')
    if lines:
        parts.append(_render_exact_lines("Exact lines", lines, state))
    else:
        parts.append('<p class="uncertainty">No cited exact-line evidence.</p>')
    if evidence_ids:
        parts.append(_render_evidence_citations("Scene evidence", evidence_ids, state))

    branches = _records(scene, ("branches", "outcomes", "routes"))
    if branches:
        parts.append('<section class="branches" aria-label="Branch consequences">')
        parts.append("<h3>Branch consequences</h3>")
        for branch_index, branch in enumerate(_ordered_records(branches, state.evidence)):
            parts.append(_render_branch(branch, branch_index, state))
        parts.append("</section>")

    menus = _records(scene, ("menus", "menu_points", "choice_points"))
    if menus:
        parts.append('<section class="menus" aria-label="Choices">')
        for menu_index, menu in enumerate(_ordered_records(menus, state.evidence)):
            parts.append(_render_menu(menu, menu_index, state))
        parts.append("</section>")

    scene_notes = _notes_from(
        scene,
        ("unresolved", "unresolved_items", "uncertainty", "disagreements", "conflicts"),
        "Scene",
    )
    if scene_notes:
        parts.append(_render_notes("Uncertainty", scene_notes, state, heading_level=3))
    parts.append("</article>")
    return "\n".join(parts)


def _render_exact_lines(heading: str, identifiers: Sequence[str], state: _RenderState) -> str:
    lines = [
        '<section class="exact-source">',
        f"<h3>{_escape(heading)}</h3>",
        '<ol class="exact-lines">',
    ]
    ordered = _ordered_identifiers(identifiers, state.evidence)
    for identifier in ordered:
        evidence = state.evidence.get(identifier)
        if evidence is None:
            state.missing(identifier)
            lines.append(
                f'<li class="exact-line uncertainty"><span class="exact-line-text">'
                f"Evidence {_escape(identifier)} is unavailable.</span></li>"
            )
            continue
        if evidence.source_text is None:
            lines.append(
                f'<li class="exact-line uncertainty"><span class="exact-line-text">'
                f"Exact source text is unavailable for evidence {_escape(identifier)}.</span>"
                f"{_render_source_label(evidence)}</li>"
            )
            continue
        lines.append(
            f'<li class="exact-line"><span class="exact-line-text">'
            f"{_escape(evidence.source_text)}</span>{_render_source_label(evidence)}</li>"
        )
    lines.append("</ol>")
    lines.append("</section>")
    return "\n".join(lines)


def _render_menu(menu: Mapping[str, object], menu_index: int, state: _RenderState) -> str:
    title = _first_text(menu, "title", "name", "label") or "Choice"
    parts = [
        f'<section class="menu" id="menu-{menu_index}">',
        f'<h3 class="menu-title">{_escape(title)}</h3>',
    ]
    menu_ids = _evidence_ids(menu, ("evidence_id", "source_evidence_id", "evidence_ids"))
    for identifier in _ordered_identifiers(menu_ids, state.evidence):
        parts.append(_render_evidence_ref(identifier, state, show_text=True))
    arms = _records(menu, ("arms", "choice_arms", "options"))
    if not arms:
        parts.append('<p class="uncertainty">No choice arms supplied.</p>')
    else:
        parts.append('<ol class="arms">')
        for arm_index, arm in enumerate(_ordered_records(arms, state.evidence)):
            parts.append(_render_arm(arm, arm_index, state))
        parts.append("</ol>")
    parts.append("</section>")
    return "\n".join(parts)


def _render_arm(arm: Mapping[str, object], arm_index: int, state: _RenderState) -> str:
    caption = _first_text(arm, "caption", "title", "label", "text") or f"Choice arm {arm_index + 1}"
    parts = [f'<li class="arm"><span class="arm-caption">{_escape(caption)}</span>']
    parts.extend(_render_relationships(arm))
    identifiers = _evidence_ids(arm, ("evidence_id", "source_evidence_id", "evidence_ids"))
    for identifier in _ordered_identifiers(identifiers, state.evidence):
        parts.append(_render_evidence_ref(identifier, state, show_text=True))
    uncertainty = _first_text(arm, "uncertainty", "unresolved", "reason")
    if uncertainty:
        parts.append(f'<div class="uncertainty">{_escape(uncertainty)}</div>')
    parts.append("</li>")
    return "\n".join(parts)


def _render_branch(branch: Mapping[str, object], branch_index: int, state: _RenderState) -> str:
    title = _first_text(branch, "title", "name", "label") or f"Branch {branch_index + 1}"
    parts = [f'<article class="branch"><h3 class="branch-title">{_escape(title)}</h3>']
    parts.extend(_render_relationships(branch))
    identifiers = _evidence_ids(branch, ("evidence_id", "source_evidence_id", "evidence_ids"))
    for identifier in _ordered_identifiers(identifiers, state.evidence):
        parts.append(_render_evidence_ref(identifier, state, show_text=True))
    parts.append("</article>")
    return "\n".join(parts)


def _render_relationships(record: Mapping[str, object]) -> list[str]:
    result: list[str] = []
    fields = (
        ("Condition", ("condition", "conditions")),
        ("Consequence", ("consequence", "consequences", "effect", "effects", "outcome")),
        ("Destination", ("destination", "destinations", "target", "targets", "leads_to")),
        ("Rejoin", ("rejoin", "rejoins", "join", "rejoin_target")),
    )
    for label, keys in fields:
        value = _first_value(record, *keys)
        if _empty(value):
            continue
        result.append(
            f'<div class="detail"><span class="detail-label">{label}:</span>'
            f"{_escape(_describe(value))}</div>"
        )

    terminal = _first_value(record, "terminal", "terminals", "ending")
    if _empty(terminal):
        outcome_kind = _first_text(record, "outcome_kind", "result_kind")
        if outcome_kind and outcome_kind.casefold() in {"terminal", "ends", "ending"}:
            terminal = outcome_kind
    if not _empty(terminal):
        value = "Terminal" if terminal is True else _describe(terminal)
        result.append(
            f'<div class="detail terminal"><span class="detail-label">Terminal:</span>'
            f"{_escape(value)}</div>"
        )
    return result


def _render_source_label(evidence: _Evidence) -> str:
    return (
        f'<span class="source-line"><span class="source-id">Evidence '
        f"{_escape(evidence.identifier)}</span> &middot; "
        f'<span class="source-location">{_escape(evidence.location)}</span></span>'
    )


def _render_evidence_ref(identifier: str, state: _RenderState, *, show_text: bool) -> str:
    evidence = state.evidence.get(identifier)
    if evidence is None:
        state.missing(identifier)
        return (
            f'<span class="evidence-ref uncertainty">Evidence '
            f"{_escape(identifier)} is unavailable.</span>"
        )
    text = ""
    if show_text and evidence.source_text is not None:
        text = f'<span class="evidence-text">{_escape(evidence.source_text)}</span>'
    return f'<span class="evidence-ref">{_render_source_label(evidence)}{text}</span>'


def _render_evidence_citations(
    title: str, identifiers: Sequence[str], state: _RenderState
) -> str:
    refs = "".join(
        _render_evidence_ref(identifier, state, show_text=False)
        for identifier in _ordered_identifiers(identifiers, state.evidence)
    )
    return (
        f'<section class="scene-evidence" aria-label="{_escape(title)}">'
        f"<h3>{_escape(title)}</h3>{refs}</section>"
    )


def _render_notes(
    title: str,
    notes: Sequence[Mapping[str, object]],
    state: _RenderState,
    *,
    heading_level: int = 2,
) -> str:
    if heading_level not in {2, 3}:
        raise ValueError("heading_level must be 2 or 3")
    parts = [
        f'<section class="notes-section" aria-label="{_escape(title)}">',
        f"<h{heading_level}>{_escape(title)}</h{heading_level}>",
        '<ul class="notes">',
    ]
    for note in notes:
        message = _note_message(note)
        kind = _first_text(note, "code", "severity", "kind", "source")
        kind_html = f'<span class="note-kind">{_escape(kind)}:</span> ' if kind else ""
        evidence_html = "".join(
            _render_evidence_ref(identifier, state, show_text=False)
            for identifier in _ordered_identifiers(
                _evidence_ids(note, ("evidence_ids", "source_evidence_ids")), state.evidence
            )
        )
        source_html = _render_note_source(note)
        parts.append(
            f'<li class="note">{kind_html}{_escape(message)}{source_html}{evidence_html}</li>'
        )
    parts.append("</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def _render_note_source(note: Mapping[str, object]) -> str:
    source = note.get("source")
    if not isinstance(source, Mapping):
        return ""
    location = _location_mapping(note)
    path = _first_text(location, "path", "relative_path", "source_path", "file")
    if path is None:
        return ""
    start_line = _line_value(location, ("start_line", "line"))
    start = location.get("start")
    if isinstance(start, Mapping):
        start_line = start_line or _line_value(start, ("line", "start_line"))
    label = path if start_line is None else f"{path}:{start_line}"
    return f'<span class="source-line"><span class="source-location">{_escape(label)}</span></span>'


def _notes_from(
    mapping: Mapping[str, object], keys: Sequence[str], source: str
) -> tuple[Mapping[str, object], ...]:
    result: list[Mapping[str, object]] = []
    for key in keys:
        raw = mapping.get(key)
        for item in _note_items(raw):
            value = dict(item) if isinstance(item, Mapping) else {"message": _text(item)}
            value.setdefault("source", source)
            result.append(value)
    return tuple(result)


def _note_items(value: object) -> tuple[object, ...]:
    if value is None or value is False or value == "":
        return ()
    if isinstance(value, Mapping):
        if any(
            key in value
            for key in ("message", "description", "reason", "detail", "text", "parser", "ai")
        ):
            return (value,)
        nested = _first_value(value, "items", "records", "notes")
        if nested is not None:
            return _note_items(nested)
        return (value,)
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        result: list[object] = []
        for item in value:
            result.extend(_note_items(item))
        return tuple(result)
    return (value,)


def _note_message(note: Mapping[str, object]) -> str:
    message = _first_text(note, "message", "description", "reason", "detail", "text")
    if message:
        return message
    parser = _describe(note.get("parser"))
    ai = _describe(note.get("ai"))
    if parser or ai:
        parts = []
        if parser:
            parts.append(f"Parser: {parser}")
        if ai:
            parts.append(f"AI: {ai}")
        return "; ".join(parts)
    return _describe(note)


def _story_title(profile: Mapping[str, object], analysis: Mapping[str, object]) -> str:
    for mapping in (profile, analysis):
        value = _first_text(mapping, "title", "game_name", "name")
        if value:
            return value
        game = mapping.get("game")
        if isinstance(game, Mapping):
            value = _first_text(game, "title", "name")
            if value:
                return value
    return "Storyboard"


def _records(
    mapping: Mapping[str, object], keys: Sequence[str]
) -> tuple[Mapping[str, object], ...]:
    raw = _raw_collection(mapping, keys)
    result: list[Mapping[str, object]] = []
    for item in raw:
        if isinstance(item, Mapping):
            result.append(item)
    return tuple(result)


def _raw_collection(mapping: Mapping[str, object], keys: Sequence[str]) -> tuple[object, ...]:
    for key in keys:
        raw = mapping.get(key)
        if raw is None:
            continue
        if isinstance(raw, Mapping):
            result: list[object] = []
            for identifier, item in raw.items():
                if isinstance(item, Mapping):
                    record = dict(item)
                    record.setdefault("id", identifier)
                    result.append(record)
                else:
                    result.append({"id": identifier, "value": item})
            return tuple(result)
        if isinstance(raw, str):
            return (raw,)
        if isinstance(raw, Iterable) and not isinstance(raw, (bytes, bytearray)):
            return tuple(raw)
    return ()


def _ordered_records(
    records: Sequence[Mapping[str, object]], evidence: Mapping[str, _Evidence]
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        record
        for _key, record in sorted(
            enumerate(records), key=lambda item: _record_order(item[1], item[0], evidence)
        )
    )


def _record_order(
    record: Mapping[str, object], ordinal: int, evidence: Mapping[str, _Evidence]
) -> tuple[int, str, int, int, int, int, int]:
    references = _evidence_ids(record, ("evidence_id", "source_evidence_id", "evidence_ids"))
    locations = [evidence[item].order_key for item in references if item in evidence]
    if locations:
        location = min(locations)
        return (0, location[1], location[2], location[3], location[4], location[5], ordinal)
    explicit = _integer(_first_value(record, "source_order", "ordinal", "order"))
    return (1, "", 1, 0, 0, explicit if explicit is not None else ordinal, ordinal)


def _ordered_identifiers(
    identifiers: Sequence[str], evidence: Mapping[str, _Evidence]
) -> tuple[str, ...]:
    return tuple(
        identifier
        for _key, identifier in sorted(
            enumerate(identifiers),
            key=lambda item: (
                (
                    0,
                    *evidence[item[1]].order_key,
                    item[0],
                )
                if item[1] in evidence
                else (1, "", 1, 0, 0, item[0], item[0])
            ),
        )
    )


def _evidence_ids(mapping: Mapping[str, object], keys: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    for key in keys:
        raw = mapping.get(key)
        if raw is None:
            continue
        for identifier in _identifiers(raw):
            if identifier not in result:
                result.append(identifier)
    return tuple(result)


def _identifiers(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Mapping):
        identifier = _first_text(value, "evidence_id", "source_evidence_id", "id", "reference_id")
        if identifier:
            return (identifier,)
        nested = _first_value(value, "evidence_ids", "source_evidence_ids", "items")
        return _identifiers(nested) if nested is not None else ()
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        result: list[str] = []
        for item in value:
            for identifier in _identifiers(item):
                if identifier not in result:
                    result.append(identifier)
        return tuple(result)
    return ()


def _first_value(mapping: Mapping[str, object], *keys: str) -> object | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _first_text(mapping: Mapping[str, object], *keys: str) -> str:
    value = _first_value(mapping, *keys)
    return _text(value)


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _escape(value: object) -> str:
    return escape(_text(value), quote=True)


def _integer(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _line_value(mapping: Mapping[str, object], keys: Sequence[str]) -> int | None:
    for key in keys:
        line = _integer(mapping.get(key))
        if line is not None:
            return line
    return None


def _describe(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, Mapping):
        preferred = _first_text(value, "text", "description", "label", "name", "target", "kind")
        if preferred:
            return preferred
        parts = [
            f"{key}: {_describe(value[key])}"
            for key in sorted(value, key=str)
            if _describe(value[key])
        ]
        return "; ".join(parts)
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        return "; ".join(_describe(item) for item in value if _describe(item))
    return str(value)


def _empty(value: object) -> bool:
    if value is None or value is False or value == "":
        return True
    if isinstance(value, (Mapping, Sequence)) and not isinstance(value, (str, bytes, bytearray)):
        return len(value) == 0
    return False
