from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from renpy_story_mapper.project import Project
from renpy_story_mapper.story_map_v2.durable_repository import StoryMapV2RepositoryError
from renpy_story_mapper.story_map_v2.frozen_plans import FrozenPlanBundle
from renpy_story_mapper.story_map_v2.phase04_assembly import assemble_frozen_chunk_plan
from renpy_story_mapper.story_map_v2.phase04_chunk_adapter import (
    adapt_chunk_planning_projection,
)
from renpy_story_mapper.story_map_v2.phase04_chunk_plan import (
    plan_story_chunks,
    serialize_story_chunk_plan,
)
from renpy_story_mapper.story_map_v2.story_plan import serialize_story_plan
from renpy_story_mapper.story_map_v2.workflow_contracts import (
    GLOBAL_SUBMISSION_SLOTS,
    AttemptAccounting,
    AuthorityIdentity,
    ProviderCallKind,
    TransmissionDisposition,
    WorkflowFailure,
)
from renpy_story_mapper.story_map_v2.workflow_protocols import WorkflowProviderError
from renpy_story_mapper.story_map_v2.workflow_repository_adapter import (
    DurableWorkflowRepositoryAdapter,
)
from renpy_story_mapper.story_map_v2.workflow_service import StoryMapWorkflowService
from test_story_map_v2_phase04_story_plan import _planned
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


class ValidationBarrier:
    def __init__(self) -> None:
        self._barrier = threading.Barrier(2)

    def __call__(self, name: str, job_id: str) -> None:
        del job_id
        if name == "after_validation":
            self._barrier.wait(timeout=5)


class MixedIndeterminateFactory:
    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self):  # type: ignore[no-untyped-def]
        factory = self

        class Provider:
            def submit(self, request: bytes):  # type: ignore[no-untyped-def]
                with factory._lock:
                    factory.calls += 1
                calls = 0 if b"public-0" in request else 1
                raise WorkflowProviderError(
                    WorkflowFailure.INDETERMINATE,
                    TransmissionDisposition.INDETERMINATE,
                    AttemptAccounting(calls, calls, 0, calls),
                )

            def cancel(self) -> None:
                return

        return Provider()


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


def _frozen_plan_bundle() -> tuple[FrozenPlanBundle, tuple[bytes, ...]]:
    _graph, _scene_model, source, story_plan, _by_key = _planned()
    story_chunk_plan = plan_story_chunks(
        adapt_chunk_planning_projection(story_plan, source)
    )
    raw_story_fragments = tuple(
        span.raw_text.encode("utf-8")
        for span in source.spans
        if len(span.raw_text.encode("utf-8")) >= 24
    )
    return FrozenPlanBundle(story_plan, story_chunk_plan), raw_story_fragments


