/** Packaged loopback API and rendering safety contract. */
export const API_VERSION = "v1";
export const ROUTE_PAGE_SIZE = 30;
export const RENDER_LIMITS = Object.freeze({ nodes: 30, edges: 180, items: 240 });

export const ENDPOINTS = Object.freeze({
  bootstrap: "/api/v1/bootstrap",
  nativePicker: "/api/v1/native-picker",
  projectsOpen: "/api/v1/projects/open",
  projectsCreate: "/api/v1/projects/create",
  projectsRefresh: "/api/v1/projects/refresh",
  analysisProgress: "/api/v1/analysis/progress",
  analysisCancel: "/api/v1/analysis/cancel",
  settings: "/api/v1/settings",
  diagnostics: "/api/v1/diagnostics",
  shutdown: "/api/v1/shutdown",
  routeMap: "/api/v1/m07/route-map",
  routeDetail: "/api/v1/m07/detail",
  organization: "/api/v1/m07/organization",
  organizationPrepare: "/api/v1/m07/organization/prepare",
  organizationStart: "/api/v1/m07/organization/start",
  organizationCancel: "/api/v1/m07/organization/cancel",
  assemblyApply: "/api/v1/m07/assembly/apply",
});

const object = (value) => value && typeof value === "object" && !Array.isArray(value);

export function assertRoutePage(page) {
  if (!object(page) || !Array.isArray(page.nodes) || !Array.isArray(page.edges)) {
    throw new TypeError("Invalid Route Map response");
  }
  const nodes = page.nodes.length;
  const edges = page.edges.length;
  if (nodes > RENDER_LIMITS.nodes || edges > RENDER_LIMITS.edges || nodes + edges > RENDER_LIMITS.items) {
    throw new RangeError("Route Map exceeds the packaged rendering boundary");
  }
  if (page.level && page.level !== "route_map") throw new TypeError("Unexpected semantic level");
  return page;
}

export function assertDetail(detail) {
  if (!object(detail) || !object(detail.element) || !Array.isArray(detail.evidence)) {
    throw new TypeError("Invalid Detail/Evidence response");
  }
  if (detail.level && detail.level !== "detail_evidence") throw new TypeError("Unexpected semantic level");
  return detail;
}

export function assertOrganization(value) {
  if (!object(value)) throw new TypeError("Invalid organization response");
  return value;
}
