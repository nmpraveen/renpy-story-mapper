from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from renpy_story_mapper.project import Project
from renpy_story_mapper.story_map_v2.durable_repository import StoryMapV2RepositoryError
from renpy_story_mapper.story_map_v2.workflow_contracts import (
    GLOBAL_SUBMISSION_SLOTS,
    AttemptAccounting,
    AuthorityIdentity,
    TransmissionDisposition,
    WorkflowFailure,
)
from renpy_story_mapper.story_map_v2.workflow_protocols import WorkflowProviderError
from renpy_story_mapper.story_map_v2.workflow_repository_adapter import (
    DurableWorkflowRepositoryAdapter,
)
from renpy_story_mapper.story_map_v2.workflow_service import StoryMapWorkflowService
from test_story_map_v2_phase04_workflow import (
    BarrierFactory,
    ConstructionTrap,
    DictMaterializer,
    FaultOnce,
    FaultOnOccurrence,
    RecordingFactory,
    SimulatedProcessCrash,
    SyntheticValidator,
    _ceilings,
    _plan,
    _policy,
    _reply,
)


class CancelAtSubmittingAdapter(DurableWorkflowRepositoryAdapter):
    def mark_submitting(self, claim, reservation):  # type: ignore[no-untyped-def]
        self.persist_cancellation(claim.run_id)
        return super().mark_submitting(claim, reservation)


def _service(
    adapter: DurableWorkflowRepositoryAdapter,
    requests: dict[str, bytes],
    factory: RecordingFactory | ConstructionTrap | BarrierFactory,
    *,
    loopback: RecordingFactory | None = None,
    checkpoint: FaultOnce | None = None,
) -> StoryMapWorkflowService:
    return StoryMapWorkflowService(
        adapter,
        DictMaterializer(requests),
        SyntheticValidator(),
        cloud_factory=factory,
        loopback_factory=loopback,
        checkpoint=checkpoint,
    )


def test_prepare_approval_status_and_reopen_construct_zero_providers(tmp_path: Path) -> None:
    path = tmp_path / "prepare.rsmp"
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        policy = _policy()
        plan, requests = _plan(1, policy)
        trap = ConstructionTrap()
        service = _service(adapter, requests, trap)

        preview = service.prepare("run-prepare", plan, policy, _ceilings(1))
        service.approve("run-prepare", preview.identity)
        assert service.status("run-prepare").pending_jobs == 1
        assert service.recover("run-prepare").not_transmitted_jobs == ()
        assert trap.constructions == 0

    with Project.open(path) as project:
        trap = ConstructionTrap()
        reopened = _service(
            DurableWorkflowRepositoryAdapter.from_project(project), requests, trap
        )
        assert reopened.status("run-prepare").approved
        assert reopened.recover("run-prepare").published_jobs == ()
        assert trap.constructions == 0


