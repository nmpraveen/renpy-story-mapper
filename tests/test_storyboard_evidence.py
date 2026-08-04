from __future__ import annotations

from pathlib import Path

from renpy_story_mapper.storyboard import (
    EvidenceKind,
    build_evidence_index,
    build_evidence_index_from_text,
)

SOURCE = """label entry_point:
    "Opening line."
    if gate_value > 1:
        $ weird_flag = True
        "Chosen line."
    menu:
        "First option":
            call helper
        "Second option" if gate_value > 0:
            jump ending
    return

label helper:
    python:
        custom_value = "not executed"
    $ renpy.notify("custom")
    custom_statement whatever
    return

label ending:
    return
"""


def _records(index, kind: EvidenceKind):
    return index.records_of(kind)


def test_selected_section_preserves_source_facts_and_stable_ids() -> None:
    first = build_evidence_index_from_text(SOURCE, label="entry_point")
    second = build_evidence_index_from_text(SOURCE, label="entry_point")

    assert first.to_dict() == second.to_dict()
    assert first.source is not None
    assert first.source.path == "game/source.rpy"
    assert first.source.provenance.line_basis == "physical_original_source"
    assert [record.metadata["name"] for record in first.labels] == ["entry_point"]
    assert len(first.menus) == 1
    assert len(first.choice_arms) == 2
    assert {record.metadata["caption"] for record in first.choice_arms} == {
        "First option",
        "Second option",
    }
    assert {record.metadata["condition"] for record in first.conditions} == {
        "gate_value > 1",
        "gate_value > 0",
    }
    assert len(first.assignments) == 1
    assert first.assignments[0].metadata["target"] == "weird_flag"
    assert len(_records(first, EvidenceKind.CALL)) == 1
    assert len(_records(first, EvidenceKind.JUMP)) == 1
    assert len(_records(first, EvidenceKind.RETURN)) == 1
    assert any(record.kind is EvidenceKind.NARRATION for record in first.records)
    assert all(record.id.startswith("ev_") for record in first.records)
    assert all(record.source.span.path == "game/source.rpy" for record in first.records)
    assert any(record.text == '    "Opening line."\n' for record in first.records)


def test_python_custom_and_unknown_constructs_are_retained_without_execution() -> None:
    index = build_evidence_index_from_text(SOURCE, label="helper")

    python_blocks = _records(index, EvidenceKind.PYTHON)
    custom = _records(index, EvidenceKind.CUSTOM)
    unknown = _records(index, EvidenceKind.UNKNOWN)

    assert len(python_blocks) == 1
    assert 'custom_value = "not executed"' in python_blocks[0].text
    assert python_blocks[0].metadata["opaque_reason"] == "embedded_python_not_executed"
    assert any('renpy.notify("custom")' in record.text for record in custom)
    assert any("custom_statement whatever" in record.text for record in unknown)
    assert all(record.metadata.get("syntax_kind") for record in unknown)


def test_source_label_and_line_selection_failures_are_diagnostics() -> None:
    missing_label = build_evidence_index_from_text(SOURCE, label="not_present")
    assert missing_label.records == ()
    assert {diagnostic.code for diagnostic in missing_label.diagnostics} == {"label_not_found"}

    selected = build_evidence_index_from_text(
        SOURCE,
        label="entry_point",
        start_line=7,
        end_line=5,
    )
    assert selected.records == ()
    assert any(diagnostic.code == "invalid_line_span" for diagnostic in selected.diagnostics)

    out_of_bounds = build_evidence_index_from_text(
        SOURCE,
        label="entry_point",
        start_line=999,
    )
    assert out_of_bounds.records == ()
    assert any(
        diagnostic.code == "line_span_out_of_bounds" for diagnostic in out_of_bounds.diagnostics
    )

    missing_source = build_evidence_index_from_text(
        SOURCE,
        path="game/chosen.rpy",
        source_path="game/missing.rpy",
    )
    assert missing_source.records == ()
    assert any(diagnostic.code == "source_not_found" for diagnostic in missing_source.diagnostics)


def test_filesystem_ingestion_can_select_one_source_by_logical_path(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    (game / "other.rpy").write_text("label other:\n    return\n", encoding="utf-8")
    selected = game / "chosen.rpy"
    selected.write_text(SOURCE, encoding="utf-8")

    index = build_evidence_index(game, source_path="chosen.rpy", label="entry_point")

    assert index.source is not None
    assert index.source.path == "game/chosen.rpy"
    assert [record.metadata["name"] for record in index.labels] == ["entry_point"]


def test_stable_ids_use_case_insensitive_logical_paths_consistently() -> None:
    mixed_case = build_evidence_index_from_text(SOURCE, path="game/Scene.rpy")
    folded_case = build_evidence_index_from_text(SOURCE, path="GAME/scene.rpy")

    assert [record.id for record in mixed_case.records] == [
        record.id for record in folded_case.records
    ]
