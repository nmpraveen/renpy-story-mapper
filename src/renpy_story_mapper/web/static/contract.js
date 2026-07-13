/** Packaged loopback API and rendering safety contract. */
export const API_VERSION = "v1";
export const ROUTE_PAGE_SIZE = 30;
export const ROUTE_EDGE_PAGE_SIZE = 180;
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
  boundedWindowResolve: "/api/v1/m07/bounded-window/resolve",
  organization: "/api/v1/m07/organization",
  organizationPrepare: "/api/v1/m07/organization/prepare",
  organizationStart: "/api/v1/m07/organization/start",
  organizationCancel: "/api/v1/m07/organization/cancel",
  assemblyApply: "/api/v1/m07/assembly/apply",
  assemblyDiscard: "/api/v1/m07/assembly/discard",
  aiStoryMap: "/api/v1/m08/ai-story-map",
  aiStoryDetail: "/api/v1/m08/ai-story-detail",
  mapComparison: "/api/v1/m08/comparison",
});

const object = (value) => value && typeof value === "object" && !Array.isArray(value);
const WINDOW_KEYS = ["schema_version", "id", "selection_kind", "entry_node_id", "exit_node_id", "node_ids", "internal_edge_ids", "boundary_node_ids", "boundary_edge_ids", "evidence_ids", "fact_ids", "input_hash", "authority_hash"];
const EXPECTED_WINDOW_KEYS = ["id", "node_ids", "internal_edge_ids", "boundary_node_ids", "boundary_edge_ids", "evidence_ids", "fact_ids", "input_hash", "authority_hash"];
const PREPARED_KEYS = ["run_id", "scopes", "scope_ids", "window_ids", "windows", "selected_counts", "cached", "validated", "model", "budgets", "authority_hash", "selection_hash", "recovered_source_acknowledgement", "source_coverage", "requires_confirm_cloud"];
const SELECTED_COUNT_KEYS = ["work_units", "deterministic_scopes", "windows", "nodes", "internal_edges", "boundary_nodes", "boundary_edges", "evidence", "facts"];
export const ORGANIZATION_BUDGET_KEYS = Object.freeze(["soft_seconds", "hard_seconds", "soft_tokens", "hard_tokens", "hard_calls"]);
export const ORGANIZATION_MODEL = Object.freeze({ id: "gpt-5.6-luna", reasoning: "high", fast_mode: false });

function exactKeys(value, keys, label) {
  if (!object(value) || Object.keys(value).length !== keys.length || keys.some((key) => !Object.hasOwn(value, key))) throw new TypeError(`${label} has missing or extra fields`);
  return value;
}

function digest(value, label) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) throw new TypeError(`${label} is not an exact SHA-256 digest`);
  return value;
}

function uniqueStrings(value, label, maximum = 64) {
  if (!Array.isArray(value) || value.length > maximum || value.some((item) => typeof item !== "string" || !item || item.length > 512) || new Set(value).size !== value.length) throw new TypeError(`${label} is not a bounded unique string array`);
  return [...value];
}

function sameArray(left, right) { return left.length === right.length && left.every((item, index) => item === right[index]); }

export function exactOrganizationBudgets(value) {
  exactKeys(value, ORGANIZATION_BUDGET_KEYS, "Organization budgets");
  const result = Object.fromEntries(ORGANIZATION_BUDGET_KEYS.map((key) => {
    if (!Number.isInteger(value[key]) || value[key] <= 0) throw new TypeError("Organization budgets must be finite positive integers");
    return [key, value[key]];
  }));
  if (result.soft_seconds > result.hard_seconds || result.soft_tokens > result.hard_tokens) throw new TypeError("Organization soft budgets exceed hard budgets");
  return result;
}

export function exactOrganizationModel(value) {
  exactKeys(value, Object.keys(ORGANIZATION_MODEL), "Organization model");
  if (Object.keys(ORGANIZATION_MODEL).some((key) => value[key] !== ORGANIZATION_MODEL[key])) throw new TypeError("Organization model identity is not Luna/High/fast-off");
  return { ...ORGANIZATION_MODEL };
}

