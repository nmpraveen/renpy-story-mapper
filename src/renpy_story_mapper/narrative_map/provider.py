"""Provider-neutral transport beneath the M15 semantic boundary.

The prepared job payload is transient.  Only validated normalized results and identity metadata
may cross into :mod:`narrative_map.persistence`.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from importlib.resources import as_file, files
from threading import Lock
from typing import Protocol, cast

from renpy_story_mapper.narrative.contracts import ProviderIdentity, ProviderSettings
from renpy_story_mapper.narrative.provider import ProviderUsage
from renpy_story_mapper.narrative_map.contracts import (
    AuthorityBinding,
    BoundaryCandidate,
    JsonValue,
    NarrativeEvent,
    canonical_hash,
    stable_m15_id,
)
from renpy_story_mapper.narrative_map.semantic_contracts import (
    M15_WHOLE_SCOPE_EDITORIAL_BATCH_SCHEMA,
    M15_WHOLE_SCOPE_HIERARCHY_PROPOSAL_SCHEMA,
    MAXIMUM_DAY1_PROVIDER_SUBMISSIONS,
    BoundaryWindow,
    ChoiceComposition,
    MajorCluster,
    SemanticBeat,
    WholeScopeSemanticStage,
)
from renpy_story_mapper.organization.sterile_runner import (
    SterileCodexRunner,
    SterileRunnerError,
    SterileRunRequest,
    SterileRunResult,
)

BOUNDARY_PROMPT_VERSION = "m15-boundary-prompt-v1"
BOUNDARY_RESPONSE_SCHEMA = "m15-boundary-decision-v2"
SUMMARY_PROMPT_VERSION = "m15-event-summary-prompt-v1"
SUMMARY_RESPONSE_SCHEMA = "m15-event-summary-v2"
SEMANTIC_BOUNDARY_PROMPT_VERSION = "m15-semantic-boundary-prompt-v3"
SEMANTIC_BOUNDARY_RESPONSE_SCHEMA = "m15-boundary-window-v3"
SEMANTIC_SUMMARY_PROMPT_VERSION = "m15-semantic-summary-prompt-v3"
SEMANTIC_SUMMARY_RESPONSE_SCHEMA = "m15-semantic-summary-v3"
WHOLE_SCOPE_HIERARCHY_PROMPT_VERSION = "m15-whole-scope-hierarchy-prompt-v4"
WHOLE_SCOPE_HIERARCHY_RESPONSE_SCHEMA = M15_WHOLE_SCOPE_HIERARCHY_PROPOSAL_SCHEMA
WHOLE_SCOPE_EDITORIAL_PROMPT_VERSION = "m15-whole-scope-editorial-prompt-v1"
WHOLE_SCOPE_EDITORIAL_RESPONSE_SCHEMA = M15_WHOLE_SCOPE_EDITORIAL_BATCH_SCHEMA
MAXIMUM_INPUT_BYTES = 1_000_000
MAXIMUM_OUTPUT_BYTES = 2_000_000
_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
SEMANTIC_REPAIR_POLICY_VERSION = "m15-semantic-repair-guidance-v2"
WHOLE_SCOPE_REPAIR_POLICY_VERSION = "m15-whole-scope-targeted-repair-v5"
_SEMANTIC_REPAIR_GUIDANCE = {
    "invalid_title": (
        "The prior title failed strict validation. Replace only the title with a natural story "
        "title, then scan every word case-insensitively before returning it. BOUNDARY and LINE "
        "are forbidden, as are atom, cache, cluster, evidence, job, label, menu, node, and source. "
        "Do not begin with bg, cg, scene, show, hide, or image; do not describe a count of atoms, "
        "lines, items, or nodes."
    ),
    "invalid_characters": (
        "Replace only characters. Copy exact strings from request.job.known_characters, omit any "
        "name not in that list, include each supported name at most once, and return [] when none "
        "is supported. Never normalize or alias."
    ),
}
_WHOLE_SCOPE_REPAIR_GUIDANCE = {
    "uncertain_membership": (
        "The prior Stage H proposal declared unresolved membership. An accepted proposal requires "
        "uncertain_unit_ids must be [] only after you re-evaluate every listed uncertain unit "
        "against the complete supplied evidence and hard constraints. Semantic ambiguity alone is "
        "not unresolved authority: express it with lower confidence and warnings, and use a "
        "conservative singleton beat when the unit's relation to its neighbors is ambiguous. "
        "Never clear uncertainty mechanically or guess. Return exact supplied uncertain unit IDs "
        "only when required evidence is missing or no placement, including a singleton beat, can "
        "satisfy the supplied structural constraints; that response intentionally fails closed."
    ),
}

CancelledCallback = Callable[[], bool]


class _ConsentCallLedger:
    """Transient atomic call grants shared by copies of one consent manifest."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._bound_manifest_id: str | None = None
        self._reserved_calls = 0

    def reserve(
        self,
        manifest: NarrativeConsentManifest,
        job: PreparedNarrativeJob,
        profile: ProviderProfile,
    ) -> None:
        with self._lock:
            manifest.validate_job(job, profile)
            manifest_id = manifest.manifest_id
            if self._bound_manifest_id is None:
                self._bound_manifest_id = manifest_id
            elif self._bound_manifest_id != manifest_id:
                raise ValueError("M15 consent call ledger identity does not match")
            if self._reserved_calls >= manifest.maximum_provider_calls:
                raise NarrativeMapProviderError(
                    "consent_call_limit",
                    "The M15 consent has no remaining provider call grant.",
                    provider_call_reserved=False,
                )
            self._reserved_calls += 1


