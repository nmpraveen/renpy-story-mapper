import {
  ENDPOINTS, ROUTE_EDGE_PAGE_SIZE, ROUTE_PAGE_SIZE,
  assertBoundedWindowResolution, assertDetail, assertOrganization,
  assertPreparedOrganization, assertRoutePage, assertWindowSelectionRequest,
  assertAIStoryDetail, assertAIStoryMap, assertMapComparison,
  exactOrganizationBudgets,
} from "./contract.js";

const mutations = new Set(["POST", "PUT", "PATCH", "DELETE"]);
export const DEFAULT_ORGANIZATION_BUDGETS = Object.freeze({
  soft_seconds: 600, hard_seconds: 900, soft_tokens: 1500000, hard_tokens: 2000000, hard_calls: 48,
});
const budgetKeys = Object.keys(DEFAULT_ORGANIZATION_BUDGETS);

function exactBudgets(value) {
  const budgets = exactOrganizationBudgets(value);
  if (Object.values(budgets).some((item) => !Number.isInteger(item))) throw new TypeError("Organization budgets must be finite integers");
  return budgets;
}

function uniqueIds(value, label) {
  if (!Array.isArray(value) || value.length > 64 || value.some((item) => typeof item !== "string" || !item || item.length > 512) || new Set(value).size !== value.length) throw new TypeError(`${label} must be a bounded unique ID array`);
  return [...value];
}

function exactKeys(value, keys, label) {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).length !== keys.length || keys.some((key) => !Object.hasOwn(value, key))) throw new TypeError(`${label} has missing or extra fields`);
  return value;
}

function exactWindowRequest(request) {
  if (!request || typeof request !== "object" || Array.isArray(request)) throw new TypeError("Bounded-window request must be an object");
  const anchors = Object.hasOwn(request, "entry_node_id") || Object.hasOwn(request, "exit_node_id");
  exactKeys(request, anchors ? ["entry_node_id", "exit_node_id", "expected"] : ["node_ids", "expected"], "Bounded-window request");
  const expected = request.expected;
  const window = {
    schema_version: 1,
    id: expected?.id,
    selection_kind: anchors ? "anchors" : "node_ids",
    entry_node_id: anchors ? request.entry_node_id : null,
    exit_node_id: anchors ? request.exit_node_id : null,
    node_ids: expected?.node_ids,
    internal_edge_ids: expected?.internal_edge_ids,
    boundary_node_ids: expected?.boundary_node_ids,
    boundary_edge_ids: expected?.boundary_edge_ids,
    evidence_ids: expected?.evidence_ids,
    fact_ids: expected?.fact_ids,
    input_hash: expected?.input_hash,
    authority_hash: expected?.authority_hash,
  };
  assertWindowSelectionRequest(request, window);
  return JSON.parse(JSON.stringify(request));
}

export function organizationStartPayload(preparedValue) {
  const prepared = assertPreparedOrganization(preparedValue);
  if (!prepared.run_id || (!prepared.scope_ids.length && !prepared.window_ids.length)) throw new TypeError("Prepared organization binding is incomplete");
  const binding = { scope_ids: prepared.scope_ids, budgets: prepared.budgets };
  return {
    run_id: prepared.run_id,
    confirm_cloud: true,
    scope_ids: [...binding.scope_ids],
    window_ids: [...prepared.window_ids],
    selection_hash: prepared.selection_hash,
    authority_hash: prepared.authority_hash,
    recovered_source_acknowledgement: prepared.recovered_source_acknowledgement,
    model: { ...prepared.model },
    budgets: exactBudgets(binding.budgets),
  };
}

export class LocalApi {
  constructor({ session, csrf } = {}) {
    this.session = session || document.querySelector('meta[name="rsm-session"]')?.content || "";
    this.csrf = csrf || document.querySelector('meta[name="rsm-csrf"]')?.content || "";
    this.organizationSelection = { scopeIds: [], windowRequests: [] };
  }

