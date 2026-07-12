"""Executable evidence for the independent M05 adversarial review."""

import shutil
from pathlib import Path

import pytest

from renpy_story_mapper.organization.cache import build_cache_key
from renpy_story_mapper.organization.contracts import (
    CodexMode,
    OrganizationConstraints,
    OrganizationRequest,
    OrganizationStage,
)
from renpy_story_mapper.organization.provider import CodexCliProvider
from renpy_story_mapper.project import Project, create_project
from renpy_story_mapper.ui.organization_workflow import (
    OrganizationOptions,
    OrganizationWorkflow,
)


def test_cloud_provider_command_is_intrinsically_luna_locked() -> None:
    """The provider boundary always emits the required cloud model flag."""

    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT)

    _program, arguments = provider.command(Path("schema.json"))

    assert arguments[arguments.index("--model") + 1] == "gpt-5.6-luna"
    assert 'model_reasoning_effort="high"' in arguments
    assert _disabled_features(arguments).issuperset({"fast_mode", "shell_tool"})
    with pytest.raises(ValueError, match=r"locked to gpt-5\.6-luna"):
        CodexCliProvider(CodexMode.CODEX_CHATGPT, model_override="other-model")
    with pytest.raises(ValueError, match=r"locked to gpt-5\.6-luna"):
        provider.set_model_override("other-model")
    with pytest.raises(ValueError, match=r"locked to gpt-5\.6-luna"):
        provider.command(Path("schema.json"), model="other-model")


def test_workflow_rejects_mislabeled_execution_profile() -> None:
    """Workflow metadata cannot disagree with the locked CLI profile."""

    options = OrganizationOptions(model=None, model_profile="balanced")
    workflow = OrganizationWorkflow(  # type: ignore[arg-type]
        object(), lambda _mode: (_ for _ in ()).throw(AssertionError("provider created"))
    )
    with pytest.raises(ValueError, match=r"GPT-5\.6 Luna"):
        workflow.organize(
            (),
            options,
            progress=lambda _percent, _status: None,
            cancelled=lambda: False,
            confirm_cloud=lambda _run_id: True,
        )


def test_claim_cannot_cite_evidence_outside_its_target_event_or_arc(tmp_path: Path) -> None:
    """Existing-ID validation also binds evidence to the exact claim target."""

    source = tmp_path / "game"
    fixture = Path(__file__).parent / "fixtures" / "m05" / "organization"
    shutil.copytree(fixture, source)
    project_path = tmp_path / "review.rsmproj"
    create_project(project_path, source).close()

    with Project.open(project_path) as project:
        connection = project._require_open()
        beats = [
            str(row[0])
            for row in connection.execute(
                "SELECT node_id FROM presentation_nodes WHERE level=3 ORDER BY sort_key,node_id"
            )
        ]
        assert len(beats) >= 2
        boundary = len(beats) // 2
        unrelated_evidence = str(
            connection.execute(
                "SELECT evidence_id FROM presentation_evidence WHERE node_id=?",
                (beats[-1],),
            ).fetchone()[0]
        )
        service = project.organization_service()
        run_id = service.create_run(
            provider_mode="codex_chatgpt",
            model_profile="high",
            model_fingerprint="gpt-5.6-luna",
            prompt_version="review",
            output_schema_version="review",
            generation="review",
        )
        candidate: dict[str, object] = {
            "events": [
                {
                    "id": "event-first",
                    "title": "First",
                    "summary": "First half.",
                    "beat_ids": beats[:boundary],
                },
                {
                    "id": "event-second",
                    "title": "Second",
                    "summary": "Second half.",
                    "beat_ids": beats[boundary:],
                },
            ],
            "arcs": [
                {
                    "id": "arc-first",
                    "title": "First arc",
                    "summary": "The first event.",
                    "event_ids": ["event-first"],
                },
                {
                    "id": "arc-second",
                    "title": "Second arc",
                    "summary": "The second event.",
                    "event_ids": ["event-second"],
                },
            ],
            "claims": [],
        }

        for target_key, target_id in (
            ("event_id", "event-first"),
            ("arc_id", "arc-first"),
        ):
            candidate["claims"] = [
                {
                    "id": f"claim-cross-target-{target_key}",
                    target_key: target_id,
                    "text": "A claim about the first target.",
                    "kind": "interpretation",
                    "evidence_ids": [unrelated_evidence],
                }
            ]
            with pytest.raises(ValueError, match="attached to their target"):
                service.create_draft(run_id, "review", candidate)


def test_cache_hash_includes_prompt_constraints() -> None:
    """Prompt-affecting constraints produce distinct integrated cache input hashes."""

    baseline = OrganizationRequest(
        run_id="run",
        chunk_id="chunk",
        scope_id="scope",
        stage=OrganizationStage.RECONCILE,
        payload={"events": [{"id": "event-a"}]},
        constraints=OrganizationConstraints(
            ordered_member_ids=("event-a",),
            required_member_ids=frozenset({"event-a"}),
            evidence_ids=frozenset({"evidence-a"}),
        ),
    )
    changed_requests = (
        OrganizationRequest(**{**baseline.__dict__, "stage": OrganizationStage.EVENTS}),
        OrganizationRequest(**{**baseline.__dict__, "scope_id": "other-scope"}),
        OrganizationRequest(**{**baseline.__dict__, "payload": {"events": []}}),
        _with_constraints(baseline, ordered_member_ids=("event-a", "event-b")),
        _with_constraints(baseline, required_member_ids=frozenset()),
        _with_constraints(baseline, context_member_ids=frozenset({"event-a"})),
        _with_constraints(baseline, fact_ids=frozenset({"fact-a"})),
        _with_constraints(
            baseline, evidence_ids=frozenset({"evidence-a", "evidence-b"})
        ),
        _with_constraints(baseline, character_names=frozenset({"Luna"})),
    )

    baseline_hash = _cache_input_hash(baseline)
    assert all(_cache_input_hash(changed) != baseline_hash for changed in changed_requests)


def _with_constraints(
    request: OrganizationRequest, **changes: object
) -> OrganizationRequest:
    constraints = OrganizationConstraints(
        **{**request.constraints.__dict__, **changes}  # type: ignore[arg-type]
    )
    return OrganizationRequest(**{**request.__dict__, "constraints": constraints})


def _cache_input_hash(request: OrganizationRequest) -> str:
    return build_cache_key(
        request,
        provider_mode=CodexMode.CODEX_CHATGPT,
        model_profile="high",
        model_fingerprint="gpt-5.6-luna",
        prompt_version="p",
        schema_version="s",
    ).input_hash


def _disabled_features(arguments: list[str]) -> set[str]:
    return {
        arguments[index + 1]
        for index, value in enumerate(arguments[:-1])
        if value == "--disable"
    }
