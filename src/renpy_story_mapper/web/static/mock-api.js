import {
  ROUTE_EDGE_PAGE_SIZE, ROUTE_PAGE_SIZE, assertDetail, assertOrganization, assertRoutePage,
} from "./contract.js";

const titles = [
  "Day 1 · Arrival", "Garden choice", "A quiet refusal", "Garden conversation", "Day 1 merge",
  "Shared memory", "Day 2 · Market", "Vendor choice", "Market return", "Route commitment",
  "Red route · Promise", "Blue route · Harbor", "Red route · Night", "Blue route · Shift",
  "Shared call", "Courage gate", "Loop entry", "Try again", "Loop exit", "Final crossing",
  "Game ending", "Route ending", "Dead end", "Update boundary", "Unresolved target", "Epilogue",
  "Afterword", "Credits boundary", "Appendix route", "Last station", "Follow-on day", "Follow-on choice",
];

const lane = (index) => {
  if ([2, 3, 7].includes(index)) return ["detour-a", "detour"];
  if ([10, 12, 15, 17, 21].includes(index)) return ["red", "persistent"];
  if ([11, 13, 22, 23].includes(index)) return ["blue", "persistent"];
  return ["spine", "spine"];
};

const kind = (index) => {
  if ([1, 7, 9].includes(index)) return "choice";
  if ([4, 8, 14].includes(index)) return "merge";
  if (index === 16) return "loop";
  if ([20, 21, 22, 23].includes(index)) return "terminal";
  if (index === 24) return "unresolved";
  return "milestone";
};

const allNodes = titles.map((title, index) => {
  const [lane_id, lane_kind] = lane(index);
  return {
    id: `station-${index + 1}`, title, kind: kind(index), lane_id, lane_kind, order: index,
    terminal_kind: index === 20 ? "game_ending" : index === 21 ? "route_ending" : index === 22 ? "dead_end" : index === 23 ? "update_boundary" : null,
    unresolved: index === 24, evidence_ids: [`evidence-${index + 1}`], region_ids: [],
    summary: index === 1 ? "A compact choice opens a proven reconvergent detour." : "A chronological story milestone with exact local evidence.",
    effects: index === 3 ? [{ id: "effect-love", label: "Love +1" }] : [],
  };
});

const edge = (id, source, target, role = "flow", options = {}) => ({
  id, source_id: `station-${source}`, target_id: `station-${target}`, role,
  lane_id: options.lane || "spine", gate_ids: options.gates || [], effect_ids: options.effects || [],
  evidence_ids: options.evidence || [`edge-evidence-${id}`], technical_hops: options.technical || 0,
  proven_merge: options.merge || false,
});

const allEdges = [
  edge("spine-1", 1, 2), edge("fork-garden", 2, 3, "local_detour"),
  edge("fork-wits", 2, 4, "local_detour", { lane: "detour-a", gates: ["gate-wits"] }),
  edge("merge-refusal", 3, 5, "merge", { merge: true }), edge("merge-garden", 4, 5, "merge", { merge: true, effects: ["effect-love"] }),
  edge("corridor", 5, 6, "technical_corridor", { technical: 5 }), edge("spine-2", 6, 7),
  edge("market-fork", 7, 8, "flow"), edge("market-detour", 8, 9, "local_detour", { gates: ["gate-money"], effects: ["effect-money"] }),
  edge("route-fork", 9, 10, "flow"), edge("red-entry", 10, 11, "persistent_route", { lane: "red", gates: ["gate-red"], effects: ["effect-red-route"] }),
  edge("blue-entry", 10, 12, "persistent_route", { lane: "blue", gates: ["gate-blue"], effects: ["effect-blue-route"] }),
  edge("red-line", 11, 13, "persistent_route", { lane: "red" }), edge("blue-line", 12, 14, "persistent_route", { lane: "blue" }),
  edge("red-shared", 13, 15, "shared_call", { lane: "red" }), edge("blue-shared", 14, 15, "shared_call", { lane: "blue", merge: true }),
  edge("loop-entry", 15, 17), edge("loop-back", 17, 18, "loop_choice", { lane: "red" }), edge("loop-cycle", 18, 17, "loop_choice", { lane: "red" }),
  edge("loop-exit", 17, 19), edge("final", 19, 20), edge("ending-game", 20, 21),
  edge("ending-route", 20, 22, "persistent_route", { lane: "red" }), edge("ending-dead", 20, 23, "terminal_split"),
  edge("ending-update", 20, 24, "terminal_split", { lane: "blue" }), edge("ending-unresolved", 20, 25, "unresolved"),
  edge("epilogue", 21, 26), edge("afterword", 26, 27), edge("credits", 27, 28), edge("appendix", 28, 29), edge("last", 29, 30),
  edge("follow", 30, 31), edge("follow-choice", 31, 32),
];