def test_real_service_publishes_immutable_result_and_second_run_uses_cache(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cache.rsmp"
    policy = _policy()
    plan, requests = _plan(1, policy)
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        cloud = RecordingFactory(policy.cloud, [_reply(policy.cloud, b"first")])
        service = _service(adapter, requests, cloud)
        preview = service.prepare("run-first", plan, policy, _ceilings(1))
        service.approve("run-first", preview.identity)
        status = service.execute(
            "run-first",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        published = adapter.load_published_result("run-first", "job-0")
        assert status.accepted_jobs == 1
        assert published is not None
        assert cloud.calls == 1

        cached_plan, cached_requests = _plan(1, policy)
        trap = ConstructionTrap()
        cached_service = _service(adapter, cached_requests, trap)
        cached_preview = cached_service.prepare(
            "run-cached", cached_plan, policy, _ceilings(1)
        )
        assert cached_preview.cache_hit_job_ids == ("job-0",)
        cached_service.approve("run-cached", cached_preview.identity)
        cached_status = cached_service.execute(
            "run-cached",
            preview_identity=cached_preview.identity,
            authority_identity=cached_plan.authority_identity,
        )
        assert cached_status.accepted_jobs == 1
        assert trap.constructions == 0
        assert adapter.load_published_result("run-first", "job-0") == published


def test_64_jobs_use_exact_six_real_sqlite_submission_slots(tmp_path: Path) -> None:
    path = tmp_path / "six-slots.rsmp"
    policy = _policy()
    plan, requests = _plan(64, policy)
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        cloud = BarrierFactory(policy.cloud, 64)
        service = _service(adapter, requests, cloud)
        preview = service.prepare("run-64", plan, policy, _ceilings(64))
        service.approve("run-64", preview.identity)
        status = service.execute(
            "run-64",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert status.accepted_jobs == 64
        assert cloud.calls == 64
        assert cloud.max_active == GLOBAL_SUBMISSION_SLOTS


def test_two_adapters_share_global_claim_limit_without_duplicate_claims(
    tmp_path: Path,
) -> None:
    path = tmp_path / "two-connections.rsmp"
    policy = _policy()
    plan, _ = _plan(12, policy)
    with Project.create(path) as project:
        first = DurableWorkflowRepositoryAdapter.from_project(project)
        preview = StoryMapWorkflowService(
            first,
            DictMaterializer({}),
            SyntheticValidator(),
            cloud_factory=ConstructionTrap(),
        ).prepare("run-claims", plan, policy, _ceilings(12))
        approval_service = StoryMapWorkflowService(
            first,
            DictMaterializer({}),
            SyntheticValidator(),
            cloud_factory=ConstructionTrap(),
        )
        approval_service.approve("run-claims", preview.identity)
        execution = first.begin_execution(
            "run-claims", preview.identity, plan.authority_identity.value
        )

        second = DurableWorkflowRepositoryAdapter.from_project(project)
        claims = []
        for index in range(12):
            adapter = first if index % 2 == 0 else second
            claim = adapter.claim_next_job(
                "run-claims",
                execution,
                f"worker-{index}",
                submission_slots=GLOBAL_SUBMISSION_SLOTS,
            )
            if claim is not None:
                claims.append(claim)
        assert len(claims) == GLOBAL_SUBMISSION_SLOTS
        assert len({claim.job.job_id for claim in claims}) == GLOBAL_SUBMISSION_SLOTS


def test_definite_nontransmission_and_reserved_crash_resume_same_mapping(
    tmp_path: Path,
) -> None:
    path = tmp_path / "resume.rsmp"
    policy = _policy()
    plan, requests = _plan(1, policy)
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        cloud = RecordingFactory(
            policy.cloud,
            [
                WorkflowProviderError(
                    WorkflowFailure.PROVIDER_UNAVAILABLE,
                    TransmissionDisposition.NOT_TRANSMITTED,
                    AttemptAccounting.zero(),
                ),
                _reply(policy.cloud, b"resumed"),
            ],
        )
        service = _service(adapter, requests, cloud)
        preview = service.prepare("run-resume", plan, policy, _ceilings(1))
        service.approve("run-resume", preview.identity)
        first = service.execute(
            "run-resume",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert first.resumable_jobs == 1
        second = service.execute(
            "run-resume",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert second.accepted_jobs == 1
        assert cloud.calls == 2

        crash_policy = _policy()
        crash_plan, crash_requests = _plan(
            1,
            crash_policy,
            authority="authority-crash",
            request_prefix=b'{"story":"crash-',
        )
        crash = FaultOnce("after_reservation")
        crash_cloud = RecordingFactory(crash_policy.cloud, [_reply(crash_policy.cloud)])
        crashing = _service(
            adapter, crash_requests, crash_cloud, checkpoint=crash
        )
        crash_preview = crashing.prepare(
            "run-crash", crash_plan, crash_policy, _ceilings(1)
        )
        crashing.approve("run-crash", crash_preview.identity)
        with pytest.raises(SimulatedProcessCrash):
            crashing.execute(
                "run-crash",
                preview_identity=crash_preview.identity,
                authority_identity=crash_plan.authority_identity,
            )
        report = crashing.recover("run-crash")
        assert report.not_transmitted_jobs == ("job-0",)
        resumed = crashing.execute(
            "run-crash",
            preview_identity=crash_preview.identity,
            authority_identity=crash_plan.authority_identity,
        )
        assert resumed.accepted_jobs == 1
        assert crash_cloud.calls == 1


def test_calls_one_indeterminate_retry_uses_exact_supplemental_capacity_once(
    tmp_path: Path,
) -> None:
    path = tmp_path / "retry.rsmp"
    policy = _policy()
    plan, requests = _plan(1, policy)
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        cloud = RecordingFactory(
            policy.cloud,
            [
                WorkflowProviderError(
                    WorkflowFailure.INDETERMINATE,
                    TransmissionDisposition.INDETERMINATE,
                    AttemptAccounting(1, 3, 0, 2),
                ),
                _reply(policy.cloud, b"approved-retry"),
            ],
        )
        service = _service(adapter, requests, cloud)
        preview = service.prepare("run-retry", plan, policy, _ceilings(1, retries=1))
        service.approve("run-retry", preview.identity)
        first = service.execute(
            "run-retry",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert first.indeterminate_jobs == 1
        row = project._require_open().execute(
            "SELECT attempt_id FROM story_map_v2_attempts ORDER BY ordinal DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        attempt_id = str(row[0])
        service.approve_indeterminate_retry(
            "run-retry",
            preview_identity=preview.identity,
            job_id="job-0",
            indeterminate_attempt_id=attempt_id,
        )
        second = service.execute(
            "run-retry",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert second.accepted_jobs == 1
        assert second.accounting.calls == 2
        assert cloud.calls == 2
        with pytest.raises(StoryMapV2RepositoryError):
            service.approve_indeterminate_retry(
                "run-retry",
                preview_identity=preview.identity,
                job_id="job-0",
                indeterminate_attempt_id=attempt_id,
            )


@pytest.mark.parametrize("continuation", ["review", "fallback"])
def test_calls_one_continuation_retry_survives_pretransmission_crash(
    tmp_path: Path, continuation: str
) -> None:
    path = tmp_path / f"{continuation}-retry.rsmp"
    policy = _policy(fallback=continuation == "fallback")
    plan, requests = _plan(1, policy)
    fault = FaultOnOccurrence("after_reservation", 3)
    if continuation == "review":
        cloud = RecordingFactory(
            policy.cloud,
            [
                _reply(policy.cloud, b"flagged"),
                WorkflowProviderError(
                    WorkflowFailure.INDETERMINATE,
                    TransmissionDisposition.INDETERMINATE,
                    AttemptAccounting(1, 2, 0, 1),
                ),
                _reply(policy.cloud, b"reviewed"),
            ],
        )
        loopback = None
    else:
        cloud = RecordingFactory(
            policy.cloud,
            [
                WorkflowProviderError(
                    WorkflowFailure.CONTENT_REFUSAL,
                    TransmissionDisposition.TRANSMITTED,
                    AttemptAccounting(1, 2, 0, 1),
                )
            ],
        )
        assert policy.loopback is not None
        loopback = RecordingFactory(
            policy.loopback,
            [
                WorkflowProviderError(
                    WorkflowFailure.INDETERMINATE,
                    TransmissionDisposition.INDETERMINATE,
                    AttemptAccounting(1, 2, 0, 1),
                ),
                _reply(policy.loopback, b"local"),
            ],
        )
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        service = _service(
            adapter, requests, cloud, loopback=loopback, checkpoint=fault
        )
        preview = service.prepare(
            f"run-{continuation}",
            plan,
            policy,
            _ceilings(
                1,
                reviews=1 if continuation == "review" else 0,
                fallbacks=1 if continuation == "fallback" else 0,
                retries=1,
            ),
        )
        service.approve(preview.run_id, preview.identity)
        initial = service.execute(
            preview.run_id,
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert initial.indeterminate_jobs == 1
        row = project._require_open().execute(
            "SELECT attempt_id FROM story_map_v2_attempts ORDER BY ordinal DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        attempt_id = str(row[0])
        service.approve_indeterminate_retry(
            preview.run_id,
            preview_identity=preview.identity,
            job_id="job-0",
            indeterminate_attempt_id=attempt_id,
        )
        with pytest.raises(SimulatedProcessCrash):
            service.execute(
                preview.run_id,
                preview_identity=preview.identity,
                authority_identity=plan.authority_identity,
            )
        report = service.recover(preview.run_id)
        assert report.not_transmitted_jobs == ("job-0",)
        final = service.execute(
            preview.run_id,
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert final.accepted_jobs == 1
        attempts = project._require_open().execute(
            "SELECT ordinal, call_kind, transmission_disposition FROM story_map_v2_attempts "
            "ORDER BY ordinal"
        ).fetchall()
        assert [int(row[0]) for row in attempts] == [1, 2, 3, 4]
        expected = "replacement_review" if continuation == "review" else "refusal_fallback"
        assert [str(row[1]) for row in attempts[1:]] == [expected, expected, expected]
        assert str(attempts[2][2]) == "definitely_not_transmitted"
        assert final.accounting.calls == 3
        if loopback is None:
            assert cloud.calls == 3
        else:
            assert cloud.calls == 1
            assert loopback.calls == 2


def test_cancel_wins_atomic_submitting_race_with_zero_submit_or_publication(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cancel-race.rsmp"
    policy = _policy()
    plan, requests = _plan(1, policy)
    with Project.create(path) as project:
        adapter = CancelAtSubmittingAdapter(project.story_map_v2_repository())
        cloud = RecordingFactory(policy.cloud, [_reply(policy.cloud)])
        service = _service(adapter, requests, cloud)
        preview = service.prepare("run-cancel", plan, policy, _ceilings(1))
        service.approve("run-cancel", preview.identity)
        status = service.execute(
            "run-cancel",
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert status.cancelled
        assert cloud.calls == 0
        assert adapter.load_published_result("run-cancel", "job-0") is None


@pytest.mark.parametrize(
    ("checkpoint", "recovery_state"),
    [
        ("before_reservation", "pending"),
        ("after_transport_return", "indeterminate"),
        ("after_validation", "published"),
        ("after_finalization", "published"),
        ("after_publication", "already_published"),
    ],
)
def test_real_sqlite_recovery_at_service_fault_checkpoints(
    tmp_path: Path, checkpoint: str, recovery_state: str
) -> None:
    path = tmp_path / f"fault-{checkpoint}.rsmp"
    policy = _policy()
    plan, requests = _plan(
        1,
        policy,
        request_prefix=f'{{"story":"{checkpoint}-'.encode(),
    )
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        cloud = RecordingFactory(policy.cloud, [_reply(policy.cloud, b"fault-result")])
        fault = FaultOnce(checkpoint)
        service = _service(adapter, requests, cloud, checkpoint=fault)
        preview = service.prepare(
            f"run-{checkpoint}", plan, policy, _ceilings(1, retries=1)
        )
        service.approve(preview.run_id, preview.identity)
        with pytest.raises(SimulatedProcessCrash):
            service.execute(
                preview.run_id,
                preview_identity=preview.identity,
                authority_identity=plan.authority_identity,
            )
        report = service.recover(preview.run_id)
        if recovery_state == "pending":
            assert report == type(report)((), (), (), (), ())
            resumed = _service(adapter, requests, cloud).execute(
                preview.run_id,
                preview_identity=preview.identity,
                authority_identity=plan.authority_identity,
            )
            assert resumed.accepted_jobs == 1
            assert cloud.calls == 1
        elif recovery_state == "indeterminate":
            assert report.indeterminate_jobs == ("job-0",)
            assert service.status(preview.run_id).indeterminate_jobs == 1
            assert cloud.calls == 1
        elif recovery_state == "published":
            assert report.published_jobs == ("job-0",)
            assert adapter.load_published_result(preview.run_id, "job-0") is not None
            assert cloud.calls == 1
        else:
            assert report.published_jobs == ()
            assert adapter.load_published_result(preview.run_id, "job-0") is not None
            assert cloud.calls == 1


def test_durable_workflow_rows_contain_no_private_markers_or_absolute_paths(
    tmp_path: Path,
) -> None:
    path = tmp_path / "privacy.rsmp"
    policy = _policy()
    plan, requests = _plan(1, policy)
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        cloud = RecordingFactory(policy.cloud, [_reply(policy.cloud, b"public")])
        service = _service(adapter, requests, cloud)
        preview = service.prepare("run-privacy", plan, policy, _ceilings(1))
        service.approve("run-privacy", preview.identity)
        service.execute(
            "run-privacy",
            preview_identity=preview.identity,
            authority_identity=AuthorityIdentity("authority-public-v1"),
        )

    connection = sqlite3.connect(path)
    try:
        dump = "\n".join(connection.iterdump()).lower()
    finally:
        connection.close()
    for marker in (
        "@@source",
        "rawrequest",
        "rawresponse",
        "providerstderr",
        "credential",
        "c:\\users\\private",
        "/opt/private",
    ):
        assert marker not in dump
