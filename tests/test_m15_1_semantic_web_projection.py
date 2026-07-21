from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from renpy_story_mapper.narrative.contracts import ProviderIdentity
from renpy_story_mapper.narrative.provider import ProviderUsage
from renpy_story_mapper.narrative_map import (
    BoundaryWindow,
    NarrativeMapRepository,
    NarrativeMapService,
)
from renpy_story_mapper.narrative_map.contracts import canonical_hash
from renpy_story_mapper.narrative_map.provider import (
    NarrativeMapProviderRequest,
    NarrativeMapProviderResponse,
    ProviderProfile,
)
from renpy_story_mapper.project import Project, create_ingested_project
from renpy_story_mapper.web.m15_semantic_api import (
    freeze_boundary_membership,
    load_m15_semantic_inputs,
    m15_provider_profile,
    prepare_boundaries,
    prepare_summaries,
)
from renpy_story_mapper.web.narrative_map_api import (
    narrative_map_detail,
    narrative_map_page,
)

FIXTURE = Path(__file__).parent / "fixtures" / "linear.rpy"


@dataclass
class _FakeSemanticProvider:
    profile: ProviderProfile
    requests: list[NarrativeMapProviderRequest]
    valid_responses: int | None = None

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        _cancelled: Callable[[], bool],
    ) -> NarrativeMapProviderResponse:
        self.requests.append(request)
        if self.valid_responses is not None and len(self.requests) > self.valid_responses:
            payload: dict[str, object] = {"invalid": True}
        elif request.job.kind.value == "semantic_boundary_window":
            window = request.job.subject
            assert isinstance(window, BoundaryWindow)
            payload = {
                "window_id": request.job.subject_id,
                "decisions": [
                    {
                        "candidate_id": candidate_id,
                        "decision": "new_beat_same_cluster",
                        "reason": "The next supported story turn begins.",
                        "confidence": 0.95,
                        "warnings": [],
                    }
                    for candidate_id in window.owned_candidate_ids
                ],
            }
        else:
            subject_kind = type(request.job.subject).__name__
            subject_kind = {
                "SemanticBeat": "beat",
                "MajorCluster": "major_cluster",
                "ChoiceComposition": "choice",
            }[subject_kind]
            payload = {
                "subject_kind": subject_kind,
                "subject_id": request.job.subject_id,
                "membership_hash": request.job.membership_hash,
                "title": "A New Story Movement",
                "summary": "The evidence-linked story action develops and reaches its next turn.",
                "characters": list(request.job.known_characters),
                "claims": [
                    {
                        "claim_class": "factual",
                        "text": "This story item is supported by exact local evidence.",
                        "evidence_ids": [request.job.known_evidence_ids[0]],
                    }
                ],
                "warnings": [],
            }
        return NarrativeMapProviderResponse(
            request.request_id,
            ProviderIdentity(
                self.profile.provider,
                self.profile.adapter,
                self.profile.adapter_version,
                self.profile.requested_model,
                self.profile.requested_model,
                self.profile.settings,
            ),
            payload,
            ProviderUsage(10, 5, 1),
        )

    def cancel(self) -> None:
        return None


def _profile() -> ProviderProfile:
    return m15_provider_profile()


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return cast(Mapping[str, object], value)


def _mappings(value: object) -> tuple[Mapping[str, object], ...]:
    assert isinstance(value, list)
    return tuple(_mapping(item) for item in value)


def _project(tmp_path: Path) -> Path:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_bytes(FIXTURE.read_bytes())
    project_path = tmp_path / "story.rsmproj"
    create_ingested_project(project_path, source).close()
    return project_path


def _multi_window_project(tmp_path: Path) -> Path:
    source = tmp_path / "game"
    source.mkdir()
    (source / "story.rpy").write_text(
        "label start:\n"
        + "".join(f'    "Public synthetic turn {index}."\n' for index in range(12))
        + "    return\n",
        encoding="utf-8",
        newline="\n",
    )
    project_path = tmp_path / "multi-window.rsmproj"
    create_ingested_project(project_path, source).close()
    return project_path


