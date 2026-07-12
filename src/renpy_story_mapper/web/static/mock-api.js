import { assertBoundedView } from "./contract.js";

const text = [
  "A quiet arrival establishes the town and its unresolved history.",
  "A choice divides the investigation before the paths converge.",
  "Trust becomes the gate for a private conversation.",
  "The shared call returns to the central story line.",
];

function nodesFor(level) {
  const count = level === "arcs" ? 6 : level === "events" ? 14 : 9;
  return Array.from({ length: count }, (_, index) => ({
    id: `${level}-${index + 1}`,
    title: level === "arcs" ? ["The Arrival", "Old Signals", "Fault Lines", "Night Crossing", "The Reckoning", "Four Endings"][index] : level === "events" ? `Event ${String(index + 1).padStart(2, "0")} · ${["Arrival", "Question", "Choice", "Detour", "Meeting", "Return", "Gate"][index % 7]}` : `Evidence ${index + 1}`,
    summary: text[index % text.length],
    kind: index % 7 === 2 ? "choice" : index % 9 === 4 ? "merge" : index % 11 === 7 ? "unresolved" : level.slice(0, -1),
    technical: index === count - 1,
    unresolved: index % 11 === 7,
    parent_id: level === "arcs" ? null : "arcs-1",
    characters: index % 2 ? ["Mara", "Elias"] : ["Mara"],
    facts: [
      { id: `req-${index}`, type: "requirement", label: "Trust ≥ 2", expression: "trust >= 2", certainty: "proven" },
      { id: `effect-${index}`, type: "effect", label: "Trust +1", expression: "trust += 1", certainty: "proven" },
    ],
    evidence_count: 3 + (index % 4),
    source: { path: "game/story/chapter_01.rpy", start_line: 118 + index * 4, end_line: 121 + index * 4, basis: "physical" },
  }));
}

function edgesFor(nodes) {
  const edges = [];
  for (let index = 0; index < nodes.length - 1; index += 1) {
    edges.push({ id: `edge-${index}`, source: nodes[index].id, target: nodes[index + 1].id, kind: index === 2 ? "choice" : "flow", label: index === 2 ? "Trust ≥ 2" : "" });
    if (index === 2 && nodes[index + 3]) edges.push({ id: `branch-${index}`, source: nodes[index].id, target: nodes[index + 3].id, kind: "choice", label: "Wait" });
  }
  return edges;
}

export class MockApi {
  constructor() { this.calls = []; this.level = "arcs"; this.cancelled = false; }
  record(name, payload = {}) { this.calls.push({ name, payload }); }
  async bootstrap() {
    this.record("bootstrap");
    return {
      api_version: "v1", project: null,
      recent_projects: [
        { id: "project-demo", name: "The Lantern House", source_type: "Archive", last_opened: "Today · 10:42", organization: "Accepted", deterministic: true },
        { id: "project-north", name: "Northbound", source_type: "Folder", last_opened: "Yesterday", organization: "Technical", deterministic: true },
        { id: "project-glass", name: "Glass Harbor", source_type: "Project", last_opened: "8 Jul", organization: "Draft ready", deterministic: true },
      ],
      settings: { theme: "system", zoom: 1, include_technical: false, include_unresolved: true, show_requirements: true, show_effects: true },
    };
  }
  async pick(kind) { this.record("pick", { kind }); return { selection_id: `opaque-${kind}`, display_name: kind === "folder" ? "The Lantern House" : "Selected story" }; }
  async chooseSave() { this.record("chooseSave"); return { selection: { id: "opaque-project-save", kind: "project_save", display_name: "The Lantern House.rsmproj" } }; }
  async create(sourceSelectionId, projectSelectionId) { this.record("create", { sourceSelectionId, projectSelectionId }); return { task: { id: "analysis-demo", state: "running" } }; }
  async open(selectionId) { this.record("open", { selectionId }); return { project: { id: "project-demo", name: "The Lantern House", organization: "Technical organization", level: "arcs" }, analysis: { id: "analysis-demo", state: "running" } }; }
  async progress() { this.record("progress"); return { state: this.cancelled ? "cancelled" : "complete", stage: this.cancelled ? "Cancelled safely" : "Presentation index ready", percent: this.cancelled ? 47 : 100, elapsed_seconds: 8 }; }
  async cancel() { this.record("cancel"); this.cancelled = true; return { state: "cancelled" }; }
  async view(request) {
    this.record("view", request); this.level = request.level;
    let nodes = nodesFor(request.level);
    if (!request.include_technical) nodes = nodes.filter((node) => !node.technical);
    if (!request.include_unresolved) nodes = nodes.filter((node) => !node.unresolved);
    const query = String(request.query || "").toLocaleLowerCase();
    if (query) nodes = nodes.filter((node) => `${node.title} ${node.summary}`.toLocaleLowerCase().includes(query));
    return assertBoundedView({ level: request.level, nodes, edges: edgesFor(nodes), overflow: request.level === "events" ? { nodes_total: 318, edges_total: 442, message: "Showing a bounded slice: 14 of 318 nodes" } : null, selected_id: request.selected_id || null });
  }
  async evidence(nodeId) {
    this.record("evidence", { nodeId });
    return { node_id: nodeId, records: Array.from({ length: 6 }, (_, index) => ({ id: `${nodeId}-e${index}`, kind: index % 2 ? "dialogue" : "expression", speaker: index % 2 ? "Mara" : "", text: index % 2 ? "There is another way through this." : index === 0 ? "trust >= 2" : "trust += 1", source: { path: "game/story/chapter_01.rpy", start_line: 118 + index, end_line: 118 + index, basis: "physical" } })), truncated: false };
  }
  async facts(nodeId) { this.record("facts", { nodeId }); return { items: nodesFor(this.level).find((node) => node.id === nodeId)?.facts || [] }; }
  async search(query) { this.record("search", { query }); return { items: nodesFor(this.level).filter((node) => `${node.title} ${node.summary}`.toLowerCase().includes(query.toLowerCase())).map((node) => ({ node_id: node.id, title: node.title, level: this.level })) }; }
  async saveSettings(settings) { this.record("saveSettings", settings); return { settings }; }
  async consent(scopeIds) { this.record("organizationConsent", { scopeIds }); return { draft_id: "draft-demo", status: "review_ready" }; }
  async organization() { this.record("organization"); return this.draft(); }
  async draft() { this.record("draft"); return { id: "draft-demo", provider: "Codex · GPT-5.6 Luna · High", elapsed: "01:42", cache_hits: 12, provider_calls: 0, changes: [{ type: "Renamed", before: "Label start", after: "The Arrival" }, { type: "Grouped", before: "7 technical events", after: "Night Crossing" }, { type: "Unchanged", before: "4 authoritative endings", after: "4 authoritative endings" }] }; }
  async applyDraft(draftId) { this.record("applyDraft", { draftId }); return { status: "accepted" }; }
  async discardDraft(draftId) { this.record("discardDraft", { draftId }); return { status: "discarded" }; }
  async diagnostics() { this.record("diagnostics"); return { version: "0.1.0", project_schema: 5, browser_api: "v1", provider_requests_on_open: this.calls.filter((call) => call.name === "organizationConsent").length, messages: ["Presentation index loaded", "Rendering limited to 240 items", "No remote requests observed"] }; }
}