class ProviderJobKind(StrEnum):
    BOUNDARY = "boundary"
    EVENT_SUMMARY = "event_summary"
    SEMANTIC_BOUNDARY_WINDOW = "semantic_boundary_window"
    SEMANTIC_SUMMARY = "semantic_summary"
    WHOLE_SCOPE_HIERARCHY = "whole_scope_hierarchy"
    WHOLE_SCOPE_EDITORIAL = "whole_scope_editorial"


@dataclass(frozen=True)
class ProviderProfile:
    """Exact non-secret provider/model/settings identity used before submission and for cache."""

    provider: str
    adapter: str
    adapter_version: str
    requested_model: str
    settings: ProviderSettings

    def __post_init__(self) -> None:
        for value, label in (
            (self.provider, "provider"),
            (self.adapter, "provider adapter"),
            (self.adapter_version, "provider adapter version"),
            (self.requested_model, "requested model"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{label} must be a non-empty trimmed string")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "provider": self.provider,
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "requested_model": self.requested_model,
            "settings": self.settings.to_dict(),
        }

    @property
    def settings_hash(self) -> str:
        return canonical_hash(self.settings.to_dict())


@dataclass(frozen=True)
class WholeScopeEditorialSubject:
    """Exact frozen Stage E subject identity and its allowed evidence vocabulary."""

    subject_kind: str
    subject_id: str
    membership_hash: str
    evidence_ids: tuple[str, ...]
    known_characters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.subject_kind not in {"beat", "major_cluster", "choice"}:
            raise ValueError("whole-scope editorial subject kind is unsupported")
        for value, label in (
            (self.subject_id, "whole-scope editorial subject ID"),
            (self.membership_hash, "whole-scope editorial membership hash"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{label} must be a non-empty trimmed string")
        for values, label in (
            (self.evidence_ids, "whole-scope editorial evidence ID"),
            (self.known_characters, "whole-scope editorial character"),
        ):
            if len(values) != len(set(values)) or any(
                not value or value != value.strip() for value in values
            ):
                raise ValueError(f"{label} values must be unique non-empty strings")
        if not self.evidence_ids:
            raise ValueError("whole-scope editorial subjects require evidence IDs")

    @property
    def identity(self) -> str:
        return f"{self.subject_kind}:{self.subject_id}"

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "membership_hash": self.membership_hash,
            "evidence_ids": list(self.evidence_ids),
            "known_characters": list(self.known_characters),
        }


@dataclass(frozen=True)
class WholeScopeProviderSubject:
    """Transient Stage H/E batch subject; only its identifiers enter durable metadata."""

    stage: WholeScopeSemanticStage
    scope_id: str
    ordered_unit_ids: tuple[str, ...] = ()
    hierarchy_hash: str | None = None
    editorial_subjects: tuple[WholeScopeEditorialSubject, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.stage, WholeScopeSemanticStage):
            raise ValueError("whole-scope provider stage is unsupported")
        if not self.scope_id or self.scope_id != self.scope_id.strip():
            raise ValueError("whole-scope provider scope ID must be non-empty and trimmed")
        if self.stage is WholeScopeSemanticStage.HIERARCHY:
            if (
                not self.ordered_unit_ids
                or self.hierarchy_hash is not None
                or self.editorial_subjects
            ):
                raise ValueError("Stage H requires only ordered authority-bound unit IDs")
            if len(self.ordered_unit_ids) != len(set(self.ordered_unit_ids)):
                raise ValueError("Stage H authority-bound unit IDs must be unique")
        else:
            if self.ordered_unit_ids or not self.hierarchy_hash or not self.editorial_subjects:
                raise ValueError("Stage E requires a hierarchy hash and frozen editorial subjects")
            identities = tuple(item.identity for item in self.editorial_subjects)
            if len(identities) != len(set(identities)):
                raise ValueError("Stage E editorial subject identities must be unique")

    def to_dict(self) -> dict[str, JsonValue]:
        value: dict[str, JsonValue] = {
            "stage": self.stage.value,
            "scope_id": self.scope_id,
        }
        if self.stage is WholeScopeSemanticStage.HIERARCHY:
            value["ordered_unit_ids"] = list(self.ordered_unit_ids)
        else:
            value["hierarchy_hash"] = cast(str, self.hierarchy_hash)
            value["editorial_subjects"] = [
                item.to_dict() for item in self.editorial_subjects
            ]
        return value


@dataclass(frozen=True)
class PreparedNarrativeJob:
    """One exact transient semantic job; ``payload`` must never be persisted."""

    kind: ProviderJobKind
    authority: AuthorityBinding
    subject: (
        BoundaryCandidate
        | NarrativeEvent
        | BoundaryWindow
        | SemanticBeat
        | MajorCluster
        | ChoiceComposition
        | WholeScopeProviderSubject
    )
    subject_id: str
    input_hash: str
    prompt_version: str
    response_schema: str
    payload: dict[str, JsonValue]
    known_evidence_ids: tuple[str, ...]
    known_characters: tuple[str, ...] = ()
    story_facing: bool = True
    source_hash: str | None = None
    correction_id: str | None = None
    membership_hash: str | None = None
    privacy_scope: str | None = None
    logical_job_ids: tuple[str, ...] = ()
    combined_submission_limit: int | None = None

    def __post_init__(self) -> None:
        if not self.subject_id or self.subject_id != self.subject_id.strip():
            raise ValueError("job subject ID must be a non-empty trimmed string")
        if not self.input_hash or not self.prompt_version or not self.response_schema:
            raise ValueError("job input, prompt, and schema identities are required")
        if len(self.known_evidence_ids) != len(set(self.known_evidence_ids)):
            raise ValueError("job evidence IDs must be unique")
        if len(self.known_characters) != len(set(self.known_characters)):
            raise ValueError("job characters must be unique")
        if len(self.logical_job_ids) != len(set(self.logical_job_ids)) or any(
            not value or value != value.strip() for value in self.logical_job_ids
        ):
            raise ValueError("job logical identities must be unique non-empty strings")
        expected_subject = _subject_id(self.subject)
        if self.subject_id != expected_subject:
            raise ValueError("job subject does not match its frozen contract identity")
        for value, label in (
            (self.source_hash, "job source hash"),
            (self.correction_id, "job correction ID"),
            (self.membership_hash, "job membership hash"),
            (self.privacy_scope, "job privacy scope"),
        ):
            if value is not None and (not value or value != value.strip()):
                raise ValueError(f"{label} must be a non-empty trimmed string")
        if self.kind is ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW:
            if not isinstance(self.subject, BoundaryWindow) or self.membership_hash is not None:
                raise ValueError("semantic boundary jobs require a window and no membership hash")
        elif self.kind is ProviderJobKind.SEMANTIC_SUMMARY:
            if not isinstance(self.subject, SemanticBeat | MajorCluster | ChoiceComposition):
                raise ValueError("semantic summary jobs require a frozen visible subject")
            if self.membership_hash is None:
                raise ValueError("semantic summary jobs require frozen membership")
        elif self.kind in {
            ProviderJobKind.WHOLE_SCOPE_HIERARCHY,
            ProviderJobKind.WHOLE_SCOPE_EDITORIAL,
        }:
            expected_stage = (
                WholeScopeSemanticStage.HIERARCHY
                if self.kind is ProviderJobKind.WHOLE_SCOPE_HIERARCHY
                else WholeScopeSemanticStage.EDITORIAL
            )
            if (
                not isinstance(self.subject, WholeScopeProviderSubject)
                or self.subject.stage is not expected_stage
                or not self.logical_job_ids
                or self.combined_submission_limit != MAXIMUM_DAY1_PROVIDER_SUBMISSIONS
            ):
                raise ValueError("whole-scope jobs require exact logical and submission identity")
            if self.kind is ProviderJobKind.WHOLE_SCOPE_HIERARCHY:
                if len(self.logical_job_ids) != 1 or self.membership_hash is not None:
                    raise ValueError("Stage H requires one logical job and no membership hash")
            elif self.membership_hash != self.subject.hierarchy_hash:
                raise ValueError("Stage E requires exact frozen hierarchy membership")
        elif self.logical_job_ids or self.combined_submission_limit is not None:
            raise ValueError("legacy M15 jobs cannot carry whole-scope submission identity")
        self.validate_integrity()

    @property
    def job_id(self) -> str:
        exact_scope: dict[str, JsonValue] = {
            "kind": self.kind.value,
            "authority": self.authority.to_dict(),
            "subject_id": self.subject_id,
            "input_hash": self.input_hash,
            "prompt_version": self.prompt_version,
            "response_schema": self.response_schema,
        }
        if self.source_hash is not None:
            exact_scope["source_hash"] = self.source_hash
        if self.correction_id is not None:
            exact_scope["correction_id"] = self.correction_id
        if self.membership_hash is not None:
            exact_scope["membership_hash"] = self.membership_hash
        if self.privacy_scope is not None:
            exact_scope["privacy_scope"] = self.privacy_scope
        if self.logical_job_ids:
            exact_scope["logical_job_ids"] = list(self.logical_job_ids)
        if self.combined_submission_limit is not None:
            exact_scope["combined_submission_limit"] = self.combined_submission_limit
        return stable_m15_id(
            f"{self.kind.value}_job",
            exact_scope,
        )

    def durable_metadata(self) -> dict[str, JsonValue]:
        """Return identifiers/counts only; source evidence and prompt content are omitted."""

        metadata: dict[str, JsonValue] = {
            "job_id": self.job_id,
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "authority": self.authority.to_dict(),
            "input_hash": self.input_hash,
            "prompt_version": self.prompt_version,
            "response_schema": self.response_schema,
            "known_evidence_ids": list(self.known_evidence_ids),
            "known_characters": list(self.known_characters),
            "story_facing": self.story_facing,
        }
        if self.source_hash is not None:
            metadata["source_hash"] = self.source_hash
        if self.correction_id is not None:
            metadata["correction_id"] = self.correction_id
        if self.membership_hash is not None:
            metadata["membership_hash"] = self.membership_hash
        if self.privacy_scope is not None:
            metadata["privacy_scope"] = self.privacy_scope
        if self.logical_job_ids:
            metadata["logical_job_ids"] = list(self.logical_job_ids)
        if self.combined_submission_limit is not None:
            metadata["combined_submission_limit"] = self.combined_submission_limit
        return metadata

    def validate_integrity(self) -> None:
        if canonical_hash(self.payload) != self.input_hash:
            raise ValueError("prepared M15 input hash does not match its provider payload")


@dataclass(frozen=True)
class NarrativeConsentManifest:
    """Fresh, granted consent bound to exact jobs, provider identity, and transport limits."""

    run_id: str
    profile: ProviderProfile
    job_ids: tuple[str, ...]
    job_identity_hashes: tuple[str, ...]
    job_identity_hash: str
    issued_utc: str
    expires_utc: str
    maximum_provider_calls: int
    maximum_input_bytes: int
    maximum_output_bytes: int
    timeout_seconds: float
    consent_granted: bool = False
    repair_policy_version: str | None = None
    version: str = "m15-narrative-consent-v1"
    _call_ledger: _ConsentCallLedger = field(
        default_factory=_ConsentCallLedger,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.run_id or self.run_id != self.run_id.strip():
            raise ValueError("consent run ID must be a non-empty trimmed string")
        if not self.job_ids or len(self.job_ids) != len(set(self.job_ids)):
            raise ValueError("consent scope requires unique M15 jobs")
        if len(self.job_identity_hashes) != len(self.job_ids):
            raise ValueError("consent job identities must cover the exact scope")
        transport_limits = (
            self.maximum_provider_calls,
            self.maximum_input_bytes,
            self.maximum_output_bytes,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in transport_limits
        ):
            raise ValueError("consent transport limits must be positive")
        if self.maximum_input_bytes > MAXIMUM_INPUT_BYTES:
            raise ValueError("consent input limit exceeds the sterile boundary")
        if self.maximum_output_bytes > MAXIMUM_OUTPUT_BYTES:
            raise ValueError("consent output limit exceeds the sterile boundary")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("consent timeout must be positive")
        if (
            self.repair_policy_version is None
            and self.version != "m15-narrative-consent-v1"
        ) or (
            self.repair_policy_version is not None
            and (
                not self.repair_policy_version
                or self.repair_policy_version != self.repair_policy_version.strip()
                or self.version != "m15-narrative-consent-v2"
            )
        ):
            raise ValueError("consent repair policy identity is invalid")
        _consent_times(self.issued_utc, self.expires_utc)

    @classmethod
    def for_jobs(
        cls,
        *,
        run_id: str,
        profile: ProviderProfile,
        jobs: Sequence[PreparedNarrativeJob],
        consent_granted: bool = False,
        valid_for: timedelta = timedelta(minutes=15),
        maximum_provider_calls: int | None = None,
        maximum_input_bytes: int = MAXIMUM_INPUT_BYTES,
        maximum_output_bytes: int = MAXIMUM_OUTPUT_BYTES,
        timeout_seconds: float = 300.0,
    ) -> NarrativeConsentManifest:
        if not jobs:
            raise ValueError("consent scope requires at least one M15 job")
        if valid_for <= timedelta(0) or valid_for > timedelta(hours=1):
            raise ValueError("consent freshness window must be between zero and one hour")
        for job in jobs:
            job.validate_integrity()
        issued = datetime.now(UTC)
        repair_policy_version = _repair_policy_version(jobs)
        return cls(
            run_id=run_id,
            profile=profile,
            job_ids=tuple(job.job_id for job in jobs),
            job_identity_hashes=tuple(
                canonical_hash(job.durable_metadata()) for job in jobs
            ),
            job_identity_hash=_job_identity_hash(jobs),
            issued_utc=issued.isoformat(),
            expires_utc=(issued + valid_for).isoformat(),
            maximum_provider_calls=(
                maximum_provider_calls
                if maximum_provider_calls is not None
                else 2 * len(jobs)
            ),
            maximum_input_bytes=maximum_input_bytes,
            maximum_output_bytes=maximum_output_bytes,
            timeout_seconds=timeout_seconds,
            consent_granted=consent_granted,
            repair_policy_version=repair_policy_version,
            version=(
                "m15-narrative-consent-v2"
                if repair_policy_version is not None
                else "m15-narrative-consent-v1"
            ),
        )

    @property
    def manifest_id(self) -> str:
        return stable_m15_id("consent", self.identity_dict())

    def identity_dict(self) -> dict[str, JsonValue]:
        identity: dict[str, JsonValue] = {
            "version": self.version,
            "run_id": self.run_id,
            "profile": self.profile.to_dict(),
            "job_ids": list(self.job_ids),
            "job_identity_hashes": list(self.job_identity_hashes),
            "job_identity_hash": self.job_identity_hash,
            "issued_utc": self.issued_utc,
            "expires_utc": self.expires_utc,
            "maximum_provider_calls": self.maximum_provider_calls,
            "maximum_input_bytes": self.maximum_input_bytes,
            "maximum_output_bytes": self.maximum_output_bytes,
            "timeout_seconds": self.timeout_seconds,
        }
        if self.repair_policy_version is not None:
            identity["repair_policy_version"] = self.repair_policy_version
        return identity

    def validate_for(
        self,
        jobs: Sequence[PreparedNarrativeJob],
        profile: ProviderProfile,
    ) -> None:
        if not self.consent_granted:
            raise ValueError("M15 provider transmission requires granted consent")
        self.validate_fresh()
        if canonical_hash(self.profile.to_dict()) != canonical_hash(profile.to_dict()):
            raise ValueError("M15 consent provider profile does not match")
        if tuple(job.job_id for job in jobs) != self.job_ids:
            raise ValueError("M15 consent scope does not match the scheduled jobs")
        for job in jobs:
            job.validate_integrity()
        if _job_identity_hash(jobs) != self.job_identity_hash:
            raise ValueError("M15 consent input identity does not match")
        if self.repair_policy_version != _repair_policy_version(jobs):
            raise ValueError("M15 consent repair policy identity does not match")

    def validate_job(self, job: PreparedNarrativeJob, profile: ProviderProfile) -> None:
        if not self.consent_granted:
            raise ValueError("M15 provider transmission requires granted consent")
        self.validate_fresh()
        if canonical_hash(self.profile.to_dict()) != canonical_hash(profile.to_dict()):
            raise ValueError("M15 consent provider profile does not match")
        job.validate_integrity()
        try:
            index = self.job_ids.index(job.job_id)
        except ValueError:
            raise ValueError("M15 consent scope does not include the provider job") from None
        if canonical_hash(job.durable_metadata()) != self.job_identity_hashes[index]:
            raise ValueError("M15 consent job identity does not match")
        if self.repair_policy_version != _repair_policy_version((job,)):
            raise ValueError("M15 consent repair policy identity does not match")

    def validate_fresh(self) -> None:
        issued, expires = _consent_times(self.issued_utc, self.expires_utc)
        now = datetime.now(UTC)
        if issued > now + timedelta(minutes=1) or now >= expires:
            raise ValueError("M15 provider consent is not fresh")

    def reserve_provider_call(
        self,
        job: PreparedNarrativeJob,
        profile: ProviderProfile,
    ) -> None:
        """Atomically consume one call grant immediately before transmission."""

        self._call_ledger.reserve(self, job, profile)


@dataclass(frozen=True)
class NarrativeMapProviderRequest:
    request_id: str
    consent: NarrativeConsentManifest
    profile: ProviderProfile
    job: PreparedNarrativeJob
    repair_codes: tuple[str, ...] = ()
    repair_semantics: Mapping[str, JsonValue] | None = None
    timeout_seconds: float = 300.0
    maximum_input_bytes: int = MAXIMUM_INPUT_BYTES
    maximum_output_bytes: int = MAXIMUM_OUTPUT_BYTES

    def __post_init__(self) -> None:
        for value, label in (
            (self.request_id, "provider request ID"),
        ):
            if not value or value != value.strip():
                raise ValueError(f"{label} must be a non-empty trimmed string")
        if len(self.repair_codes) != len(set(self.repair_codes)):
            raise ValueError("repair codes must be unique")
        if bool(self.repair_codes) != (self.repair_semantics is not None):
            raise ValueError("schema repair metadata must be supplied together")
        self.validate_for_submission()

    def validate_for_submission(self) -> None:
        if (
            not isinstance(self.timeout_seconds, int | float)
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(float(self.timeout_seconds))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("provider timeout bound must be finite and positive")
        for value, label in (
            (self.maximum_input_bytes, "input"),
            (self.maximum_output_bytes, "output"),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"provider {label} bound must be a positive integer")
        if self.maximum_input_bytes > self.consent.maximum_input_bytes:
            raise ValueError("provider input bound exceeds consent")
        if self.maximum_output_bytes > self.consent.maximum_output_bytes:
            raise ValueError("provider output bound exceeds consent")
        if self.timeout_seconds > self.consent.timeout_seconds:
            raise ValueError("provider timeout bound exceeds consent")
        self.consent.validate_job(self.job, self.profile)

    @property
    def consent_manifest_id(self) -> str:
        return self.consent.manifest_id


@dataclass(frozen=True)
class NarrativeMapProviderResponse:
    request_id: str
    provider: ProviderIdentity
    payload: dict[str, object]
    usage: ProviderUsage


class NarrativeMapProvider(Protocol):
    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: CancelledCallback,
    ) -> NarrativeMapProviderResponse: ...

    def cancel(self) -> None: ...


class StructuredRunner(Protocol):
    def execute(
        self,
        request: SterileRunRequest,
        cancelled: CancelledCallback,
    ) -> SterileRunResult: ...

    def cancel(self) -> None: ...


class NarrativeMapProviderError(RuntimeError):
    """A sanitized failure code; callers persist the code and never the message."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        transient: bool = False,
        provider_call_reserved: bool = True,
    ) -> None:
        if _ERROR_CODE.fullmatch(error_code) is None:
            raise ValueError("provider error codes must be sanitized identifiers")
        super().__init__(message)
        self.error_code = error_code
        self.transient = transient
        self.provider_call_reserved = provider_call_reserved


class SterileNarrativeMapProvider:
    """M15 semantics over the existing shell-free sterile Codex process runner."""

    def __init__(
        self,
        *,
        runner: StructuredRunner | None = None,
        executable: str = "codex",
    ) -> None:
        self._runner = runner or SterileCodexRunner(executable=executable)

    def cancel(self) -> None:
        self._runner.cancel()

    def submit(
        self,
        request: NarrativeMapProviderRequest,
        cancelled: CancelledCallback,
    ) -> NarrativeMapProviderResponse:
        if cancelled():
            raise NarrativeMapProviderError(
                "cancelled",
                "The provider request was cancelled.",
                provider_call_reserved=False,
            )
        try:
            request.validate_for_submission()
            prompt_name, schema_name = _resource_names(request.job)
            prompt = _serialize_prompt(request, prompt_name)
        except NarrativeMapProviderError:
            raise
        except Exception:
            raise NarrativeMapProviderError(
                "provider_request_invalid",
                "The provider request failed local validation.",
                provider_call_reserved=False,
            ) from None
        if len(prompt) > request.maximum_input_bytes:
            raise NarrativeMapProviderError(
                "input_limit",
                "The provider request is too large.",
                provider_call_reserved=False,
            )
        schema_resource = files("renpy_story_mapper.narrative_map.schemas").joinpath(schema_name)
        reasoning = request.profile.settings.to_dict().get("reasoning_effort")
        if reasoning is not None and not isinstance(reasoning, str):
            raise NarrativeMapProviderError(
                "runtime_configuration_rejected",
                "The reasoning profile is invalid.",
                provider_call_reserved=False,
            )
        provider_call_reserved = False
        try:
            with as_file(schema_resource) as schema_path:
                sterile_request = SterileRunRequest(
                    model=request.profile.requested_model,
                    schema_path=schema_path,
                    stdin=prompt,
                    timeout_seconds=request.timeout_seconds,
                    maximum_output_bytes=request.maximum_output_bytes,
                    model_reasoning_effort=reasoning,
                )
                if cancelled():
                    raise NarrativeMapProviderError(
                        "cancelled",
                        "The provider request was cancelled.",
                        provider_call_reserved=False,
                    )
                request.consent.reserve_provider_call(request.job, request.profile)
                provider_call_reserved = True
                started_at = time.monotonic()
                result = self._runner.execute(
                    sterile_request,
                    cancelled,
                )
        except SterileRunnerError as exc:
            raise NarrativeMapProviderError(
                exc.error_code,
                "The sterile provider process failed safely.",
                transient=exc.transient,
            ) from None
        except NarrativeMapProviderError:
            raise
        except Exception:
            if provider_call_reserved:
                raise
            raise NarrativeMapProviderError(
                "provider_request_invalid",
                "The provider request could not cross the sterile boundary.",
                provider_call_reserved=False,
            ) from None
        payload = _extract_payload(result)
        resolved_model = _resolved_model(result, request.profile.requested_model)
        if resolved_model != request.profile.requested_model:
            raise NarrativeMapProviderError(
                "model_mismatch", "The provider resolved a different model."
            )
        input_tokens, output_tokens, cost_micros = _usage(result)
        elapsed_ms = round((time.monotonic() - started_at) * 1000)
        return NarrativeMapProviderResponse(
            request_id=request.request_id,
            provider=ProviderIdentity(
                provider=request.profile.provider,
                adapter=request.profile.adapter,
                adapter_version=request.profile.adapter_version,
                requested_model=request.profile.requested_model,
                resolved_model=resolved_model,
                settings=request.profile.settings,
            ),
            payload=payload,
            usage=ProviderUsage(
                input_tokens,
                output_tokens,
                elapsed_ms,
                cost_micros=cost_micros,
            ),
        )


def _resource_names(job: PreparedNarrativeJob) -> tuple[str, str]:
    resources = {
        ProviderJobKind.BOUNDARY: (
            BOUNDARY_RESPONSE_SCHEMA,
            "boundary_decision_v1.json",
            "boundary_decision_v2.schema.json",
        ),
        ProviderJobKind.EVENT_SUMMARY: (
            SUMMARY_RESPONSE_SCHEMA,
            "event_summary_v1.json",
            "event_summary_v2.schema.json",
        ),
        ProviderJobKind.SEMANTIC_BOUNDARY_WINDOW: (
            SEMANTIC_BOUNDARY_RESPONSE_SCHEMA,
            "semantic_boundary_v3.json",
            "boundary_window_v3.schema.json",
        ),
        ProviderJobKind.SEMANTIC_SUMMARY: (
            SEMANTIC_SUMMARY_RESPONSE_SCHEMA,
            "semantic_summary_v3.json",
            "semantic_summary_v3.schema.json",
        ),
        ProviderJobKind.WHOLE_SCOPE_HIERARCHY: (
            WHOLE_SCOPE_HIERARCHY_RESPONSE_SCHEMA,
            "whole_scope_hierarchy_v4.json",
            "whole_scope_hierarchy_v2.schema.json",
        ),
        ProviderJobKind.WHOLE_SCOPE_EDITORIAL: (
            WHOLE_SCOPE_EDITORIAL_RESPONSE_SCHEMA,
            "whole_scope_editorial_v1.json",
            "whole_scope_editorial_v1.schema.json",
        ),
    }
    response_schema, prompt_name, schema_name = resources[job.kind]
    if job.response_schema != response_schema:
        raise ValueError("M15 provider response schema identity is stale")
    return prompt_name, schema_name


def _subject_id(
    subject: (
        BoundaryCandidate
        | NarrativeEvent
        | BoundaryWindow
        | SemanticBeat
        | MajorCluster
        | ChoiceComposition
        | WholeScopeProviderSubject
    ),
) -> str:
    if isinstance(subject, BoundaryCandidate):
        return subject.candidate_id
    if isinstance(subject, NarrativeEvent):
        return subject.event_id
    if isinstance(subject, BoundaryWindow):
        return subject.window_id
    if isinstance(subject, WholeScopeProviderSubject):
        return subject.scope_id
    if isinstance(subject, SemanticBeat):
        return subject.beat_id
    if isinstance(subject, MajorCluster):
        return subject.cluster_id
    return subject.choice_id


def _serialize_prompt(request: NarrativeMapProviderRequest, resource_name: str) -> bytes:
    resource = files("renpy_story_mapper.narrative_map.prompts").joinpath(resource_name)
    try:
        template = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise NarrativeMapProviderError(
            "prompt_template_invalid",
            "The M15 prompt template is unavailable.",
            provider_call_reserved=False,
        ) from None
    if not isinstance(template, dict) or template.get("version") != request.job.prompt_version:
        raise NarrativeMapProviderError(
            "prompt_version_mismatch",
            "The M15 prompt identity does not match.",
            provider_call_reserved=False,
        )
    envelope = {
        **template,
        "request": {
            "request_id": request.request_id,
            "consent_manifest_id": request.consent_manifest_id,
            "job_id": request.job.job_id,
            "input_hash": request.job.input_hash,
            "response_schema": request.job.response_schema,
            "schema_only_repair": bool(request.repair_codes),
            "repair_codes": list(request.repair_codes),
            "locked_semantics": request.repair_semantics,
            "job": request.job.payload,
        },
    }
    if request.repair_codes and request.job.kind in {
        ProviderJobKind.SEMANTIC_SUMMARY,
        ProviderJobKind.WHOLE_SCOPE_HIERARCHY,
        ProviderJobKind.WHOLE_SCOPE_EDITORIAL,
    }:
        expected_policy = (
            SEMANTIC_REPAIR_POLICY_VERSION
            if request.job.kind is ProviderJobKind.SEMANTIC_SUMMARY
            else WHOLE_SCOPE_REPAIR_POLICY_VERSION
        )
        if request.consent.repair_policy_version != expected_policy:
            raise NarrativeMapProviderError(
                "repair_policy_mismatch",
                "The M15 repair policy is not bound to the exact consent.",
                provider_call_reserved=False,
            )
        envelope["request"]["repair_guidance_version"] = expected_policy
        if request.job.kind is ProviderJobKind.SEMANTIC_SUMMARY:
            envelope["request"]["locked_semantics_policy"] = (
                "Copy every scalar and claim slot in request.locked_semantics exactly. Change only "
                "fields identified by request.repair_codes as described in request.repair_guidance."
            )
            envelope["request"]["repair_guidance"] = [
                _SEMANTIC_REPAIR_GUIDANCE[code]
                for code in request.repair_codes
                if code in _SEMANTIC_REPAIR_GUIDANCE
            ]
        else:
            envelope["request"]["locked_semantics_policy"] = (
                "Copy request.locked_semantics.scope_id and hierarchy_hash exactly when present. "
                "For Stage H, copy every object in __whole_scope_beat_groups__ byte-for-byte into "
                "beat_groups exactly once with the same proposal_key, and copy every object in "
                "__whole_scope_clusters__ byte-for-byte into major_clusters exactly once with the "
                "same proposal_key. For Stage E, copy each entry's item value from "
                "__whole_scope_records__ byte-for-byte into records exactly once with the same "
                "subject_kind and subject_id; do not copy the identity/item wrapper. Do not return "
                "the internal lock keys. Add or replace "
                "only entries absent from these lock collections as required by repair_codes."
            )
            envelope["request"]["repair_guidance"] = [
                "Return the complete exact stage envelope. Preserve every valid locked item "
                "byte-for-byte and repair only missing or invalid entries."
            ]
            envelope["request"]["repair_guidance"].extend(
                _WHOLE_SCOPE_REPAIR_GUIDANCE[code]
                for code in request.repair_codes
                if code in _WHOLE_SCOPE_REPAIR_GUIDANCE
            )
    return json.dumps(
        envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _repair_policy_version(
    jobs: Sequence[PreparedNarrativeJob],
) -> str | None:
    semantic_summary = tuple(
        job.kind is ProviderJobKind.SEMANTIC_SUMMARY for job in jobs
    )
    whole_scope = tuple(
        job.kind
        in {
            ProviderJobKind.WHOLE_SCOPE_HIERARCHY,
            ProviderJobKind.WHOLE_SCOPE_EDITORIAL,
        }
        for job in jobs
    )
    if (any(semantic_summary) and not all(semantic_summary)) or (
        any(whole_scope) and not all(whole_scope)
    ):
        raise ValueError("M15 repair-policy consent cannot mix job kinds")
    if any(semantic_summary):
        return SEMANTIC_REPAIR_POLICY_VERSION
    if any(whole_scope):
        if len({job.kind for job in jobs}) != 1:
            raise ValueError("whole-scope consent cannot mix Stage H and Stage E")
        return WHOLE_SCOPE_REPAIR_POLICY_VERSION
    return None


def _extract_payload(result: SterileRunResult) -> dict[str, object]:
    payloads: list[dict[str, object]] = []
    for event in result.events:
        if not isinstance(event, Mapping):
            continue
        item = event.get("item")
        if isinstance(item, Mapping) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str):
                try:
                    decoded = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    payloads.append(cast(dict[str, object], decoded))
        response = event.get("response")
        if isinstance(response, dict):
            payloads.append(cast(dict[str, object], response))
    if len(payloads) != 1:
        raise NarrativeMapProviderError(
            "response_envelope_invalid", "The provider returned no unique structured result."
        )
    return payloads[0]


def _resolved_model(result: SterileRunResult, requested_model: str) -> str:
    models = {
        value
        for event in result.events
        if isinstance(event, Mapping)
        for value in (event.get("model"),)
        if isinstance(value, str)
    }
    if not models:
        return requested_model
    if len(models) != 1:
        raise NarrativeMapProviderError(
            "model_metadata_conflict", "The provider returned conflicting model identities."
        )
    return next(iter(models))


def _usage(result: SterileRunResult) -> tuple[int, int, int | None]:
    latest: Mapping[object, object] | None = None
    for event in result.events:
        if isinstance(event, Mapping) and isinstance(event.get("usage"), Mapping):
            latest = cast(Mapping[object, object], event["usage"])
    if latest is None:
        raise NarrativeMapProviderError("usage_metadata_missing", "Provider usage is missing.")
    input_tokens = latest.get("input_tokens")
    output_tokens = latest.get("output_tokens")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in (input_tokens, output_tokens)
    ):
        raise NarrativeMapProviderError("usage_metadata_invalid", "Provider usage is invalid.")
    cost = latest.get("cost_micros")
    if cost is not None and (
        not isinstance(cost, int) or isinstance(cost, bool) or cost < 0
    ):
        raise NarrativeMapProviderError("usage_metadata_invalid", "Provider cost is invalid.")
    return cast(int, input_tokens), cast(int, output_tokens), cost


def _job_identity_hash(jobs: Sequence[PreparedNarrativeJob]) -> str:
    return canonical_hash([job.durable_metadata() for job in jobs])


def _consent_times(issued_value: str, expires_value: str) -> tuple[datetime, datetime]:
    try:
        issued = datetime.fromisoformat(issued_value)
        expires = datetime.fromisoformat(expires_value)
    except ValueError:
        raise ValueError("consent timestamps must be ISO-8601 values") from None
    if issued.tzinfo is None or expires.tzinfo is None:
        raise ValueError("consent timestamps must be timezone-aware")
    issued = issued.astimezone(UTC)
    expires = expires.astimezone(UTC)
    if expires <= issued or expires - issued > timedelta(hours=1):
        raise ValueError("consent freshness window is invalid")
    return issued, expires