const denseEdges = Array.from({ length: 195 }, (_, index) => {
  const source = (index % 29) + 1;
  const options = index % 17 === 0 ? { technical: 2 } : {};
  return edge(`dense-${index + 1}`, source, source + 1, index % 11 === 0 ? "local_detour" : "flow", options);
});

function page(offset, limit, edgeOffset, edgeLimit, dense = false) {
  const nodes = allNodes.slice(offset, offset + limit);
  const ids = new Set(nodes.map((node) => node.id));
  const pageEdges = (dense && offset === 0 ? denseEdges : allEdges).filter(
    (item) => ids.has(item.source_id) || ids.has(item.target_id),
  );
  const edges = pageEdges.slice(edgeOffset, edgeOffset + edgeLimit);
  const edgeNextOffset = edgeOffset + edges.length;
  return assertRoutePage({
    level: "route_map", offset, limit, edge_offset: edgeOffset, edge_limit: edgeLimit,
    total_nodes: allNodes.length, nodes, edges,
    next_offset: offset + nodes.length < allNodes.length ? offset + nodes.length : null,
    edge_next_offset: edgeNextOffset < pageEdges.length ? edgeNextOffset : null,
    page_edge_total: pageEdges.length,
    overflow: pageEdges.length > edges.length ? { kind: "edge_slice", total: pageEdges.length } : null,
    coverage: { control_nodes: 97, visible_nodes: 32, technical_nodes: 5, unresolved_nodes: 1, corridor_count: 1 },
  });
}

function detailFor(elementId) {
  const node = allNodes.find((item) => item.id === elementId);
  const selectedEdge = allEdges.find((item) => item.id === elementId);
  const element = node || selectedEdge;
  if (!element) throw new Error("The selected map element is unavailable");
  const isEdge = Boolean(selectedEdge);
  return assertDetail({
    level: "detail_evidence", element,
    predecessor_ids: isEdge ? [selectedEdge.source_id] : allEdges.filter((item) => item.target_id === node.id).map((item) => item.source_id),
    successor_ids: isEdge ? [selectedEdge.target_id] : allEdges.filter((item) => item.source_id === node.id).map((item) => item.target_id),
    choices: [{ id: "choice-garden", caption: "Take the garden path" }],
    gates: [{ id: "gate-wits", label: "Wits ≥ 2", expression: "wits >= 2", certainty: "proven" }],
    effects: [{ id: "effect-love", label: "Love +1", expression: "love += 1", certainty: "proven" }],
    dialogue: [{ id: "dialogue-1", speaker: "Mara", text: "There is another way through this." }],
    narration: [{ id: "narration-1", text: "A short garden detour." }],
    interpretations: [{ id: "claim-1", label: "Interpretation", text: "The conversation strengthens the relationship.", evidence_ids: ["effect-love"] }],
    evidence: [
      { id: "gate-wits", kind: "choice", text: '"Take the garden path" if wits >= 2:', source: { path: "m07/route_topology.rpy", start_line: 5, end_line: 5, basis: "physical" } },
      { id: "effect-love", kind: "effect", text: "$ love += 1", source: { path: "m07/route_topology.rpy", start_line: 6, end_line: 6, basis: "physical" } },
      { id: "dialogue-1", kind: "dialogue", text: "There is another way through this.", source: { path: "m07/route_topology.rpy", start_line: 7, end_line: 7, basis: "physical" } },
    ],
    back_target: "route_map",
  });
}

