from __future__ import annotations

from pathlib import Path

import pytest

from m15_test_support import linear_authority
from renpy_story_mapper import storage
from renpy_story_mapper.m11_persistence import M11_PHASES, phase_input_hash
from renpy_story_mapper.m11_scene_model import AtomKind
from renpy_story_mapper.m11_scene_projection import (
    build_scene_assembly,
    build_scene_boundaries,
    build_scene_presentation,
    build_story_atoms,
)
from renpy_story_mapper.narrative_map import (
    AuthorityBinding,
    LeadingTechnicalCoverageCorrection,
    QualifiedSourceLocator,
    SourceLocator,
)
from renpy_story_mapper.narrative_map.coverage_corrections import (
    M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION,
    LeadingTechnicalCorrectionRepository,
    M15CorrectionPreconditionError,
    decode_leading_technical_correction_envelope,
    seed_leading_technical_correction_working_copy,
)
from renpy_story_mapper.project import PayloadRecord, Project, SourceFingerprint


def _add_source(project: Project) -> None:
    project.refresh_sources((SourceFingerprint.from_bytes("game/story.rpy", b"synthetic source"),))


def _authority(marker: str = "current") -> AuthorityBinding:
    return AuthorityBinding(
        source_generation=f"generation-{marker}",
        canonical_schema="m10-canonical-graph-v1",
        canonical_hash=f"canonical-{marker}",
        atom_schema="m11-scene-model-v1",
        atom_hash=f"atoms-{marker}",
    )


def _correction(marker: str = "current") -> LeadingTechnicalCoverageCorrection:
    return LeadingTechnicalCoverageCorrection(
        authority=_authority(marker),
        reason="User classified the exact leading setup as technical coverage.",
        qualified_locators=(
            QualifiedSourceLocator(
                "atom-0",
                "node-0",
                ("evidence-0",),
                SourceLocator("game/story.rpy", 1, 1, "source"),
            ),
            QualifiedSourceLocator(
                "atom-1",
                "node-1",
                ("evidence-1",),
                SourceLocator("game/story.rpy", 2, 2, "source"),
            ),
        ),
        ordered_atom_ids=("atom-0", "atom-1"),
    )


def test_correction_save_is_atomic_and_survives_exact_authority_reopen(tmp_path: Path) -> None:
    path = tmp_path / "correction.rsmproj"
    correction = _correction()
    with Project.create(path) as project:
        _add_source(project)
        repository = LeadingTechnicalCorrectionRepository(project)
        write = repository.save(correction, expected_correction_hash=None)
        assert not write.reused
        assert write.correction_id == correction.correction_id
        assert write.normalized_hash == correction.normalized_hash
        assert project.payload_keys(M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION) == (
            "authoritative",
        )

    with Project.open(path) as reopened:
        selected = LeadingTechnicalCorrectionRepository(reopened).load(_authority())
        assert selected == correction


def test_correction_compare_and_set_rejects_stale_replacement_without_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "precondition.rsmproj"
    first = _correction()
    replacement = LeadingTechnicalCoverageCorrection(
        authority=first.authority,
        reason="A replacement with a different exact prefix.",
        qualified_locators=(
            *first.qualified_locators,
            QualifiedSourceLocator(
                "atom-2",
                "node-2",
                ("evidence-2",),
                SourceLocator("game/story.rpy", 3, 3, "source"),
            ),
        ),
        ordered_atom_ids=("atom-0", "atom-1", "atom-2"),
    )
    with Project.create(path) as project:
        _add_source(project)
        repository = LeadingTechnicalCorrectionRepository(project)
        repository.save(first, expected_correction_hash=None)
        before = project.canonical_export()
        with pytest.raises(M15CorrectionPreconditionError, match="changed"):
            repository.save(replacement, expected_correction_hash="0" * 64)
        assert project.canonical_export() == before
        assert repository.load(first.authority) == first


def test_absent_or_stale_binding_keeps_the_correction_unselected(tmp_path: Path) -> None:
    path = tmp_path / "stale.rsmproj"
    with Project.create(path) as project:
        _add_source(project)
        repository = LeadingTechnicalCorrectionRepository(project)
        assert repository.load(_authority()) is None
        repository.save(_correction(), expected_correction_hash=None)
        assert repository.load(_authority("other")) is None