function exactExpectedWindow(value, window) {
  exactKeys(value, EXPECTED_WINDOW_KEYS, "Bounded-window expectation");
  for (const key of EXPECTED_WINDOW_KEYS) {
    if (key.endsWith("_ids")) {
      const ids = uniqueStrings(value[key], `Expected ${key}`, key === "evidence_ids" ? 2048 : key === "fact_ids" ? 1024 : 256);
      if (!sameArray(ids, window[key])) throw new TypeError(`Bounded-window expectation drifted at ${key}`);
    } else if (value[key] !== window[key]) throw new TypeError(`Bounded-window expectation drifted at ${key}`);
  }
  return value;
}

export function assertBoundedWindow(value) {
  exactKeys(value, WINDOW_KEYS, "Bounded narrative window");
  if (value.schema_version !== 1 || typeof value.id !== "string" || !value.id.startsWith("bounded_window_")) throw new TypeError("Invalid bounded-window identity");
  if (!['node_ids', 'anchors'].includes(value.selection_kind)) throw new TypeError("Invalid bounded-window selection kind");
  const arrays = {
    node_ids: 64, internal_edge_ids: 256, boundary_node_ids: 256,
    boundary_edge_ids: 256, evidence_ids: 2048, fact_ids: 1024,
  };
  for (const [key, maximum] of Object.entries(arrays)) uniqueStrings(value[key], `Window ${key}`, maximum);
  if (!value.node_ids.length) throw new TypeError("Bounded narrative window is empty");
  if (value.selection_kind === "anchors") {
    if (typeof value.entry_node_id !== "string" || !value.entry_node_id || typeof value.exit_node_id !== "string" || !value.exit_node_id) throw new TypeError("Bounded-window anchors are incomplete");
  } else if (value.entry_node_id !== null || value.exit_node_id !== null) throw new TypeError("Explicit bounded-window selection has unexpected anchors");
  digest(value.input_hash, "Window input_hash"); digest(value.authority_hash, "Window authority_hash");
  return value;
}

export function assertWindowSelectionRequest(value, windowValue) {
  const window = assertBoundedWindow(windowValue);
  const selectorKeys = window.selection_kind === "anchors" ? ["entry_node_id", "exit_node_id", "expected"] : ["node_ids", "expected"];
  exactKeys(value, selectorKeys, "Bounded-window selection request");
  if (window.selection_kind === "anchors") {
    if (value.entry_node_id !== window.entry_node_id || value.exit_node_id !== window.exit_node_id) throw new TypeError("Bounded-window anchors were tampered");
  } else if (!sameArray(uniqueStrings(value.node_ids, "Selection node_ids"), window.node_ids)) throw new TypeError("Bounded-window node_ids were tampered");
  exactExpectedWindow(value.expected, window);
  return value;
}

export function assertBoundedWindowResolution(value) {
  exactKeys(value, ["window", "selection_request"], "Bounded-window resolution");
  assertWindowSelectionRequest(value.selection_request, value.window);
  return value;
}

function exactSelectedCounts(value, scopeCount, windowCount) {
  exactKeys(value, SELECTED_COUNT_KEYS, "Selected counts");
  if (SELECTED_COUNT_KEYS.some((key) => !Number.isInteger(value[key]) || value[key] < 0)) throw new TypeError("Selected counts must be finite non-negative integers");
  if (value.work_units !== scopeCount + windowCount || value.deterministic_scopes !== scopeCount || value.windows !== windowCount) throw new TypeError("Selected counts do not match the prepared work units");
  return value;
}

