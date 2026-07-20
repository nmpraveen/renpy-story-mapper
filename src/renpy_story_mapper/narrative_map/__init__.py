"""M15 deterministic Narrative Map contracts.

The package is intentionally independent from the legacy M07/M08 AI page and M11 scene
membership.  Track implementations build on the versioned records exported here.
"""

from renpy_story_mapper.narrative_map.contracts import (
    M15_BOUNDARY_SCHEMA,
    M15_CORRIDOR_SCHEMA,
    M15_EVENT_SCHEMA,
    M15_MAP_SCHEMA,
    AuthorityBinding,
    BoundaryCandidate,
    BoundaryDecision,
    BoundaryDecisionKind,
    BoundaryProviderIdentity,
    BoundarySignal,
    CoverageState,
    EvidenceNavigation,
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

__all__ = [
    "M15_BOUNDARY_SCHEMA",
    "M15_CORRIDOR_SCHEMA",
    "M15_EVENT_SCHEMA",
    "M15_MAP_SCHEMA",
    "AuthorityBinding",
    "BoundaryCandidate",
    "BoundaryDecision",
    "BoundaryDecisionKind",
    "BoundaryProviderIdentity",
    "BoundarySignal",
    "CoverageState",
    "EvidenceNavigation",
    "NarrativeCorridor",
    "NarrativeEdgeKind",
    "NarrativeEvent",
    "NarrativeMap",
    "NarrativeMapEdge",
    "NarrativeMapNode",
    "NarrativeNodeKind",
    "Provenance",
    "SourceLocator",
    "stable_m15_id",
]