def test_prepare_approval_status_and_reopen_construct_zero_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "prepare.rsmp"
    frozen_plans, raw_story_fragments = _frozen_plan_bundle()
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        policy = _policy()
        plan, requests = _plan(1, policy)
        trap = ConstructionTrap()
        service = _service(adapter, requests, trap)

        preview = service.prepare(
            "run-prepare",
            plan,
            policy,
            _ceilings(1),
            frozen_plans=frozen_plans,
        )
        service.approve("run-prepare", preview.identity)
        assert service.status("run-prepare").pending_jobs == 1
        assert service.recover("run-prepare").not_transmitted_jobs == ()
        assert trap.constructions == 0

    replanning_calls = 0

    def replanning_trap(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal replanning_calls
        replanning_calls += 1
        raise AssertionError("reopen attempted forbidden Story Plan replanning")

    monkeypatch.setattr(
        "renpy_story_mapper.story_map_v2.story_plan.build_story_plan",
        replanning_trap,
    )
    monkeypatch.setattr(
        "renpy_story_mapper.story_map_v2.phase04_chunk_adapter.adapt_chunk_planning_projection",
        replanning_trap,
    )
    monkeypatch.setattr(
        "renpy_story_mapper.story_map_v2.phase04_chunk_plan.plan_story_chunks",
        replanning_trap,
    )

    with Project.open(path) as project:
        trap = ConstructionTrap()
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        reopened = _service(
            adapter, requests, trap
        )
        loaded_plans = adapter.load_frozen_plans("run-prepare")
        assert loaded_plans is not None
        assert reopened.status("run-prepare").approved
        assert reopened.recover("run-prepare").published_jobs == ()
        assert trap.constructions == 0
        assembly = assemble_frozen_chunk_plan(
            loaded_plans.story_chunk_plan,
            (),
            replanning_trap=replanning_trap,
        )

    assert serialize_story_plan(loaded_plans.story_plan) == frozen_plans.story_plan_bytes
    assert serialize_story_chunk_plan(
        loaded_plans.story_chunk_plan
    ) == frozen_plans.story_chunk_plan_bytes
    assert assembly.story_chunk_plan_identity == frozen_plans.story_chunk_plan.identity
    assert replanning_calls == 0
    database_bytes = path.read_bytes()
    assert all(fragment not in database_bytes for fragment in raw_story_fragments)


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


def test_cloned_adapter_recovers_exact_job_after_durable_validation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cloned-validation.rsmp"
    policy = _policy()
    plan, requests = _plan(1, policy)
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        cloud = RecordingFactory(policy.cloud, [_reply(policy.cloud, b"validated")])
        service = _service(
            adapter, requests, cloud, checkpoint=FaultOnce("after_validation")
        )
        preview = service.prepare("run-cloned", plan, policy, _ceilings(1))
        service.approve(preview.run_id, preview.identity)
        with pytest.raises(SimulatedProcessCrash):
            service.execute(
                preview.run_id,
                preview_identity=preview.identity,
                authority_identity=plan.authority_identity,
            )

        cloned = DurableWorkflowRepositoryAdapter.from_project(project)
        trap = ConstructionTrap()
        reopened = _service(cloned, requests, trap)
        report = reopened.recover(preview.run_id)
        assert report.finalized_jobs == ("job-0",)
        assert report.published_jobs == ("job-0",)
        assert cloned.load_cache(plan.jobs[0].cache_identity) is not None
        assert cloned.load_published_result(preview.run_id, "job-0") is not None
        assert trap.constructions == 0


def test_two_concurrent_same_identity_runs_route_cache_to_exact_jobs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "concurrent-cache.rsmp"
    policy = _policy()
    plan, requests = _plan(1, policy)
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        barrier = ValidationBarrier()
        services: list[tuple[StoryMapWorkflowService, str, str]] = []
        for suffix in ("a", "b"):
            cloud = RecordingFactory(policy.cloud, [_reply(policy.cloud, b"same")])
            service = StoryMapWorkflowService(
                adapter,
                DictMaterializer(requests),
                SyntheticValidator(),
                cloud_factory=cloud,
                checkpoint=barrier,
            )
            run_id = f"run-concurrent-{suffix}"
            preview = service.prepare(run_id, plan, policy, _ceilings(1))
            service.approve(run_id, preview.identity)
            services.append((service, run_id, preview.identity))

        def execute(item: tuple[StoryMapWorkflowService, str, str]) -> None:
            service, run_id, identity = item
            status = service.execute(
                run_id,
                preview_identity=identity,
                authority_identity=plan.authority_identity,
            )
            assert status.accepted_jobs == 1

        with ThreadPoolExecutor(max_workers=2) as executor:
            tuple(executor.map(execute, services))
        rows = project._require_open().execute(
            "SELECT run_id, status, resolution FROM story_map_v2_jobs ORDER BY run_id"
        ).fetchall()
        assert len(rows) == 2
        assert {(str(row[1]), str(row[2])) for row in rows} == {
            ("published", "accepted")
        }
        for _, run_id, _ in services:
            assert adapter.load_published_result(run_id, "job-0") is not None


def test_fallback_validation_recovery_uses_exact_loopback_cache_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "fallback-validation.rsmp"
    policy = _policy(fallback=True)
    plan, requests = _plan(1, policy)
    assert policy.loopback is not None
    cloud = RecordingFactory(
        policy.cloud,
        [
            WorkflowProviderError(
                WorkflowFailure.CONTENT_REFUSAL,
                TransmissionDisposition.TRANSMITTED,
                AttemptAccounting(1, 1, 0, 1),
            )
        ],
    )
    loopback = RecordingFactory(policy.loopback, [_reply(policy.loopback, b"local")])
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        service = _service(
            adapter,
            requests,
            cloud,
            loopback=loopback,
            checkpoint=FaultOnce("after_validation"),
        )
        preview = service.prepare("run-fallback-cache", plan, policy, _ceilings(1, fallbacks=1))
        service.approve(preview.run_id, preview.identity)
        with pytest.raises(SimulatedProcessCrash):
            service.execute(
                preview.run_id,
                preview_identity=preview.identity,
                authority_identity=plan.authority_identity,
            )
        cloned = DurableWorkflowRepositoryAdapter.from_project(project)
        report = cloned.recover(preview.run_id)
        local_identity = policy.input_identity(
            plan.jobs[0].serialized_request_identity,
            mode=policy.loopback.mode,
        ).cache_identity
        assert report.published_jobs == ("job-0",)
        assert cloned.load_cache(local_identity) is not None
        assert cloned.load_cache(plan.jobs[0].cache_identity) is None


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


def test_mixed_zero_and_one_call_indeterminate_retries_use_exact_capacities(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mixed-retry-capacity.rsmp"
    policy = _policy()
    plan, requests = _plan(2, policy)
    factory = MixedIndeterminateFactory()
    with Project.create(path) as project:
        adapter = DurableWorkflowRepositoryAdapter.from_project(project)
        service = StoryMapWorkflowService(
            adapter,
            DictMaterializer(requests),
            SyntheticValidator(),
            cloud_factory=factory,
        )
        preview = service.prepare("run-mixed", plan, policy, _ceilings(2, retries=1))
        service.approve(preview.run_id, preview.identity)
        first = service.execute(
            preview.run_id,
            preview_identity=preview.identity,
            authority_identity=plan.authority_identity,
        )
        assert first.indeterminate_jobs == 2
        rows = project._require_open().execute(
            """SELECT jobs.ordinal, attempts.attempt_id
               FROM story_map_v2_jobs AS jobs
               JOIN story_map_v2_attempts AS attempts ON attempts.job_id = jobs.job_id
               ORDER BY jobs.ordinal, attempts.ordinal"""
        ).fetchall()
        assert len(rows) == 2
        for job_ordinal, attempt_id in rows:
            service.approve_indeterminate_retry(
                preview.run_id,
                preview_identity=preview.identity,
                job_id=f"job-{int(job_ordinal)}",
                indeterminate_attempt_id=str(attempt_id),
            )
        execution_id = adapter.begin_execution(
            preview.run_id, preview.identity, plan.authority_identity.value
        )
        ordinary_claim = adapter.claim_next_job(
            preview.run_id,
            execution_id,
            "ordinary-worker",
            submission_slots=GLOBAL_SUBMISSION_SLOTS,
        )
        assert ordinary_claim is not None
        assert ordinary_claim.job.job_id == "job-0"
        ordinary = adapter.reserve_attempt(
            ordinary_claim,
            ProviderCallKind.MAPPING,
            policy.input_identity(ordinary_claim.job.serialized_request_identity),
            preview.ceilings,
        )
        assert ordinary is not None
        assert ordinary.retry_of_attempt_id == str(rows[0][1])
        assert not ordinary.uses_supplemental_retry_capacity

        supplemental_claim = adapter.claim_next_job(
            preview.run_id,
            execution_id,
            "supplemental-worker",
            submission_slots=GLOBAL_SUBMISSION_SLOTS,
        )
        assert supplemental_claim is not None
        assert supplemental_claim.job.job_id == "job-1"
        supplemental = adapter.reserve_attempt(
            supplemental_claim,
            ProviderCallKind.MAPPING,
            policy.input_identity(supplemental_claim.job.serialized_request_identity),
            preview.ceilings,
        )
        assert supplemental is not None
        assert supplemental.retry_of_attempt_id == str(rows[1][1])
        assert supplemental.uses_supplemental_retry_capacity

        reloaded = project.story_map_v2_repository()
        run_row = project._require_open().execute(
            "SELECT run_id FROM story_map_v2_runs LIMIT 1"
        ).fetchone()
        assert run_row is not None
        durable_jobs = reloaded.list_jobs(str(run_row[0]))
        first_retry = reloaded.list_attempts(durable_jobs[0].descriptor.job_id)[-1]
        second_retry = reloaded.list_attempts(durable_jobs[1].descriptor.job_id)[-1]
        assert first_retry.reservation.retry_of_attempt_id == ordinary.retry_of_attempt_id
        assert not first_retry.reservation.uses_supplemental_retry_capacity
        assert second_retry.reservation.retry_of_attempt_id == supplemental.retry_of_attempt_id
        assert second_retry.reservation.uses_supplemental_retry_capacity


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
            "SELECT ordinal, call_kind, transmission_disposition, retry_of_attempt_id, "
            "uses_supplemental_retry_capacity FROM story_map_v2_attempts "
            "ORDER BY ordinal"
        ).fetchall()
        assert [int(row[0]) for row in attempts] == [1, 2, 3, 4]
        expected = "replacement_review" if continuation == "review" else "refusal_fallback"
        assert [str(row[1]) for row in attempts[1:]] == [expected, expected, expected]
        assert str(attempts[2][2]) == "definitely_not_transmitted"
        assert attempts[0][3] is None and int(attempts[0][4]) == 0
        assert attempts[1][3] is None and int(attempts[1][4]) == 0
        assert str(attempts[2][3]) == attempt_id and int(attempts[2][4]) == 1
        assert str(attempts[3][3]) == attempt_id and int(attempts[3][4]) == 1
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
