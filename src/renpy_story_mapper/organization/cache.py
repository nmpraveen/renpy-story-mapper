"""Content-addressed cache contracts; persistence belongs to the story model worker."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from renpy_story_mapper.organization.contracts import CodexMode, OrganizationRequest


@dataclass(frozen=True)
class OrganizationCacheKey:
    provider_mode: CodexMode
    model_profile: str
    model_fingerprint: str
    prompt_version: str
    schema_version: str
    input_hash: str

    def digest(self) -> str:
        fields = {
            "provider_mode": self.provider_mode.value,
            "model_profile": self.model_profile,
            "model_fingerprint": self.model_fingerprint,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "input_hash": self.input_hash,
        }
        return hashlib.sha256(
            json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


def build_cache_key(
    request: OrganizationRequest,
    *,
    provider_mode: CodexMode,
    model_profile: str,
    model_fingerprint: str,
    prompt_version: str,
    schema_version: str,
) -> OrganizationCacheKey:
    """Hash payload plus exact ordered/context IDs before querying persistent cache."""
    material = {
        "stage": request.stage.value,
        "scope_id": request.scope_id,
        "payload": request.payload,
        "ordered_member_ids": request.constraints.ordered_member_ids,
        "required_member_ids": sorted(request.constraints.required_member_ids),
        "context_member_ids": sorted(request.constraints.context_member_ids),
        "fact_ids": sorted(request.constraints.fact_ids),
        "evidence_ids": sorted(request.constraints.evidence_ids),
        "character_names": sorted(request.constraints.character_names),
    }
    input_hash = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return OrganizationCacheKey(
        provider_mode=provider_mode,
        model_profile=model_profile,
        model_fingerprint=model_fingerprint,
        prompt_version=prompt_version,
        schema_version=schema_version,
        input_hash=input_hash,
    )
