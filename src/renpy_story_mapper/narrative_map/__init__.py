"""M15 deterministic Narrative Map contracts.

The package is intentionally independent from the legacy M07/M08 AI page and M11 scene
membership.  Track implementations build on the versioned records exported here.
"""

from renpy_story_mapper.narrative_map.assembly import assemble_narrative_events
from renpy_story_mapper.narrative_map.contracts import (
    M15_BOUNDARY_SCHEMA,
    M15_CORRIDOR_SCHEMA,
    M15_EVENT_SCHEMA,
    M15_MAP_SCHEMA,
    M15_TECHNICAL_CORRECTION_RULE_VERSION,
    M15_TECHNICAL_CORRECTION_SCHEMA,
    AuthorityBinding,
    BoundaryCandidate,
    BoundaryDecision,
    BoundaryDecisionKind,
    BoundaryProviderIdentity,
    BoundarySignal,
    CoverageState,
    EvidenceNavigation,
    LeadingTechnicalCoverageCorrection,
    NarrativeCorridor,
    NarrativeEdgeKind,
    NarrativeEvent,
    NarrativeMap,
    NarrativeMapEdge,
    NarrativeMapNode,
    NarrativeNodeKind,
    Provenance,
    SourceLocator,
    stable_m15_id,
)
from renpy_story_mapper.narrative_map.corridors import (
    build_boundary_candidates,
    build_narrative_corridors,
    create_leading_technical_coverage_correction,
    resolve_leading_technical_coverage_correction,
)
from renpy_story_mapper.narrative_map.persistence import NarrativeMapRepository
from renpy_story_mapper.narrative_map.projection import build_narrative_map
from renpy_story_mapper.narrative_map.provider import NarrativeConsentManifest
from renpy_story_mapper.narrative_map.service import NarrativeMapService
from renpy_story_mapper.narrative_map.validation import (
    validate_boundary_response,
    validate_event_summary_response,
)
from renpy_story_mapper.narrative_map.workflow import NarrativeBoundaryWorkflow

__all__ = [
    "M15_BOUNDARY_SCHEMA",
    "M15_CORRIDOR_SCHEMA",
    "M15_EVENT_SCHEMA",
    "M15_MAP_SCHEMA",
    "M15_TECHNICAL_CORRECTION_RULE_VERSION",
    "M15_TECHNICAL_CORRECTION_SCHEMA",
    "AuthorityBinding",
    "BoundaryCandidate",
    "BoundaryDecision",
    "BoundaryDecisionKind",
    "BoundaryProviderIdentity",
    "BoundarySignal",
    "CoverageState",
    "EvidenceNavigation",
    "LeadingTechnicalCoverageCorrection",
    "NarrativeBoundaryWorkflow",
    "NarrativeConsentManifest",
    "NarrativeCorridor",
    "NarrativeEdgeKind",
    "NarrativeEvent",
    "NarrativeMap",
    "NarrativeMapEdge",
    "NarrativeMapNode",
    "NarrativeMapRepository",
    "NarrativeMapService",
    "NarrativeNodeKind",
    "Provenance",
    "SourceLocator",
    "assemble_narrative_events",
    "build_boundary_candidates",
    "build_narrative_corridors",
    "build_narrative_map",
    "create_leading_technical_coverage_correction",
    "resolve_leading_technical_coverage_correction",
    "stable_m15_id",
    "validate_boundary_response",
    "validate_event_summary_response",
]