export function assertPreparedOrganization(value) {
  exactKeys(value, PREPARED_KEYS, "Prepared organization");
  if (typeof value.run_id !== "string" || !value.run_id.startsWith("m07_") || value.requires_confirm_cloud !== true) throw new TypeError("Prepared organization consent is invalid");
  const scopeIds = uniqueStrings(value.scope_ids, "Prepared scope_ids");
  const windowIds = uniqueStrings(value.window_ids, "Prepared window_ids");
  if (!scopeIds.length && !windowIds.length) throw new TypeError("Prepared organization selection is empty");
  if (scopeIds.length + windowIds.length > 64 || scopeIds.some((id) => windowIds.includes(id))) throw new TypeError("Prepared organization selection is invalid");
  if (!Number.isInteger(value.scopes) || value.scopes !== scopeIds.length + windowIds.length) throw new TypeError("Prepared organization scope count is inexact");
  if (!Array.isArray(value.windows) || value.windows.length !== windowIds.length) throw new TypeError("Prepared bounded windows are inexact");
  value.windows.forEach((window, index) => { assertBoundedWindow(window); if (window.id !== windowIds[index]) throw new TypeError("Prepared window_ids were tampered"); });
  exactSelectedCounts(value.selected_counts, scopeIds.length, windowIds.length);
  if (![value.cached, value.validated].every((count) => Number.isInteger(count) && count >= 0 && count <= value.scopes)) throw new TypeError("Prepared checkpoint counts are invalid");
  exactOrganizationModel(value.model); exactOrganizationBudgets(value.budgets);
  digest(value.authority_hash, "Prepared authority_hash"); digest(value.selection_hash, "Prepared selection_hash"); digest(value.recovered_source_acknowledgement, "Prepared recovered-source acknowledgement");
  if (!object(value.source_coverage)) throw new TypeError("Prepared source coverage is unavailable");
  return value;
}

