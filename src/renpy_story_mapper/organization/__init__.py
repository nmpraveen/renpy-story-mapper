"""Secure, provider-neutral story organization contracts."""

from renpy_story_mapper.organization.cache import OrganizationCacheKey, build_cache_key
from renpy_story_mapper.organization.chunking import build_event_chunks
from renpy_story_mapper.organization.contracts import (
    BeatRecord,
    CodexMode,
    FactRecord,
    OrganizationChunkResult,
    OrganizationProvider,
    OrganizationRequest,
    OrganizationStage,
    ProviderExecutionMetadata,
    ProviderStatus,
)
from renpy_story_mapper.organization.provider import CodexCliProvider
from renpy_story_mapper.organization.validation import validate_result

__all__ = [
    "BeatRecord",
    "CodexCliProvider",
    "CodexMode",
    "FactRecord",
    "OrganizationCacheKey",
    "OrganizationChunkResult",
    "OrganizationProvider",
    "OrganizationRequest",
    "OrganizationStage",
    "ProviderExecutionMetadata",
    "ProviderStatus",
    "build_cache_key",
    "build_event_chunks",
    "validate_result",
]
