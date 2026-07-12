import { ENDPOINTS, LEVEL_NUMBER, assertBoundedView } from "./contract.js";

const mutationMethods = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export class LocalApi {
  constructor({ session, csrf } = {}) {
    this.session = session || document.querySelector('meta[name="rsm-session"]')?.content || "";
    this.csrf = csrf || document.querySelector('meta[name="rsm-csrf"]')?.content || "";
  }

  async request(path, { method = "GET", body, signal } = {}) {
    if (!Object.values(ENDPOINTS).includes(path)) throw new TypeError("Unknown local API endpoint");
    const upperMethod = method.toUpperCase();
    const headers = { Accept: "application/json", "X-RSM-Session": this.session };
    if (mutationMethods.has(upperMethod)) {
      headers["Content-Type"] = "application/json";
      headers["X-RSM-CSRF"] = this.csrf;
    }
    const response = await fetch(path, {
      method: upperMethod,
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

  async bootstrap() {
    return this.request(ENDPOINTS.bootstrap);
  }
  pick(kind) {
    const apiKind = kind === "file" ? "source" : kind;
    return this.request(ENDPOINTS.nativePicker, { method: "POST", body: { kind: apiKind } });
  }
  chooseSave() { return this.request(ENDPOINTS.nativePicker, { method: "POST", body: { kind: "project_save" } }); }
  open(selectionId) { return this.request(ENDPOINTS.projectsOpen, { method: "POST", body: { selection_id: selectionId } }); }
  create(sourceSelectionId, projectSelectionId) { return this.request(ENDPOINTS.projectsCreate, { method: "POST", body: { source_selection_id: sourceSelectionId, project_selection_id: projectSelectionId } }); }
  progress() { return this.request(ENDPOINTS.analysisProgress); }
  cancel() { return this.request(ENDPOINTS.analysisCancel, { method: "POST", body: {} }); }
  async view(request) {
    const payload = { ...request, level: LEVEL_NUMBER[request.level] || 1, node_limit: 80, edge_limit: 120 };
    return assertBoundedView(await this.request(ENDPOINTS.storyView, { method: "POST", body: payload }));
  }
  search(query) { return this.request(ENDPOINTS.storySearch, { method: "POST", body: { query, limit: 100 } }); }
  evidence(nodeId) { return this.request(ENDPOINTS.storyEvidence, { method: "POST", body: { node_id: nodeId, limit: 80 } }); }
  facts(nodeId) { return this.request(ENDPOINTS.storyFacts, { method: "POST", body: { node_id: nodeId, limit: 80 } }); }
  saveSettings(settings) { return this.request(ENDPOINTS.settings, { method: "PUT", body: settings }); }
  consent(scopeIds) { return this.request(ENDPOINTS.organizationConsent, { method: "POST", body: { scope_ids: scopeIds, consent: true } }); }
  draft() { return this.request(ENDPOINTS.organizationDraft); }
  applyDraft(draftId) { return this.request(ENDPOINTS.organizationApply, { method: "POST", body: { draft_id: draftId } }); }
  discardDraft(draftId) { return this.request(ENDPOINTS.organizationDiscard, { method: "POST", body: { draft_id: draftId } }); }
  diagnostics() { return this.request(ENDPOINTS.diagnostics); }
  shutdown() { return this.request(ENDPOINTS.shutdown, { method: "POST", body: {} }); }
}
