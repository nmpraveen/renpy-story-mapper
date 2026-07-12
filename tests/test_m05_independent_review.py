"""Executable evidence for the independent M05 adversarial review."""

import hashlib
import json
import shutil
from pathlib import Path

from renpy_story_mapper.organization.cache import build_cache_key
from renpy_story_mapper.organization.contracts import (
    CodexMode,
    OrganizationConstraints,
    OrganizationRequest,
    OrganizationStage,
)
from renpy_story_mapper.organization.provider import CodexCliProvider
from renpy_story_mapper.project import Project, create_project
from renpy_story_mapper.ui.organization_workflow import OrganizationOptions


def test_reproduction_cloud_provider_command_is_not_intrinsically_luna_locked() -> None:
    """The provider boundary permits a cloud command without the required model flag."""

    provider = CodexCliProvider(CodexMode.CODEX_CHATGPT)

    _program, arguments = provider.command(Path("schema.json"))

    assert "--model" not in arguments
    assert 'model_reasoning_effort="high"' in arguments
    assert _disabled_features(arguments).issuperset({"fast_mode", "shell_tool"})


def test_reproduction_workflow_options_accept_mislabeled_execution_profile() -> None:
    """Workflow options accept cache/run identity that disagrees with the fixed CLI profile."""

    options = OrganizationOptions(model=None, model_profile="balanced")
    provider = CodexCliProvider(options.mode)

    _program, arguments = provider.command(Path("schema.json"), model=options.model)

    assert options.model_profile == "balanced"
    assert options.model is None
    assert 'model_reasoning_effort="high"' in arguments
    assert "--model" not in arguments


def test_reproduction_claim_can_cite_evidence_outside_its_target_event(tmp_path: Path) -> None:
    """Existing-ID validation does not require claim evidence to belong to its target."""

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
        candidate = {
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
                    "id": "arc-all",
                    "title": "All",
                    "summary": "All events.",
                    "event_ids": ["event-first", "event-second"],
                }
            ],
            "claims": [
                {
                    "id": "claim-cross-target",
                    "event_id": "event-first",
                    "text": "A claim about the first event.",
                    "kind": "interpretation",
                    "evidence_ids": [unrelated_evidence],
                }
            ],
        }

        draft_id = service.create_draft(run_id, "review", candidate)

        assert next(draft for draft in service.drafts() if draft.id == draft_id).status == "pending"


def test_reproduction_workflow_cache_hash_omits_prompt_constraints() -> None:
    """The workflow hash can collide even though the serialized provider prompt changes."""

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
    changed = OrganizationRequest(
        **{
            **baseline.__dict__,
            "constraints": OrganizationConstraints(
                ordered_member_ids=("event-a",),
                required_member_ids=frozenset({"event-a"}),
                evidence_ids=frozenset({"evidence-a", "evidence-b"}),
            ),
        }
    )

    def workflow_input_hash(request: OrganizationRequest) -> str:
        payload = json.dumps(
            request.payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    assert workflow_input_hash(baseline) == workflow_input_hash(changed)
    assert build_cache_key(
        baseline,
        provider_mode=CodexMode.CODEX_CHATGPT,
        model_profile="high",
        model_fingerprint="gpt-5.6-luna",
        prompt_version="p",
        schema_version="s",
    ).digest() != build_cache_key(
        changed,
        provider_mode=CodexMode.CODEX_CHATGPT,
        model_profile="high",
        model_fingerprint="gpt-5.6-luna",
        prompt_version="p",
        schema_version="s",
    ).digest()


def _disabled_features(arguments: list[str]) -> set[str]:
    return {
        arguments[index + 1]
        for index, value in enumerate(arguments[:-1])
        if value == "--disable"
    }