def _publish(project_path: Path) -> tuple[str, str]:
    profile = _profile()
    with Project.open(project_path) as project:
        inputs = load_m15_semantic_inputs(project)
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        boundaries = prepare_boundaries(
            service,
            inputs,
            run_id="web-boundaries",
            replay_existing=False,
        )
        boundary_provider = _FakeSemanticProvider(profile, [])
        boundary_report = service.start_boundaries(
            boundaries,
            provider=boundary_provider,
            consent=boundaries.granted_consent(),
        )
        assert boundary_report.failed_job_ids == ()
        frozen = freeze_boundary_membership(service, inputs, boundaries)
        assert frozen.record.state.value == "membership_frozen"
        summaries = prepare_summaries(
            service,
            inputs,
            run_id="web-summaries",
            replay_existing=False,
        )
        summary_provider = _FakeSemanticProvider(profile, [])
        summary_report = service.start_summaries(
            summaries,
            provider=summary_provider,
            consent=summaries.granted_consent(),
        )
        assert summary_report.failed_job_ids == (), repository.read_semantic_build()
        current = service.read_current_semantic_publication()
        assert current is not None
        outline = current["outline"]
        assert isinstance(outline, dict)
        clusters = outline["clusters"]
        assert isinstance(clusters, list) and clusters
        first_cluster = clusters[0]
        assert isinstance(first_cluster, dict)
        return str(current["publication_hash"]), str(first_cluster["cluster_id"])


def _publish_with_resumed_producer_lineage(project_path: Path) -> tuple[str, str, str, str]:
    profile = _profile()
    with Project.open(project_path) as project:
        inputs = load_m15_semantic_inputs(project)
        assert len(inputs.windows) > 1
        repository = NarrativeMapRepository(project)
        service = NarrativeMapService(repository)
        first_boundaries = prepare_boundaries(
            service,
            inputs,
            run_id="public-boundaries-first",
            replay_existing=False,
        )
        service.confirm_semantic_consent(
            first_boundaries,
            first_boundaries.granted_consent(),
        )
        first_boundary_report = service.start_boundaries(
            first_boundaries,
            provider=_FakeSemanticProvider(profile, [], valid_responses=1),
            consent=first_boundaries.granted_consent(),
        )
        assert first_boundary_report.validated_job_ids == (first_boundaries.jobs[0].job_id,)
        resumed_boundaries = prepare_boundaries(
            service,
            inputs,
            run_id="public-boundaries-resumed",
            replay_existing=True,
        )
        assert resumed_boundaries.consent.manifest_id != first_boundaries.consent.manifest_id
        service.confirm_semantic_consent(
            resumed_boundaries,
            resumed_boundaries.granted_consent(),
        )
        resumed_boundary_report = service.start_boundaries(
            resumed_boundaries,
            provider=_FakeSemanticProvider(profile, []),
            consent=resumed_boundaries.granted_consent(),
        )
        assert resumed_boundary_report.failed_job_ids == ()
        freeze_boundary_membership(service, inputs, resumed_boundaries)

        first_summaries = prepare_summaries(
            service,
            inputs,
            run_id="public-summaries-first",
            replay_existing=False,
        )
        assert len(first_summaries.jobs) > 1
        service.confirm_semantic_consent(
            first_summaries,
            first_summaries.granted_consent(),
        )
        first_summary_report = service.start_summaries(
            first_summaries,
            provider=_FakeSemanticProvider(profile, [], valid_responses=1),
            consent=first_summaries.granted_consent(),
        )
        assert first_summary_report.validated_job_ids == (first_summaries.jobs[0].job_id,)
        resumed_summaries = prepare_summaries(
            service,
            inputs,
            run_id="public-summaries-resumed",
            replay_existing=True,
        )
        assert resumed_summaries.consent.manifest_id != first_summaries.consent.manifest_id
        service.confirm_semantic_consent(
            resumed_summaries,
            resumed_summaries.granted_consent(),
        )
        resumed_summary_report = service.start_summaries(
            resumed_summaries,
            provider=_FakeSemanticProvider(profile, []),
            consent=resumed_summaries.granted_consent(),
        )
        assert resumed_summary_report.failed_job_ids == ()
        current = service.read_current_semantic_publication()
        assert current is not None
        return (
            str(current["publication_hash"]),
            first_boundaries.consent.manifest_id,
            resumed_boundaries.consent.manifest_id,
            first_summaries.consent.manifest_id,
        )


