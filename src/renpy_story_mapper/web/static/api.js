import {
  ENDPOINTS, ROUTE_EDGE_PAGE_SIZE, ROUTE_PAGE_SIZE,
  assertDetail, assertOrganization, assertRoutePage,
} from "./contract.js";

const mutations = new Set(["POST", "PUT", "PATCH", "DELETE"]);
export const DEFAULT_ORGANIZATION_BUDGETS = Object.freeze({
  soft_seconds: 300, hard_seconds: 600, soft_tokens: 15000, hard_tokens: 18000, hard_calls: 16,
});
const budgetKeys = Object.keys(DEFAULT_ORGANIZATION_BUDGETS);

function exactBudgets(value) {
  if (!value || budgetKeys.some((key) => !Number.isFinite(value[key]) || value[key] <= 0)) throw new TypeError("Prepared organization budgets are missing or unbounded");
  return Object.fromEntries(budgetKeys.map((key) => [key, value[key]]));
}

export class LocalApi {
  constructor({ session, csrf } = {}) {
    this.session = session || document.querySelector('meta[name="rsm-session"]')?.content || "";
    this.csrf = csrf || document.querySelector('meta[name="rsm-csrf"]')?.content || "";
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
  async organization() { return assertOrganization(await this.request(ENDPOINTS.organization)); }
  async prepareOrganization(scopeIds = [], budgets = DEFAULT_ORGANIZATION_BUDGETS) {
    const requested = exactBudgets(budgets);
    const prepared = assertOrganization(await this.request(ENDPOINTS.organizationPrepare, { method: "POST", body: { scope_ids: scopeIds, ...requested } }));
    const returned = exactBudgets(prepared.budgets);
    if (budgetKeys.some((key) => returned[key] !== requested[key]) || !Array.isArray(prepared.scope_ids) || !prepared.scope_ids.length) throw new TypeError("Prepared organization binding is incomplete");
    return prepared;
  }
  async startOrganization(prepared) {
    if (!prepared?.run_id || !Array.isArray(prepared.scope_ids) || !prepared.scope_ids.length) throw new TypeError("Prepared organization binding is unavailable");
    const budgets = exactBudgets(prepared.budgets);
    return assertOrganization(await this.request(ENDPOINTS.organizationStart, {
      method: "POST", body: { run_id: prepared.run_id, confirm_cloud: true, scope_ids: prepared.scope_ids, budgets },
    }));
  }
  async cancelOrganization() { return assertOrganization(await this.request(ENDPOINTS.organizationCancel, { method: "POST", body: {} })); }
  async applyAssembly(assemblyId) { return assertOrganization(await this.request(ENDPOINTS.assemblyApply, { method: "POST", body: { assembly_id: assemblyId } })); }
}