def test_corrupt_correction_envelope_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.rsmproj"
    correction = _correction()
    with Project.create(path) as project:
        _add_source(project)
        repository = LeadingTechnicalCorrectionRepository(project)
        repository.save(correction, expected_correction_hash=None)
        connection = project._require_open()
        corrupt = storage.canonical_json(
            {
                "schema": "m15-leading-technical-correction-envelope-v1",
                "correction_hash": "0" * 64,
                "correction": correction.to_dict(),
            }
        )
        connection.execute(
            "UPDATE payloads SET payload_json=?, payload_hash=? "
            "WHERE collection=? AND record_key=?",
            (
                corrupt,
                storage.payload_digest(corrupt),
                M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION,
                "authoritative",
            ),
        )
        with pytest.raises(storage.ProjectCorruptError, match="technical correction"):
            repository.load(correction.authority)


def test_correction_uses_only_the_new_m15_payload_collection() -> None:
    assert M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION in storage.PAYLOAD_COLLECTIONS
    assert M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION.startswith("m15_")


def test_source_refresh_invalidates_the_correction_dependency(tmp_path: Path) -> None:
    path = tmp_path / "invalidated.rsmproj"
    with Project.create(path) as project:
        _add_source(project)
        repository = LeadingTechnicalCorrectionRepository(project)
        repository.save(_correction(), expected_correction_hash=None)
        result = project.refresh_sources(
            (SourceFingerprint.from_bytes("game/story.rpy", b"changed source"),)
        )
        assert result.invalidated_payloads == 1
        assert repository.load(_authority()) is None


def test_working_copy_utility_is_atomic_and_preserves_source_project(tmp_path: Path) -> None:
    canonical, _model = linear_authority((AtomKind.NARRATION,) * 3)
    canonical_value = canonical.to_dict()
    source_path = tmp_path / "source.rsmproj"
    output_path = tmp_path / "working.rsmproj"
    with Project.create(source_path) as project:
        project.refresh_sources((SourceFingerprint.from_bytes("game/synthetic.rpy", b"synthetic"),))
        project.write_payloads(
            (PayloadRecord("m10_canonical_graph", "authoritative", canonical_value),)
        )
        story_atoms = build_story_atoms(canonical)
        boundaries = build_scene_boundaries(canonical, story_atoms)
        assembly = build_scene_assembly(canonical, story_atoms, boundaries)
        presentation = build_scene_presentation(canonical, assembly)
        results = dict(
            zip(
                M11_PHASES,
                (story_atoms, boundaries, assembly, presentation),
                strict=True,
            )
        )
        working_hash: str | None = None
        phase_hashes: dict[str, str] = {}
        for phase in M11_PHASES:
            checkpoint = project.m11_persistence().checkpoint_phase(
                canonical_value,
                phase,
                phase_input_hash({"phase": phase, "fixture": "m15-correction"}),
                results[phase],
                expected_working_hash=working_hash,
            )
            working_hash = checkpoint.working_hash
            phase_hashes[phase] = checkpoint.result_hash
        assert working_hash is not None
        project.m11_persistence().publish(
            canonical_value,
            expected_working_hash=working_hash,
            expected_phase_hashes=phase_hashes,
        )
    source_before = source_path.read_bytes()

    write = seed_leading_technical_correction_working_copy(
        source_path,
        output_path,
        (SourceLocator("game/synthetic.rpy", 1, 2, "physical_source"),),
    )

    assert source_path.read_bytes() == source_before
    assert output_path.is_file()
    with Project.open(output_path) as working:
        raw = working.payload(
            M15_LEADING_TECHNICAL_CORRECTIONS_COLLECTION,
            "authoritative",
        )
        correction = decode_leading_technical_correction_envelope(raw)
        selected = LeadingTechnicalCorrectionRepository(working).load(correction.authority)
        assert selected is not None
        assert selected.correction_id == write.correction_id
        assert len(selected.ordered_atom_ids) == 2
