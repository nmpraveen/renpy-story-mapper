/**
 * Frontend contract for the loopback API. JavaScript never derives story authority.
 * Backend responses own node membership, ordering, edges, facts, and evidence locations.
 * Native pickers return opaque `selection_id` values; browser clients never submit paths.
 */
export const API_VERSION = "v1";
export const RENDER_LIMITS = Object.freeze({ nodes: 80, edges: 120, items: 240 });

export const ENDPOINTS = Object.freeze({
  state: "/api/v1/state",
  tasksCurrent: "/api/v1/tasks/current",
  dialogSource: "/api/v1/dialog/source",
  dialogProjectOpen: "/api/v1/dialog/project/open",
  dialogProjectSave: "/api/v1/dialog/project/save",
  projectsOpen: "/api/v1/projects/open",
  projectsCreate: "/api/v1/projects/create",
  projectsRefresh: "/api/v1/projects/refresh",
  tasksCancel: "/api/v1/tasks/cancel",
  presentationView: "/api/v1/presentation/view",
  presentationSearch: "/api/v1/presentation/search",
  presentationEvidence: "/api/v1/presentation/evidence",
  presentationFacts: "/api/v1/presentation/facts",
  settings: "/api/v1/settings",
  organization: "/api/v1/organization",
  organizationStart: "/api/v1/organization/start",
  organizationApply: "/api/v1/organization/drafts/apply",
  organizationDiscard: "/api/v1/organization/drafts/discard",
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