export class MockApi {
  constructor() { this.calls = []; this.cancelled = false; this.started = false; this.polls = 0; this.dense = new URLSearchParams(location.search).get("state") === "paging"; }
  record(name, payload = {}) { this.calls.push({ name, payload }); }
  async bootstrap() {
    this.record("bootstrap");
    return { recent_projects: [{ id: "project-demo", name: "The Lantern House", source_type: "Archive", last_opened: "Today · 10:42", organization: "Technical map" }], settings: { theme: "dark", include_technical: true, include_unresolved: true } };
  }
  async pick(kind) { this.record("pick", { kind }); return { selection_id: `opaque-${kind}`, display_name: "The Lantern House" }; }
  async chooseSave() { this.record("chooseSave"); return { selection_id: "opaque-project-save" }; }
  async create(sourceSelectionId, projectSelectionId) { this.record("create", { sourceSelectionId, projectSelectionId }); return { task: { state: "running" } }; }
  async open(selectionId) { this.record("open", { selectionId }); return { project: { id: "project-demo", name: "The Lantern House", organization: "Technical map" }, analysis: { state: "complete" } }; }
  async refresh() { this.record("refresh"); return { analysis: { state: "complete" } }; }
  async progress() { this.record("progress"); return { state: "complete", stage: "Route Map ready", percent: 100, elapsed_seconds: 8 }; }
  async cancelAnalysis() { this.record("cancelAnalysis"); return { state: "cancelled" }; }
  async routeMap(offset = 0, limit = ROUTE_PAGE_SIZE, edgeOffset = 0, edgeLimit = ROUTE_EDGE_PAGE_SIZE) {
    this.record("routeMap", { offset, limit, edge_offset: edgeOffset, edge_limit: edgeLimit });
    return page(offset, limit, edgeOffset, edgeLimit, this.dense);
  }
  async detail(elementId) { this.record("detail", { element_id: elementId }); return detailFor(elementId); }
  async organization() {
    this.record("organization"); this.polls += 1;
    const done = this.started && this.polls > 1;
    return assertOrganization({ status: done ? "review_ready" : this.started ? "running" : this.cancelled ? "cancelled" : "idle", run_id: "run-demo", assembly_id: done ? "assembly-demo" : null, scopes: { total: 8, validated: done ? 5 : 3, fallback: 1, pending: done ? 2 : 4, failed: 0 }, calls: done ? 6 : 4, tokens: { used: done ? 12400 : 7800, budget: 18000 }, coverage: { ai: done ? 0.625 : 0.375, technical: done ? 0.75 : 0.5 }, eta: { low_seconds: done ? 0 : 90, high_seconds: done ? 0 : 210 }, partial: true });
  }
  async prepareOrganization() { this.record("prepareOrganization", {}); return assertOrganization({ run_id: "run-demo", scopes: 8, cached: 2, budgets: { soft_tokens: 15000, hard_tokens: 18000, hard_calls: 16 }, provider_constructed: false }); }
  async startOrganization(runId, budgets) { this.record("startOrganization", { run_id: runId, confirm_cloud: true, budgets }); this.started = true; this.cancelled = false; this.polls = 0; return this.organization(); }
  async cancelOrganization() { this.record("cancelOrganization", {}); this.cancelled = true; this.started = false; return assertOrganization({ status: "cancelled", validated_preserved: 3 }); }
  async applyAssembly(assemblyId) { this.record("applyAssembly", { assembly_id: assemblyId }); return assertOrganization({ status: "applied", assembly_id: assemblyId }); }
  async saveSettings(settings) { this.record("saveSettings", settings); return { settings }; }
  async diagnostics() { this.record("diagnostics"); return { browser_api: "v1", levels: 2, provider_requests_on_open: 0, network: "loopback only" }; }
  async shutdown() { this.record("shutdown"); return { state: "shutting_down" }; }
}