def test_current_semantic_publication_drives_page_and_exact_detail(tmp_path: Path) -> None:
    project_path = _project(tmp_path)
    publication_hash, cluster_id = _publish(project_path)

    with Project.open(project_path) as project:
        page = narrative_map_page(project)
        assert page["build_state"] == "complete"
        assert page["publication_hash"] == publication_hash
        nodes = _mappings(page["nodes"])
        edges = _mappings(page["edges"])
        assert any(item["kind"] == "major_cluster" for item in nodes)
        cluster_node = next(item for item in nodes if item["id"] == cluster_id)
        assert _mapping(cluster_node["summary_provenance"])["subject_id"] == cluster_id
        assert edges == ()  # all exact edges are internal to this one compact section
        detail = narrative_map_detail(project, cluster_id)

    assert _mapping(detail["element"])["id"] == cluster_id
    assert detail["claims"]
    summary_provenance = _mapping(detail["summary_provenance"])
    assert summary_provenance["subject_id"] == cluster_id
    assert _mapping(summary_provenance["provider_identity"])["adapter_version"] == (
        "codex_cli_structured:m13-codex-cli-adapter-v3"
    )
    assert detail["evidence"]
    assert detail["quotient_topology"] == {"node": None, "edge": None}
    assert detail["provider_calls"] == 0
    assert detail["m12_requests"] == 0


def test_current_publication_loads_all_confirmed_actual_producer_manifests(
    tmp_path: Path,
) -> None:
    project_path = _multi_window_project(tmp_path)
    publication_hash, first_boundary, final_boundary, first_summary = (
        _publish_with_resumed_producer_lineage(project_path)
    )

    with Project.open(project_path) as project:
        repository = NarrativeMapRepository(project)
        publication = repository.read_semantic_current()
        build = repository.read_semantic_build()
        page = narrative_map_page(project)

    assert publication is not None and build is not None
    assert publication["publication_hash"] == publication_hash
    assert publication["boundary_manifest_id"] == final_boundary
    assert first_boundary != final_boundary
    assert {
        item["manifest_id"]
        for item in _mappings(_mapping(publication["outline"])["boundary_provenance"])
    } == {first_boundary, final_boundary}
    assert first_summary != publication["summary_manifest_id"]
    assert {
        item["manifest_id"] for item in _mappings(publication["summary_provenance"])
    } == {first_summary, publication["summary_manifest_id"]}
    assert page["status"] == "available", page
    assert page["publication_hash"] == publication_hash


@pytest.mark.parametrize("stage", ("boundary", "summary"))
def test_current_publication_rejects_unknown_or_mismatched_producer_manifest(
    tmp_path: Path,
    stage: str,
) -> None:
    project_path = _multi_window_project(tmp_path)
    _publish_with_resumed_producer_lineage(project_path)

    with Project.open(project_path) as project:
        repository = NarrativeMapRepository(project)
        publication = repository.read_semantic_current()
        build = repository.read_semantic_build()
        assert publication is not None and build is not None
        tampered = deepcopy(dict(publication))
        if stage == "boundary":
            outline = dict(_mapping(tampered["outline"]))
            provenance = [
                dict(item) for item in _mappings(outline["boundary_provenance"])
            ]
        else:
            provenance = [
                dict(item) for item in _mappings(tampered["summary_provenance"])
            ]
        provenance[0]["manifest_id"] = "consent_unknown_public_synthetic"
        if stage == "boundary":
            outline["boundary_provenance"] = provenance
            tampered["outline"] = outline
        else:
            tampered["summary_provenance"] = provenance
        publication_hash = canonical_hash(
            {key: value for key, value in tampered.items() if key != "publication_hash"}
        )
        tampered["publication_hash"] = publication_hash
        repository.publish_semantic_current(
            build=build,
            publication=tampered,
        )
        page = narrative_map_page(project)

    assert page["status"] == "unavailable"
    assert page["reason"] == "semantic_publication_invalid"
    assert page["nodes"] == []