export function assertRoutePage(page) {
  if (!object(page) || !Array.isArray(page.nodes) || !Array.isArray(page.edges)) {
    throw new TypeError("Invalid Route Map response");
  }
  const nodes = page.nodes.length;
  const edges = page.edges.length;
  if (nodes > RENDER_LIMITS.nodes || edges > RENDER_LIMITS.edges || nodes + edges > RENDER_LIMITS.items) {
    throw new RangeError("Route Map exceeds the packaged rendering boundary");
  }
  for (const key of ["edge_offset", "edge_limit", "page_edge_total"]) {
    if (!Number.isInteger(page[key]) || page[key] < 0) throw new TypeError(`Invalid Route Map ${key}`);
  }
  if (page.edge_next_offset !== null && (!Number.isInteger(page.edge_next_offset) || page.edge_next_offset < 0)) {
    throw new TypeError("Invalid Route Map edge_next_offset");
  }
  if (edges > page.edge_limit || page.edge_limit > RENDER_LIMITS.edges) {
    throw new RangeError("Route Map edge slice exceeds the packaged rendering boundary");
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

export function assertAIStoryMap(value) {
  if (!object(value) || !["available", "unavailable"].includes(value.status)) throw new TypeError("Invalid AI Story Map response");
  digest(value.authority_hash, "AI Story Map authority_hash");
  if (value.status === "unavailable") {
    if (!object(value.technical_fallback) || value.technical_fallback.available !== true) throw new TypeError("AI Story Map fallback is unavailable");
    return value;
  }
  if (!Array.isArray(value.nodes) || !Array.isArray(value.edges) || !Array.isArray(value.continuation_endpoints) || !object(value.page) || !object(value.coverage)) throw new TypeError("AI Story Map page is incomplete");
  if (value.nodes.length > RENDER_LIMITS.nodes || value.edges.length > RENDER_LIMITS.edges || value.nodes.length + value.edges.length > RENDER_LIMITS.items) throw new RangeError("AI Story Map exceeds the packaged rendering boundary");
  if (value.level !== "ai_story_map" || value.presentation_levels?.length !== 2) throw new TypeError("Unexpected AI Story Map semantic levels");
  digest(value.organization_hash, "AI Story Map organization_hash");
  digest(value.projection_hash, "AI Story Map projection_hash");
  const page = value.page;
  for (const key of ["node_offset", "node_limit", "edge_offset", "edge_limit", "incident_edge_total", "total_nodes", "total_edges"]) {
    if (!Number.isInteger(page[key]) || page[key] < 0) throw new TypeError(`Invalid AI Story Map ${key}`);
  }
  if (page.edge_scope !== "incident_to_node_slice" || page.node_limit < 1 || page.node_limit > RENDER_LIMITS.nodes || page.edge_limit < 1 || page.edge_limit > RENDER_LIMITS.edges) throw new TypeError("Invalid AI Story Map incident-edge boundary");
  if (value.edges.length > page.edge_limit || page.edge_offset + value.edges.length > page.incident_edge_total || page.incident_edge_total > page.total_edges) throw new RangeError("AI Story Map incident-edge slice is inconsistent");
  const cursor = (token, offset, label) => {
    if (typeof token !== "string" || !/^v1\.\d+\.[0-9a-f]{64}$/.test(token) || Number(token.split(".")[1]) !== offset) throw new TypeError(`Invalid AI Story Map ${label}`);
  };
  if (page.edge_offset === 0) {
    if (page.edge_cursor !== null) throw new TypeError("Initial AI Story Map edge cursor must be null");
  } else cursor(page.edge_cursor, page.edge_offset, "edge_cursor");
  if ((page.next_edge_offset === null) !== (page.next_edge_cursor === null)) throw new TypeError("AI Story Map next edge cursor is incomplete");
  if (page.next_edge_offset !== null) {
    if (!Number.isInteger(page.next_edge_offset) || page.next_edge_offset !== page.edge_offset + value.edges.length || page.next_node_offset !== null) throw new TypeError("AI Story Map advances nodes before incident edges");
    cursor(page.next_edge_cursor, page.next_edge_offset, "next_edge_cursor");
  } else {
    if (page.edge_offset + value.edges.length !== page.incident_edge_total) throw new TypeError("AI Story Map dropped incident edges");
    if (page.next_node_offset !== null && (!Number.isInteger(page.next_node_offset) || page.next_node_offset <= page.node_offset)) throw new TypeError("Invalid AI Story Map next_node_offset");
  }
  const nodeIds = new Set(value.nodes.map((node) => node.id));
  const edgeById = new Map(value.edges.map((edge) => [edge.id, edge]));
  if (value.edges.some((edge) => !nodeIds.has(edge.source_id) && !nodeIds.has(edge.target_id))) throw new TypeError("AI Story Map returned an unrelated edge");
  const expectedContinuations = value.edges.flatMap((edge) => [["source", edge.source_id], ["target", edge.target_id]].filter(([, nodeId]) => !nodeIds.has(nodeId)).map(([endpoint, nodeId]) => `${edge.id}:${endpoint}:${nodeId}`));
  const actualContinuations = value.continuation_endpoints.map((item) => {
    if (!object(item) || !["source", "target"].includes(item.endpoint) || typeof item.edge_id !== "string" || typeof item.node_id !== "string" || typeof item.title !== "string" || !Number.isInteger(item.order)) throw new TypeError("Invalid AI Story Map continuation endpoint");
    const edge = edgeById.get(item.edge_id);
    if (!edge || edge[`${item.endpoint}_id`] !== item.node_id) throw new TypeError("AI Story Map continuation endpoint is not authoritative");
    return `${item.edge_id}:${item.endpoint}:${item.node_id}`;
  });
  if (!sameArray(actualContinuations, expectedContinuations)) throw new TypeError("AI Story Map continuation endpoints are incomplete");
  return value;
}

export function assertAIStoryDetail(value) {
  if (value?.status === "unavailable") return assertAIStoryMap(value);
  if (!object(value) || value.level !== "detail_evidence" || !object(value.element) || !Array.isArray(value.member_route_nodes) || !Array.isArray(value.member_route_edges) || !Array.isArray(value.evidence) || !Array.isArray(value.claims)) throw new TypeError("Invalid AI Detail/Evidence response");
  if (value.member_route_nodes.length > 30 || value.member_route_edges.length > 180 || value.evidence.length > 60) throw new RangeError("AI Detail/Evidence exceeds its bounded response limits");
  digest(value.authority_hash, "AI Detail authority_hash");
  return value;
}

export function assertMapComparison(value) {
  if (!object(value) || value.schema_version !== 1 || value.authority_unchanged !== true || !object(value.technical) || !object(value.ai)) throw new TypeError("Invalid map comparison response");
  digest(value.authority_hash, "Comparison authority_hash");
  assertRoutePage(value.technical);
  assertAIStoryMap(value.ai);
  if (value.technical.authority_hash !== value.authority_hash || value.ai.authority_hash !== value.authority_hash) throw new TypeError("Comparison authority changed");
  return value;
}

function exactOrganizationAccounting(value) {
  exactKeys(value, ["scope", "label", "run_id", "calls", "tokens", "elapsed_seconds", "elapsed_basis", "cache_hits", "attempts"], "Organization accounting");
  exactKeys(value.tokens, ["input", "output", "total"], "Organization accounting tokens");
  for (const item of [value.calls, value.tokens.input, value.tokens.output, value.tokens.total, value.cache_hits, value.attempts]) {
    if (!Number.isInteger(item) || item < 0) throw new TypeError("Organization accounting values must be non-negative integers");
  }
  if (value.tokens.total !== value.tokens.input + value.tokens.output || !Number.isFinite(value.elapsed_seconds) || value.elapsed_seconds < 0) throw new TypeError("Organization accounting totals are invalid");
  if (value.scope === "current_run") {
    if (value.label !== "Current run" || typeof value.run_id !== "string" || !value.run_id.startsWith("m07_") || value.elapsed_basis !== "wall_clock") throw new TypeError("Current-run accounting provenance is invalid");
  } else if (value.scope === "project_history") {
    if (value.label !== "Persisted project history" || value.run_id !== null || value.elapsed_basis !== "provider_attempts") throw new TypeError("Project-history accounting provenance is invalid");
  } else throw new TypeError("Organization accounting scope is invalid");
  return value;
}

export function assertOrganization(value) {
  if (!object(value)) throw new TypeError("Invalid organization response");
  exactOrganizationAccounting(value.accounting);
  if (!["current_run", "project_history"].includes(value.status_scope) || value.status_label !== value.accounting.label || !object(value.project_history) || value.project_history.scope !== "project_history" || value.project_history.label !== "Persisted project history") throw new TypeError("Organization status provenance is invalid");
  exactOrganizationAccounting(value.project_history.accounting);
  const scopeIds = uniqueStrings(value.scope_ids, "Organization scope_ids");
  const windowIds = uniqueStrings(value.window_ids, "Organization window_ids");
  exactSelectedCounts(value.selected_counts, scopeIds.length, windowIds.length);
  exactOrganizationModel(value.model); exactOrganizationBudgets(value.budgets);
  if (![value.cached, value.validated].every((count) => Number.isInteger(count) && count >= 0)) throw new TypeError("Organization checkpoint counts are invalid");
  if (value.selection_hash === null) {
    if (value.prepared_authority_hash !== null || value.recovered_source_acknowledgement !== null || scopeIds.length || windowIds.length) throw new TypeError("Unprepared organization exposes a partial consent binding");
  } else {
    digest(value.selection_hash, "Organization selection_hash"); digest(value.prepared_authority_hash, "Organization prepared_authority_hash"); digest(value.recovered_source_acknowledgement, "Organization recovered-source acknowledgement");
    if (!scopeIds.length && !windowIds.length) throw new TypeError("Organization consent selection is empty");
  }
  return value;
}
