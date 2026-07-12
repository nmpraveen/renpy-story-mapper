/**
 * Frontend contract for the loopback API. JavaScript never derives story authority.
 * Backend responses own node membership, ordering, edges, facts, and evidence locations.
 * Native pickers return opaque `selection_id` values; browser clients never submit paths.
 */
export const API_VERSION = "v1";
export const RENDER_LIMITS = Object.freeze({ nodes: 80, edges: 120, items: 240 });

export const ENDPOINTS = Object.freeze({
  bootstrap: "/api/v1/bootstrap",
  recent: "/api/v1/recent",
  nativePicker: "/api/v1/native-picker",
  projectsOpen: "/api/v1/projects/open",
  projectsCreate: "/api/v1/projects/create",
  projectsRefresh: "/api/v1/projects/refresh",
  analysisProgress: "/api/v1/analysis/progress",
  analysisCancel: "/api/v1/analysis/cancel",
  storyView: "/api/v1/story/view",
  storySearch: "/api/v1/story/search",
  storyEvidence: "/api/v1/story/evidence",
  storyFacts: "/api/v1/story/facts",
  settings: "/api/v1/settings",
  organizationConsent: "/api/v1/organization/consent",
  organizationDraft: "/api/v1/organization/draft",
  organizationApply: "/api/v1/organization/apply",
  organizationDiscard: "/api/v1/organization/discard",
  diagnostics: "/api/v1/diagnostics",
});

export const LEVEL_NUMBER = Object.freeze({ arcs: 1, events: 2, evidence: 3 });

export function assertBoundedView(view) {
  if (!view || !Array.isArray(view.nodes) || !Array.isArray(view.edges)) {
    throw new TypeError("Invalid story view response");
  }
  const items = view.nodes.length + view.edges.length;
  if (view.nodes.length > RENDER_LIMITS.nodes || view.edges.length > RENDER_LIMITS.edges || items > RENDER_LIMITS.items) {
    throw new RangeError("Story view exceeds the packaged rendering boundary");
  }
  return view;
}

export function safeLevel(value) {
  return value === "events" || value === "evidence" ? value : "arcs";
}