def test_current_publication_rejects_wrong_stage_job_lineage(tmp_path: Path) -> None:
    project_path = _multi_window_project(tmp_path)
    _publish_with_resumed_producer_lineage(project_path)

    with Project.open(project_path) as project:
        repository = NarrativeMapRepository(project)
        publication = repository.read_semantic_current()
        build = repository.read_semantic_build()
        assert publication is not None and build is not None
        tampered = deepcopy(dict(publication))
        outline = dict(_mapping(tampered["outline"]))
        boundary_provenance = [
            dict(item) for item in _mappings(outline["boundary_provenance"])
        ]
        summary_provenance = _mappings(tampered["summary_provenance"])
        for key in (
            "job_id",
            "input_hash",
            "manifest_id",
            "provider_identity_hash",
            "cache_identity",
        ):
            boundary_provenance[0][key] = summary_provenance[0][key]
        outline["boundary_provenance"] = boundary_provenance
        tampered["outline"] = outline
        tampered["publication_hash"] = canonical_hash(
            {key: value for key, value in tampered.items() if key != "publication_hash"}
        )
        repository.publish_semantic_current(build=build, publication=tampered)
        page = narrative_map_page(project)

    assert page["status"] == "unavailable"
    assert page["reason"] == "semantic_publication_invalid"
    assert page["nodes"] == []


def test_invalid_semantic_current_fails_closed_instead_of_using_legacy(tmp_path: Path) -> None:
    project_path = _project(tmp_path)
    _publish(project_path)
    with Project.open(project_path) as project:
        repository = NarrativeMapRepository(project)
        current = repository.read_semantic_current()
        build = repository.read_semantic_build()
        assert current is not None and build is not None
        current = dict(current)
        current["publication_hash"] = "0" * 64
        repository.publish_semantic_current(build=build, publication=current)
        page = narrative_map_page(project)

    assert page["status"] == "unavailable"
    assert page["reason"] == "semantic_publication_invalid"
    assert page["nodes"] == []


@pytest.mark.parametrize("missing_key", ("candidate_id", "window_id"))
def test_checksum_valid_publication_without_exact_boundary_identity_fails_closed(
    tmp_path: Path,
    missing_key: str,
) -> None:
    project_path = _project(tmp_path)
    _publish(project_path)
    with Project.open(project_path) as project:
        repository = NarrativeMapRepository(project)
        current = repository.read_semantic_current()
        build = repository.read_semantic_build()
        assert current is not None and build is not None
        tampered = deepcopy(dict(current))
        outline = _mapping(tampered["outline"])
        provenance = list(_mappings(outline["boundary_provenance"]))
        first = dict(provenance[0])
        first.pop(missing_key)
        provenance[0] = first
        mutable_outline = dict(outline)
        mutable_outline["boundary_provenance"] = provenance
        tampered["outline"] = mutable_outline
        tampered["publication_hash"] = canonical_hash(
            {key: value for key, value in tampered.items() if key != "publication_hash"}
        )
        repository.publish_semantic_current(build=build, publication=tampered)
        page = narrative_map_page(project)

    assert page["status"] == "unavailable"
    assert page["reason"] == "semantic_publication_invalid"
    assert page["nodes"] == []


def test_absent_semantic_current_keeps_legacy_provider_free_page(tmp_path: Path) -> None:
    project_path = _project(tmp_path)

    with Project.open(project_path) as project:
        page = narrative_map_page(project)

    assert page["status"] == "available"
    assert page["map_hash"]
    assert "build_state" not in page
    assert "publication_hash" not in page
    assert page["nodes"]
    assert page["provider_calls"] == 0
    assert page["m12_requests"] == 0