  async request(path, { method = "GET", body, signal } = {}) {
    if (!Object.values(ENDPOINTS).includes(path)) throw new TypeError("Unknown local API endpoint");
    const verb = method.toUpperCase();
    const headers = { Accept: "application/json", "X-RSM-Session": this.session };
    if (mutations.has(verb)) {
      headers["Content-Type"] = "application/json";
      headers["X-RSM-CSRF"] = this.csrf;
    }
    const response = await fetch(path, {
      method: verb,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
      signal,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error?.message || "Local request failed");
    return payload;
  }

  bootstrap() { return this.request(ENDPOINTS.bootstrap); }
  pick(kind) { return this.request(ENDPOINTS.nativePicker, { method: "POST", body: { kind: kind === "file" ? "source" : kind } }); }
  chooseSave() { return this.request(ENDPOINTS.nativePicker, { method: "POST", body: { kind: "project_save" } }); }
  open(selectionId) { return this.request(ENDPOINTS.projectsOpen, { method: "POST", body: { selection_id: selectionId } }); }
  create(sourceSelectionId, projectSelectionId) { return this.request(ENDPOINTS.projectsCreate, { method: "POST", body: { source_selection_id: sourceSelectionId, project_selection_id: projectSelectionId } }); }
  refresh() { return this.request(ENDPOINTS.projectsRefresh, { method: "POST", body: {} }); }
  progress() { return this.request(ENDPOINTS.analysisProgress); }
  cancelAnalysis() { return this.request(ENDPOINTS.analysisCancel, { method: "POST", body: {} }); }
  saveSettings(settings) { return this.request(ENDPOINTS.settings, { method: "PUT", body: settings }); }
  diagnostics() { return this.request(ENDPOINTS.diagnostics); }
  shutdown() { return this.request(ENDPOINTS.shutdown, { method: "POST", body: {} }); }

  async routeMap(offset = 0, limit = ROUTE_PAGE_SIZE, edgeOffset = 0, edgeLimit = ROUTE_EDGE_PAGE_SIZE) {
    return assertRoutePage(await this.request(ENDPOINTS.routeMap, {
      method: "POST", body: { offset, limit, edge_offset: edgeOffset, edge_limit: edgeLimit },
    }));
  }
  async detail(elementId) {
    return assertDetail(await this.request(ENDPOINTS.routeDetail, { method: "POST", body: { element_id: elementId } }));
  }
  async inspectionMap(view, offset = 0, limit = ROUTE_PAGE_SIZE, edgeOffset = 0, edgeLimit = ROUTE_EDGE_PAGE_SIZE) {
    if (!["simplified", "canonical"].includes(view)) throw new TypeError("Unknown inspection view");
    return assertRoutePage(await this.request(ENDPOINTS.inspectionMap, {
      method: "POST", body: { view, offset, limit, edge_offset: edgeOffset, edge_limit: edgeLimit },
    }));
  }
  async inspectionDetail(view, elementId) {
    if (!["simplified", "canonical"].includes(view)) throw new TypeError("Unknown inspection view");
    return assertDetail(await this.request(ENDPOINTS.inspectionDetail, { method: "POST", body: { view, element_id: elementId } }));
  }
  async aiStoryMap(nodeOffset = 0, nodeLimit = ROUTE_PAGE_SIZE, edgeOffset = 0, edgeLimit = ROUTE_EDGE_PAGE_SIZE, edgeCursor = null) {
    const body = { node_offset: nodeOffset, node_limit: nodeLimit, edge_offset: edgeOffset, edge_limit: edgeLimit };
    if (edgeCursor !== null) body.edge_cursor = edgeCursor;
    return assertAIStoryMap(await this.request(ENDPOINTS.aiStoryMap, {
      method: "POST", body,
    }));
  }
  async aiStoryDetail(elementId, cursors = {}) {
    return assertAIStoryDetail(await this.request(ENDPOINTS.aiStoryDetail, {
      method: "POST", body: { element_id: elementId, ...cursors },
    }));
  }
  async mapComparison(nodeOffset = 0, nodeLimit = ROUTE_PAGE_SIZE, edgeOffset = 0, edgeLimit = ROUTE_EDGE_PAGE_SIZE) {
    return assertMapComparison(await this.request(ENDPOINTS.mapComparison, {
      method: "POST", body: { node_offset: nodeOffset, node_limit: nodeLimit, edge_offset: edgeOffset, edge_limit: edgeLimit },
    }));
  }
  async resolveBoundedWindow(selection) {
    const anchors = selection && (Object.hasOwn(selection, "entry_node_id") || Object.hasOwn(selection, "exit_node_id"));
    exactKeys(selection, anchors ? ["entry_node_id", "exit_node_id"] : ["node_ids"], "Bounded-window selector");
    const body = anchors
      ? { entry_node_id: selection.entry_node_id, exit_node_id: selection.exit_node_id }
      : { node_ids: uniqueIds(selection.node_ids, "Bounded-window node_ids") };
    return assertBoundedWindowResolution(await this.request(ENDPOINTS.boundedWindowResolve, { method: "POST", body }));
  }
  async organization() { return assertOrganization(await this.request(ENDPOINTS.organization)); }
  setOrganizationSelection(scopeIds, windowRequests) {
    this.organizationSelection = { scopeIds: [...scopeIds], windowRequests: [...windowRequests] };
  }
  async prepareOrganization(scopeIds = this.organizationSelection.scopeIds, windowRequests = this.organizationSelection.windowRequests, budgets = DEFAULT_ORGANIZATION_BUDGETS) {
    const scopes = uniqueIds(scopeIds, "Organization scope_ids");
    if (!Array.isArray(windowRequests) || windowRequests.length > 64) throw new TypeError("Organization window_requests must be bounded");
    const windows = windowRequests.map(exactWindowRequest);
    if (!scopes.length && !windows.length) throw new TypeError("Select a bounded scope or exact narrative window before preparing AI");
    if (scopes.length + windows.length > 64) throw new TypeError("Organization selection exceeds the work-unit limit");
    const requested = exactBudgets(budgets);
    const prepared = assertPreparedOrganization(await this.request(ENDPOINTS.organizationPrepare, { method: "POST", body: { scope_ids: scopes, window_requests: windows, ...requested } }));
    const returned = exactBudgets(prepared.budgets);
    if (budgetKeys.some((key) => returned[key] !== requested[key])) throw new TypeError("Prepared organization budgets changed in transit");
    return prepared;
  }
  async startOrganization(prepared) {
    const body = organizationStartPayload(prepared);
    return assertOrganization(await this.request(ENDPOINTS.organizationStart, {
      method: "POST", body,
    }));
  }
  async cancelOrganization() { return assertOrganization(await this.request(ENDPOINTS.organizationCancel, { method: "POST", body: {} })); }
  async applyAssembly(assemblyId) { return assertOrganization(await this.request(ENDPOINTS.assemblyApply, { method: "POST", body: { assembly_id: assemblyId } })); }
  async discardAssembly(assemblyId) { return assertOrganization(await this.request(ENDPOINTS.assemblyDiscard, { method: "POST", body: { assembly_id: assemblyId } })); }
}
