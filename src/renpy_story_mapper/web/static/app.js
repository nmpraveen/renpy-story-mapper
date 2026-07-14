import { LocalApi } from "./api.js";
import { ROUTE_EDGE_PAGE_SIZE, ROUTE_PAGE_SIZE } from "./contract.js";
import { RouteGraph } from "./graph.js";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const api = new LocalApi();
const CURSOR_HISTORY_LIMIT = 12;

const state = {
  project: null, page: null, aiPage: null, technicalPage: null, inspectionPage: null, canonicalPage: null, aiReason: null, mode: "inspection",
  analysisStatus: null,
  offset: 0, edgeOffset: 0, edgeCursor: null, cursorHistory: [], selectedId: null, detail: null,
  organization: null, prepared: null, assemblyId: null, windowResolution: null,
  settings: { theme: "system", include_technical: true, include_unresolved: true },
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

const graph = new RouteGraph({
  viewport: $("#mapViewport"), world: $("#mapWorld"), canvas: $("#edgeCanvas"),
  onSelect: (item) => selectItem(item), onOpen: (item) => openDetail(item.id),
});

function toast(message) {
  const host = $("#toast"); host.textContent = message; host.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { host.hidden = true; }, 2800);
}

function showPrimary(name) {
  $("#welcomeView").hidden = name !== "welcome";
  $("#progressView").hidden = name !== "progress";
  $("#workspaceView").hidden = name !== "workspace";
  $("#projectIdentity").hidden = name === "welcome";
  $("#refreshProject").hidden = name !== "workspace";
}

function showLevel(level) {
  const detail = level === "detail_evidence";
  $("#routeMapView").hidden = detail;
  $("#detailView").hidden = !detail;
  document.documentElement.dataset.activeLevel = detail ? "detail_evidence" : "route_map";
}

function renderRecent(projects) {
  const host = $("#recentProjects"); host.replaceChildren();
  $("#recentCount").textContent = `${projects.length} saved locally`;
  for (const project of projects) {
    const button = element("button", "recent-card"); button.type = "button";
    button.append(element("span", "recent-type", project.source_type || "Project"), element("strong", "", project.name || "Saved project"), element("span", "recent-meta", `${project.last_opened || "Saved locally"} · ${project.organization || "Technical Structure"}`));
    button.addEventListener("click", () => openSelection({ id: project.selection_id || project.id, display_name: project.name }, true));
    host.append(button);
  }
  if (!projects.length) host.append(element("p", "muted", "No recent projects."));
}

async function choose(kind) {
  try {
    const chosen = await api.pick(kind); const source = chosen.selection || chosen;
    if (!source?.selection_id && !source?.id) return;
    if (kind === "project") await openSelection(source, true);
    else {
      const saved = await api.chooseSave(); const destination = saved.selection || saved;
      if (!destination?.selection_id && !destination?.id) return;
      await api.create(source.selection_id || source.id, destination.selection_id || destination.id);
      state.project = { name: source.display_name || "New story", organization: "Technical Structure" };
      showPrimary("progress"); await pollAnalysis();
    }
  } catch (error) { toast(error.message); }
}

async function openSelection(selection, notify = false) {
  try {
    const opened = await api.open(selection.selection_id || selection.id);
    state.project = opened.project || { name: selection.display_name || "Story", organization: "Technical Structure" };
    if (state.project.name === "Opening") state.project.name = selection.display_name || "Story";
    $("#projectName").textContent = state.project.name;
    if (["running", "pending"].includes(opened.analysis?.state || opened.task?.state)) { showPrimary("progress"); await pollAnalysis(); }
    else await enterAvailableWorkspace();
    if (notify) toast("Project opened locally");
  } catch (error) { toast(error.message); }
}

async function pollAnalysis() {
  let progress;
  do {
    progress = await api.progress(); progress = progress.task || progress;
    const percent = Math.max(0, Math.min(100, Number(progress.percent || 0)));
    $("#progressStage").textContent = String(progress.stage || "Preparing").replaceAll("_", " ");
    $("#progressBar").style.width = `${percent}%`; $(".progress-track").setAttribute("aria-valuenow", String(percent));
    $("#progressPercent").textContent = `${percent}%`; const seconds = Number(progress.elapsed_seconds || 0); $("#progressElapsed").textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
    if (progress.state === "running") await new Promise((resolve) => setTimeout(resolve, 350));
  } while (progress.state === "running");
  if (["complete", "completed"].includes(progress.state)) await enterAvailableWorkspace();
  else if (progress.state === "cancelled") { showPrimary("welcome"); toast("Analysis cancelled safely"); }
  else await enterAvailableWorkspace();
  return progress;
}

function aiLane(node) {
  const role = node.presentation_role || "event";
  if (role === "detour_annotation") return { id: "ai-detours", kind: "detour", label: "Local detours" };
  if (role === "persistent_route") return { id: `ai-route-${node.scope_ids?.[0] || "branch"}`, kind: "persistent", label: "Persistent route" };
  return { id: "ai-story-spine", kind: "spine", label: "Story spine" };
}

function normalizedPage(page, mode = state.mode) {
  if (mode === "ai") {
    const nodes = page.nodes.map((node) => {
      const lane = aiLane(node);
      const kinds = node.route_node_kinds || [];
      const kind = node.presentation_role === "ending" ? "ending" : node.presentation_role === "loop" ? "loop" : kinds.includes("choice") ? "choice" : kinds.includes("merge") ? "merge" : "event";
      return { ...node, kind, lane_id: lane.id, lane_kind: lane.kind, lane_label: lane.label, title: node.title || "Untitled story event", summary: node.summary || "" };
    });
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const continuationByEndpoint = new Map((page.continuation_endpoints || []).map((item) => [`${item.edge_id}:${item.endpoint}`, item]));
    const edges = page.edges.map((edge) => ({ ...edge, role: edge.presentation_role || "transition", lane_id: nodeById.get(edge.source_id)?.lane_id || nodeById.get(edge.target_id)?.lane_id || "ai-story-spine", source_title: continuationByEndpoint.get(`${edge.id}:source`)?.title, target_title: continuationByEndpoint.get(`${edge.id}:target`)?.title }));
    const lanes = [...new Map(nodes.map((node) => [node.lane_id, { id: node.lane_id, kind: node.lane_kind, label: node.lane_label }])).values()];
    return { ...page, nodes, edges, lanes, offset: page.page.node_offset, edge_offset: page.page.edge_offset, edge_cursor: page.page.edge_cursor, next_offset: page.page.next_node_offset, edge_next_offset: page.page.next_edge_offset, edge_next_cursor: page.page.next_edge_cursor, total_nodes: page.page.total_nodes, page_edge_total: page.page.incident_edge_total, edge_limit: page.page.edge_limit };
  }
  return {
    ...page,
    nodes: page.nodes.map((node) => ({ ...node, title: node.title || "Untitled technical node", summary: node.summary || "" })),
    edges: page.edges.map((edge) => ({ ...edge, source_id: edge.source_id || edge.source, target_id: edge.target_id || edge.target })),
  };
}

function renderAnalysisAvailability(status, hasMap) {
  state.analysisStatus = status || null;
  const failure = status?.failure;
  const completed = status?.completed_phases || [];
  $("#analysisFailureBanner").hidden = !failure;
  if (failure) {
    const phase = String(failure.phase || "analysis").replaceAll("_", " ");
    $("#analysisFailureTitle").textContent = `Analysis failed in ${phase}`;
    const displayed = status.last_known_good ? "Showing last-known-good results" : hasMap ? "Showing current retained results" : "No retained map is available";
    $("#analysisFailureSummary").textContent = `${displayed} · ${status.freshness || "unavailable"}`;
    $("#analysisCompletedPhases").textContent = completed.length ? `Completed: ${completed.map((item) => String(item).replaceAll("_", " ")).join(" · ")}` : "No phases completed";
  }
  $("#mapLayout").hidden = !hasMap;
  $("#partialAnalysisPanel").hidden = hasMap;
  if (!hasMap) $("#partialAnalysisSummary").textContent = completed.length ? `Completed phases: ${completed.map((item) => String(item).replaceAll("_", " ")).join(" · ")}` : "Analysis stopped before a renderable graph was produced.";
}

async function loadComparison() {
  let simplified = null; let canonical = null; let comparison = null;
  try { simplified = await api.inspectionMap("simplified", 0, ROUTE_PAGE_SIZE, 0, ROUTE_EDGE_PAGE_SIZE); } catch (_error) { simplified = null; }
  try { canonical = await api.inspectionMap("canonical", 0, ROUTE_PAGE_SIZE, 0, ROUTE_EDGE_PAGE_SIZE); } catch (_error) { canonical = null; }
  state.inspectionPage = simplified?.status === "available" ? normalizedPage(simplified, "inspection") : null;
  state.canonicalPage = canonical?.status === "available" ? normalizedPage(canonical, "canonical") : null;
  try { comparison = await api.mapComparison(0, ROUTE_PAGE_SIZE, 0, ROUTE_EDGE_PAGE_SIZE); } catch (_error) { comparison = null; }
  state.technicalPage = comparison ? normalizedPage(comparison.technical, "technical") : null;
  state.aiPage = comparison?.ai.status === "available" ? normalizedPage(comparison.ai, "ai") : null;
  state.aiReason = comparison?.ai.reason || "not yet organized";
  const inspectionCurrent = state.inspectionPage?.generation_status?.freshness === "current";
  const canonicalCurrent = state.canonicalPage?.generation_status?.freshness === "current";
  if (inspectionCurrent) { state.mode = "inspection"; state.page = state.inspectionPage; }
  else if (canonicalCurrent) { state.mode = "canonical"; state.page = state.canonicalPage; }
  else if (state.inspectionPage) { state.mode = "inspection"; state.page = state.inspectionPage; }
  else if (state.technicalPage) { state.mode = "technical"; state.page = state.technicalPage; }
  else { state.mode = "inspection"; state.page = null; }
  const status = state.page?.generation_status || simplified?.generation_status || canonical?.generation_status || null;
  const hasMap = Boolean(state.page);
  renderAnalysisAvailability(status, hasMap);
  $("#fallbackNotice").hidden = !hasMap || Boolean(state.aiPage);
  $("#fallbackReason").textContent = `${String(state.aiReason).replaceAll("_", " ")}. ${state.mode === "inspection" ? "M10 Inspection" : state.mode === "canonical" ? "M10 Canonical" : "Technical Structure"} is shown.`;
  updateModeHeader();
  if (hasMap) renderMap();
  else graph.setData([], [], null, []);
  return hasMap;
}

async function loadRoutePage(cursor = { offset: state.offset, edgeOffset: state.edgeOffset, edgeCursor: state.edgeCursor }) {
  try {
    const raw = state.mode === "ai"
      ? await api.aiStoryMap(cursor.offset, ROUTE_PAGE_SIZE, cursor.edgeOffset, ROUTE_EDGE_PAGE_SIZE, cursor.edgeCursor ?? null)
      : ["inspection", "canonical"].includes(state.mode)
        ? await api.inspectionMap(state.mode === "canonical" ? "canonical" : "simplified", cursor.offset, ROUTE_PAGE_SIZE, cursor.edgeOffset, ROUTE_EDGE_PAGE_SIZE)
        : await api.routeMap(cursor.offset, ROUTE_PAGE_SIZE, cursor.edgeOffset, ROUTE_EDGE_PAGE_SIZE);
    if (raw.status === "unavailable") { renderAnalysisAvailability(raw.generation_status, false); return false; }
    const page = normalizedPage(raw, state.mode);
    state.page = page;
    if (state.mode === "ai") state.aiPage = page;
    else if (state.mode === "inspection") state.inspectionPage = page;
    else if (state.mode === "canonical") state.canonicalPage = page;
    else state.technicalPage = page;
    state.offset = Number(page.offset || 0);
    state.edgeOffset = Number(page.edge_offset || 0);
    state.edgeCursor = state.mode === "ai" ? page.edge_cursor ?? null : null;
    updateModeHeader(); renderMap(); return true;
  } catch (error) { $("#selectionStatus").textContent = "Map unavailable"; toast(error.message); }
}

async function resetRoutePaging() {
  state.cursorHistory = [];
  state.offset = 0; state.edgeOffset = 0; state.edgeCursor = null; state.windowResolution = null; state.prepared = null;
  $("#scopePreview").textContent = "No story text is sent until an exact preview is confirmed.";
  return loadComparison();
}

async function enterAvailableWorkspace() {
  showPrimary("workspace"); showLevel("route_map");
  const available = await resetRoutePaging();
  await loadOrganization();
  return available;
}

function nextCursor() {
  const navigation = state.page?.global_navigation || state.page?.navigation || {};
  if (navigation.next && Number.isInteger(navigation.next.offset)) return { offset: navigation.next.offset, edgeOffset: navigation.next.edge_offset || 0 };
  if (state.page?.edge_next_offset !== null && state.page?.edge_next_offset !== undefined) return { offset: state.offset, edgeOffset: Number(state.page.edge_next_offset), edgeCursor: state.mode === "ai" ? state.page.edge_next_cursor : null };
  if (state.page?.next_offset !== null && state.page?.next_offset !== undefined) return { offset: Number(state.page.next_offset), edgeOffset: 0, edgeCursor: null };
  return null;
}

async function nextRoutePage() {
  const target = nextCursor(); if (!target) return;
  state.cursorHistory.push({ offset: state.offset, edgeOffset: state.edgeOffset, edgeCursor: state.edgeCursor });
  if (state.cursorHistory.length > CURSOR_HISTORY_LIMIT) state.cursorHistory.shift();
  await loadRoutePage(target);
}

async function previousRoutePage() { const target = state.cursorHistory.pop(); if (target) await loadRoutePage(target); }

async function searchM10WholeGraph() {
  const query = $("#searchInput").value.trim();
  const requestId = (searchM10WholeGraph.requestId || 0) + 1; searchM10WholeGraph.requestId = requestId;
  if (!["inspection", "canonical"].includes(state.mode)) { renderMap(); return; }
  const view = state.mode === "canonical" ? "canonical" : "simplified";
  const raw = await api.inspectionMap(view, 0, ROUTE_PAGE_SIZE, 0, ROUTE_EDGE_PAGE_SIZE, query ? { query } : {});
  if (requestId !== searchM10WholeGraph.requestId || $("#searchInput").value.trim() !== query) return;
  if (raw.status === "unavailable") { renderAnalysisAvailability(raw.generation_status, Boolean(state.page)); return; }
  const focus = raw.search?.focus;
  if (view === "simplified" && focus?.target_view === "canonical") {
    const options = query ? { query, focus: focus.canonical_page_target_id } : { focus: focus.canonical_page_target_id };
    const canonicalRaw = await api.inspectionMap("canonical", Number(focus.canonical_page_offset || 0), ROUTE_PAGE_SIZE, 0, ROUTE_EDGE_PAGE_SIZE, options);
    if (requestId !== searchM10WholeGraph.requestId || $("#searchInput").value.trim() !== query) return;
    if (canonicalRaw.status === "unavailable") { renderAnalysisAvailability(canonicalRaw.generation_status, Boolean(state.page)); return; }
    const canonicalPage = normalizedPage(canonicalRaw, "canonical"); canonicalPage.search = raw.search;
    showLevel("route_map"); state.mode = "canonical"; state.page = canonicalPage; state.canonicalPage = canonicalPage; state.offset = Number(canonicalPage.offset || 0); state.edgeOffset = 0; state.cursorHistory = []; state.selectedId = focus.canonical_page_target_id;
    updateModeHeader(); renderMap();
    await openDetail(focus.canonical_id);
    return;
  }
  const page = normalizedPage(raw, state.mode); state.page = page;
  if (state.mode === "inspection") state.inspectionPage = page; else state.canonicalPage = page;
  state.offset = Number(page.offset || 0); state.edgeOffset = 0; state.cursorHistory = [];
  state.selectedId = page.search?.focus?.element_id || null;
  renderMap();
  if (query && !page.search?.total_matches) $("#selectionStatus").textContent = "No whole-graph matches";
  else if (state.selectedId) graph.world.querySelector(`[data-element-id="${CSS.escape(state.selectedId)}"]`)?.focus();
}

function visiblePage() {
  const query = $("#searchInput").value.trim().toLocaleLowerCase();
  const globalSearch = state.page?.global_search || state.page?.search;
  const matchedIds = query && globalSearch?.query === query && Array.isArray(globalSearch.element_ids) ? new Set(globalSearch.element_ids) : null;
  const visibleNodes = (state.page?.nodes || []).filter((node) => {
    if (!state.settings.include_unresolved && node.unresolved) return false;
    return !query || matchedIds?.has(node.id) || `${node.id} ${node.title} ${node.summary} ${node.reachability || ""}`.toLocaleLowerCase().includes(query);
  });
  const ids = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = (state.page?.edges || []).filter((edge) => {
    const continuation = !ids.has(edge.source_id) || !ids.has(edge.target_id);
    if (!continuation && !state.settings.include_technical && Number(edge.technical_hops || 0) > 0) return false;
    return ids.has(edge.source_id) || ids.has(edge.target_id);
  });
  return { nodes: visibleNodes, edges: visibleEdges };
}

function renderLanes(nodes) {
  const host = $("#laneList"); host.replaceChildren();
  const metadata = new Map((state.page?.lanes || []).map((lane) => [lane.id, lane]));
  for (const node of nodes) if (!metadata.has(node.lane_id)) metadata.set(node.lane_id, { id: node.lane_id, kind: node.lane_kind, label: node.lane_label });
  for (const lane of metadata.values()) {
    const row = element("div", "line-key"); const swatch = element("i", `swatch ${lane.kind === "detour" ? "detour" : ""}`);
    row.append(swatch, element("span", "", lane.label || String(lane.kind || "route").replaceAll("_", " "))); host.append(row);
  }
}

function renderMap() {
  if (!state.page) { renderAnalysisAvailability(state.analysisStatus, false); return; }
  const { nodes, edges } = visiblePage();
  graph.setData(nodes, edges, state.selectedId, state.page?.lanes || []);
  renderLanes(nodes); state.selectedId = graph.selectedId;
  const first = state.offset + 1; const last = state.offset + (state.page?.nodes.length || 0); const total = Number(state.page?.total_nodes || last);
  const edgeFirst = state.edgeOffset + 1; const edgeLast = state.edgeOffset + (state.page?.edges.length || 0); const edgeTotal = Number(state.page?.page_edge_total ?? edgeLast);
  const dense = Boolean(state.page?.overflow) || edgeTotal > state.page?.edges.length;
  $("#pageStatus").textContent = `${state.mode === "ai" ? "Events" : "Nodes"} ${first}–${last} of ${total} · routes ${edgeTotal ? `${edgeFirst}–${edgeLast} of ${edgeTotal}` : "none"}${dense ? " · bounded" : ""}`;
  $("#previousPage").disabled = state.cursorHistory.length === 0; $("#nextPage").disabled = nextCursor() === null;
  const nodeIds = new Set(nodes.map((node) => node.id)); const continuations = edges.filter((edge) => !nodeIds.has(edge.source_id) || !nodeIds.has(edge.target_id)).length;
  $("#visibleStatus").textContent = `${nodes.length} ${state.mode === "ai" ? "events" : "nodes"} · ${edges.length} routes${continuations ? ` · ${continuations} continuations` : ""}`;
  const generation = state.page?.generation_status;
  renderAnalysisAvailability(generation, true);
  $("#generationStatus").hidden = !generation;
  if (generation) $("#generationStatus").textContent = `${generation.freshness} · ${String(generation.analysis_status || "unknown").replaceAll("_", " ")}`;
  const coverage = state.page?.coverage || {}; const summary = $("#coverageSummary"); summary.replaceChildren();
  if (state.mode === "ai") summary.append(element("strong", "", "Story coverage"), element("span", "", `${coverage.ai_owned_route_nodes || 0} AI-organized nodes`), element("span", "", `${coverage.technical_fallback_route_nodes || 0} technical fallback nodes`));
  else if (["inspection", "canonical"].includes(state.mode)) summary.append(element("strong", "", state.mode === "canonical" ? "Canonical authority" : "Inspection coverage"), element("span", "", `${coverage.control_nodes ?? "—"} canonical records`), element("span", "", `${coverage.suppressed_records ?? 0} presentation suppressions`));
  else summary.append(element("strong", "", "Technical authority"), element("span", "", `${coverage.control_nodes ?? "—"} control points`), element("span", "", `${coverage.technical_nodes ?? 0} collapsed steps`));
  const selected = graph.elements().find((item) => item.id === state.selectedId); if (selected) selectItem(selected);
}

function updateModeHeader() {
  const ai = state.mode === "ai";
  const inspection = state.mode === "inspection"; const canonical = state.mode === "canonical"; const technical = state.mode === "technical";
  $("#aiMapButton").setAttribute("aria-pressed", String(ai)); $("#inspectionMapButton").setAttribute("aria-pressed", String(inspection)); $("#canonicalMapButton").setAttribute("aria-pressed", String(canonical)); $("#technicalMapButton").setAttribute("aria-pressed", String(technical));
  $("#aiMapButton").disabled = !state.aiPage;
  $("#inspectionMapButton").disabled = !state.inspectionPage;
  $("#canonicalMapButton").disabled = !state.canonicalPage;
  $("#technicalMapButton").disabled = !state.technicalPage;
  $("#mapEyebrow").textContent = ai ? "AI Story Map" : inspection ? "Deterministic inspection" : canonical ? "Canonical technical graph" : "Technical Structure";
  $("#mapTitle").textContent = ai ? "The story at a glance" : inspection ? "Choices, routes, and rejoins" : canonical ? "Every canonical record" : "Authoritative control flow";
  $("#projectBadge").textContent = ai ? "AI Story Map · applied" : inspection ? "M10 Inspection" : canonical ? "M10 Canonical" : "Technical Structure";
  const m10 = inspection || canonical; $("#organizationPanel").hidden = m10; $("#organizeButton").hidden = m10;
  if (!state.aiPage) $("#fallbackReason").textContent = `${String(state.aiReason || "not yet organized").replaceAll("_", " ")}. ${inspection ? "Inspection" : canonical ? "Canonical graph" : "Technical Structure"} is shown.`;
}

async function switchMode(mode) {
  if (mode === "ai" && !state.aiPage) { toast("Apply a validated organization before using the AI Story Map"); return; }
  const page = mode === "ai" ? state.aiPage : mode === "inspection" ? state.inspectionPage : mode === "canonical" ? state.canonicalPage : state.technicalPage;
  if (!page) { toast("That map is unavailable for this analysis result"); return; }
  state.mode = mode; state.page = page; state.cursorHistory = []; state.offset = Number(state.page?.offset || 0); state.edgeOffset = Number(state.page?.edge_offset || 0); state.edgeCursor = mode === "ai" ? state.page?.edge_cursor ?? null : null; state.selectedId = null;
  updateModeHeader(); if (state.page) renderMap(); else await loadRoutePage({ offset: 0, edgeOffset: 0 });
}

function selectItem(item) { state.selectedId = item.id; $("#selectionStatus").textContent = `${item.title || String(item.role || item.kind || "route").replaceAll("_", " ")} · Enter for Detail / Evidence`; }

function addFactGroup(host, title, items, type) {
  if (!items?.length) return;
  const section = element("section", "fact-group"); section.append(element("h2", "", title)); const list = element("ul", "fact-list");
  for (const item of items) { const visibleLabel = item.label || (item.speaker_display_name && item.text ? `${item.speaker_display_name}: ${item.text}` : item.variable_display_name || item.caption || item.text || item.id); const row = element("li", `fact ${type}`); row.append(element("span", "fact-shape", type === "gate" ? "△" : type === "effect" ? "+" : "•"), element("strong", "", visibleLabel), element("code", "", item.expression || "")); list.append(row); }
  section.append(list); host.append(section);
}

function evidenceExcerpt(record) {
  const payload = record.payload || {};
  const provenance = Array.isArray(payload.provenance) ? payload.provenance.map((item) => item.source_text).filter(Boolean) : [];
  const choices = Array.isArray(payload.choices) ? payload.choices.map((item) => item.condition ? `“${item.caption}” if ${item.condition}` : `“${item.caption}”`) : [];
  return provenance.join("\n") || choices.join("\n") || record.text || record.excerpt || record.source_text || "Evidence text unavailable";
}

function evidenceLineBasis(record, source) {
  const basis = record.line_basis || source.line_basis || source.basis || record.basis;
  if (!basis) return "Source basis unavailable";
  const qualified = String(basis);
  if (/^reconstructed(?:_|$)/i.test(qualified)) return `Reconstructed source · ${qualified}`;
  if (/^physical(?:_|$)/i.test(qualified)) return `Physical source · ${qualified}`;
  return `Qualified source · ${qualified}`;
}

function renderTechnicalMembers(detail) {
  const host = $("#memberGraph"); host.replaceChildren();
  for (const node of detail.member_route_nodes || []) host.append(element("span", "member-node", node.title || String(node.kind || "technical node").replaceAll("_", " ")));
  for (const edge of detail.member_route_edges || []) host.append(element("span", "member-edge", String(edge.role || "connection").replaceAll("_", " ")));
  $("#technicalMembers").hidden = !host.children.length;
}

function renderInspectionDerivations(detail) {
  const regionHost = $("#regionDerivation"); const proofHost = $("#proofDerivation"); const linkHost = $("#linkedRecords");
  regionHost.replaceChildren(); proofHost.replaceChildren(); linkHost.replaceChildren();
  if (detail.region) {
    const region = detail.region; const summary = element("article", "derivation-record");
    summary.append(element("strong", "", String(region.classification || "branch region").replaceAll("_", " ")), element("span", "", `Split ${region.split_node_id} · merge ${region.merge_node_id || "none"}`), element("span", "", `Persistence: ${(region.persistence_reasons || []).join(" · ") || "none"}`)); regionHost.append(summary);
    for (const arm of region.ordered_arms || []) {
      const record = element("article", "derivation-record"); const facts = (arm.facts || []).map((item) => item.label || item.id).join(" · "); const predicate = arm.predicate || {}; const expressions = predicate.expression || (predicate.expressions || []).join(" · ") || "unconditional";
      record.append(element("strong", "", `Arm ${Number(arm.ordinal) + 1}`), element("span", "", `Entry ${arm.entry_node_id} · ${arm.member_count} members · ${arm.terminal_summary || "nonterminal"}`), element("span", "", `Predicate: ${String(predicate.kind || "branch").replaceAll("_", " ")} · ${String(predicate.polarity || "unknown").replaceAll("_", " ")} · ${expressions}`), element("span", "", facts ? `Facts: ${facts}` : "Facts: none")); regionHost.append(record);
    }
  }
  for (const proof of detail.proofs || []) { const record = element("article", "derivation-record"); record.append(element("strong", "", String(proof.kind || "proof").replaceAll("_", " ")), element("p", "", proof.explanation || "Deterministic derivation"), element("span", "", `Inputs: ${(proof.input_ids || []).join(" · ")}`)); proofHost.append(record); }
  for (const linked of detail.linked_records || []) { if (linked.id === detail.element?.id) continue; const button = element("button", "quiet-button linked-record", `${String(linked.kind || "record").replaceAll("_", " ")} · ${linked.title || linked.id}`); button.type = "button"; button.addEventListener("click", () => openDetail(linked.id)); linkHost.append(button); }
  $("#derivationPanel").hidden = !(regionHost.children.length || proofHost.children.length || linkHost.children.length);
}

async function openDetail(elementId) {
  try {
    const detail = state.mode === "ai" ? await api.aiStoryDetail(elementId) : ["inspection", "canonical"].includes(state.mode) ? await api.inspectionDetail(state.mode === "canonical" ? "canonical" : "simplified", elementId) : await api.detail(elementId); state.detail = detail; state.selectedId = elementId;
    if (detail.status === "unavailable") {
      if (state.mode === "ai") { await switchMode("technical"); toast("AI Story Map became unavailable; Technical Structure is shown"); }
      else { renderAnalysisAvailability(detail.generation_status, Boolean(state.page)); toast("This inspection result is unavailable for the retained generation"); }
      return;
    }
    const selected = detail.element; $("#detailTitle").textContent = selected.title || String(selected.presentation_role || selected.role || selected.kind || "Story element").replaceAll("_", " ");
    $("#detailKind").textContent = String(selected.source_kind || selected.presentation_role || selected.kind || selected.role || "route element").replaceAll("_", " ");
    $("#detailSummary").textContent = selected.unsupported_status || selected.summary || "Authoritative local context and exact source evidence.";
    $("#canonicalEscapeButton").hidden = state.mode === "canonical" || !detail.canonical_focus_id;
    const strip = $("#pathStrip"); strip.replaceChildren();
    for (const id of detail.predecessor_ids || []) strip.append(element("span", "path-stop predecessor", `← ${titleFor(id)}`));
    strip.append(element("strong", "path-stop current", $("#detailTitle").textContent));
    for (const id of detail.successor_ids || []) strip.append(element("span", "path-stop successor", `${titleFor(id)} →`));
    renderTechnicalMembers(detail);
    renderInspectionDerivations(detail);
    const facts = $("#detailFacts"); facts.replaceChildren(); const allFacts = detail.facts || [];
    addFactGroup(facts, "Exact choices", detail.choices, "choice"); addFactGroup(facts, "Requirements", detail.gates || detail.requirements || allFacts.filter((item) => String(item.kind || "").includes("gate") || String(item.type || "").includes("require")), "gate"); addFactGroup(facts, "Effects", detail.effects || allFacts.filter((item) => String(item.kind || "").includes("effect")), "effect"); addFactGroup(facts, "Dialogue", detail.dialogue, "dialogue"); addFactGroup(facts, "Narration", detail.narration, "narration");
    const interpretations = $("#interpretations"); interpretations.replaceChildren();
    const candidates = detail.ai_candidates || detail.candidates || selected.ai_candidates || [];
    const claims = detail.claims || candidates.flatMap((candidate) => candidate.claims || []);
    for (const candidate of candidates) { const article = element("article", "interpretation candidate"); article.append(element("strong", "", candidate.title || candidate.label || "Candidate"), element("p", "", candidate.summary || candidate.text || "")); if (candidate.correction) article.append(element("span", "correction", `Correction: ${candidate.correction.title || candidate.correction.text || "provided"}`)); if (candidate.pinned) article.append(element("span", "pin", "Pinned by reviewer")); interpretations.append(article); }
    for (const claim of claims) { const article = element("article", "interpretation claim"); article.append(element("strong", "", claim.label || "Evidence-backed claim"), element("p", "", claim.text || claim.claim || ""), element("span", "evidence-links", `Evidence: ${(claim.evidence_ids || []).join(", ") || "not supplied"}`)); interpretations.append(article); }
    if (!interpretations.children.length) interpretations.append(element("p", "muted", "No AI interpretation is attached; the technical map is authoritative."));
    const evidence = $("#evidenceList"); evidence.replaceChildren();
    for (const record of detail.evidence || []) {
      const article = element("article", "evidence-record"); article.dataset.evidenceId = record.id;
      const source = record.source || record.location || {}; const start = source.start?.line ?? source.start_line ?? record.start_line ?? "?"; const endLine = source.end?.line ?? source.end_line ?? record.end_line; const end = endLine && endLine !== start ? `–${endLine}` : "";
      article.append(element("span", "evidence-id", `${record.id} · ${record.kind || "source"}`), element("pre", "", evidenceExcerpt(record)), element("span", "source-line", `${source.path || record.source_path || record.path || "source unavailable"}:${start}${end} · ${evidenceLineBasis(record, source)}`)); evidence.append(article);
    }
    if (!evidence.children.length) evidence.append(element("p", "muted", "No exact evidence was returned."));
    showLevel("detail_evidence"); $("#backToRouteMap").focus();
  } catch (error) { toast(error.message); }
}

async function openCanonicalRecord() {
  const focusId = state.detail?.canonical_focus_id; if (!focusId) return;
  showLevel("route_map"); state.mode = "canonical"; state.page = null; state.canonicalPage = null; state.cursorHistory = []; state.offset = Number(state.detail.canonical_focus_offset || 0); state.edgeOffset = 0; state.selectedId = focusId;
  await loadRoutePage({ offset: state.offset, edgeOffset: 0 });
  graph.world.querySelector(`[data-element-id="${CSS.escape(focusId)}"]`)?.focus();
}

function titleFor(id) { return state.page?.nodes.find((node) => node.id === id)?.title || "Adjacent event"; }

async function loadOrganization() { try { state.organization = await api.organization(); renderOrganization(); } catch (error) { $("#organizationMetrics").replaceChildren(element("p", "muted", "Organization status unavailable.")); } }

function renderOrganization() {
  const value = state.organization || {}; const scopes = value.scopes || {}; const accounting = value.accounting || {}; const tokens = accounting.tokens || {}; const coverage = value.coverage || {}; const eta = value.eta || {};
  const fallback = Number(scopes.fallback || 0) + Number(scopes.failed || 0) + Number(scopes.cancelled || 0);
  const honestStatus = value.status === "complete" && fallback ? "partial with fallback" : String(value.status || "idle").replaceAll("_", " ");
  const metricLabel = value.status_label || accounting.label || "Accounting unavailable";
  const host = $("#organizationMetrics"); host.replaceChildren();
  const rows = [
    [`Status — ${metricLabel}`, `${honestStatus} · ${value.stage || "idle"}`],
    [`Scopes — ${metricLabel}`, `${scopes.validated || 0} validated · ${scopes.fallback || 0} fallback · ${scopes.pending || 0} pending · ${scopes.cancelled || 0} cancelled`],
    [`Usage — ${metricLabel}`, `${accounting.calls || 0} calls · ${Number(tokens.total || 0).toLocaleString()} tokens`],
    [`Time — ${metricLabel}`, `${Number(accounting.elapsed_seconds || 0).toFixed(1)}s ${accounting.elapsed_basis === "provider_attempts" ? "provider time" : "elapsed"} · ${eta.low_seconds == null ? "ETA unavailable" : `${Math.ceil(eta.low_seconds / 60)}–${Math.ceil(eta.high_seconds / 60)} min ETA`}`],
    [`Cache — ${metricLabel}`, `${accounting.cache_hits || 0} hits · ${accounting.attempts || 0} provider attempts`],
    [`Coverage — ${metricLabel}`, `${Math.round(Number(coverage.ai || 0) * 100)}% AI · ${Math.round(Number(coverage.technical || 0) * 100)}% technical`],
  ];
  for (const [label, text] of rows) { const row = element("div", "metric"); row.append(element("span", "", label), element("strong", "", text)); host.append(row); }
  $("#cancelOrganization").hidden = value.status !== "running"; $("#resumeOrganization").hidden = !["cancelled", "partial"].includes(value.status); $("#reviewPartial").hidden = !value.assembly_id;
  state.assemblyId = value.assembly_id || null;
}

function visibleRouteNodeIds() {
  const visible = visiblePage().nodes;
  const selected = visible.find((node) => node.id === state.selectedId) || visible[0];
  const candidates = state.mode === "ai"
    ? selected?.member_route_node_ids || []
    : visible.map((node) => node.id);
  const ids = [...new Set(candidates)].slice(0, 6);
  const total = state.mode === "ai"
    ? Number(state.page?.coverage?.authoritative_route_nodes || ids.length)
    : Number(state.page?.total_nodes || ids.length);
  if (total > 1 && ids.length >= total) ids.pop();
  return ids;
}

async function selectVisibleForAI() {
  const nodeIds = visibleRouteNodeIds(); if (!nodeIds.length) throw new Error("No visible story nodes are available for a bounded window");
  state.windowResolution = await api.resolveBoundedWindow({ node_ids: nodeIds });
  api.setOrganizationSelection([], [state.windowResolution.selection_request]);
  const window = state.windowResolution.window;
  $("#scopePreview").textContent = `${window.node_ids.length} nodes · ${window.internal_edge_ids.length} internal edges · ${window.boundary_node_ids.length} boundary nodes · ${window.boundary_edge_ids.length} boundary edges · ${window.evidence_ids.length} evidence · ${window.fact_ids.length} facts · input ${window.input_hash} · authority ${window.authority_hash}`;
  return state.windowResolution;
}

async function prepareOrganization() {
  try {
    if (!state.windowResolution) await selectVisibleForAI();
    state.prepared = await api.prepareOrganization();
    const facts = $("#consentFacts"); facts.replaceChildren(); const prepared = state.prepared; const counts = prepared.selected_counts; const budgets = prepared.budgets; const model = prepared.model; const window = prepared.windows[0];
    const rows = [
      ["Selection", `${counts.work_units} bounded work unit · ${counts.nodes} nodes · ${counts.internal_edges} internal edges`],
      ["Boundaries", `${counts.boundary_nodes} nodes · ${counts.boundary_edges} edges`],
      ["Boundary node IDs", window?.boundary_node_ids?.join(", ") || "none"],
      ["Boundary edge IDs", window?.boundary_edge_ids?.join(", ") || "none"],
      ["Evidence / facts", `${counts.evidence} / ${counts.facts}`],
      ["Window", prepared.window_ids.join(", ")],
      ["Input hash", window?.input_hash || "n/a"], ["Authority hash", prepared.authority_hash], ["Selection hash", prepared.selection_hash],
      ["Recovered-source acknowledgement", prepared.recovered_source_acknowledgement],
      ["Provider", `${model.id} · ${model.reasoning} reasoning · fast mode ${model.fast_mode ? "on" : "off"}`],
      ["Time budgets", `${budgets.soft_seconds}s soft · ${budgets.hard_seconds}s hard`], ["Token budgets", `${budgets.soft_tokens.toLocaleString()} soft · ${budgets.hard_tokens.toLocaleString()} hard`], ["Call budget", budgets.hard_calls],
      ["Cache", `${prepared.cached} cached · ${prepared.validated} validated`],
    ];
    for (const [label, value] of rows) facts.append(element("dt", "", label), element("dd", "", value));
    $("#consentDialog").showModal();
  } catch (error) { toast(error.message); }
}

async function startOrganization() {
  if (!state.prepared?.run_id) { toast("Prepared run is unavailable"); return; }
  try { state.organization = await api.startOrganization(state.prepared); renderOrganization(); pollOrganization(); } catch (error) { toast(error.message); }
}

async function pollOrganization() {
  const active = new Set(["running", "starting", "cancelling", "queued"]);
  while (active.has(state.organization?.status)) { await new Promise((resolve) => setTimeout(resolve, 900)); await loadOrganization(); }
  if (["complete", "partial", "review", "applied", "cancelled", "failed"].includes(state.organization?.status)) renderOrganization();
}

function showReview() {
  const coverage = state.organization?.coverage || {}; $("#reviewCoverage").textContent = `${Math.round(Number(coverage.ai || 0) * 100)}% AI coverage · ${Math.round(Number(coverage.technical || 0) * 100)}% technical fallback`;
  const host = $("#reviewCandidates"); host.replaceChildren(); const candidates = state.organization?.assembly?.items || state.organization?.candidates || [];
  for (const candidate of candidates) { const result = candidate.result || candidate; const article = element("article", "review-candidate"); article.append(element("strong", "", result.title || result.scope_id || candidate.scope_id || "Validated scope"), element("p", "", result.summary || `${String(candidate.status || "candidate").replaceAll("_", " ")} · evidence-bounded`)); const claims = result.claims || result.organization_result?.groups?.flatMap((group) => group.claims || []) || []; for (const claim of claims) article.append(element("span", "candidate-claim", claim.text || claim.claim || String(claim))); if (candidate.correction || result.correction) article.append(element("span", "correction", "Reviewer correction included")); if (candidate.pinned || result.pinned) article.append(element("span", "pin", "Pinned")); host.append(article); }
  if (!host.children.length) host.append(element("p", "muted", "No reviewable groups were returned.")); $("#applyAssembly").disabled = !state.assemblyId; $("#reviewDialog").showModal();
}

async function showDiagnostics() { try { const data = await api.diagnostics(); const host = $("#diagnosticsContent"); host.replaceChildren(); for (const [label, value] of Object.entries(data)) { const row = element("div", "diagnostic-row"); row.append(element("strong", "", label.replaceAll("_", " ")), element("span", "", Array.isArray(value) ? value.join(" · ") : value)); host.append(row); } $("#diagnosticsDialog").showModal(); } catch (error) { toast(error.message); } }

function bind() {
  $$('[data-open-kind]').forEach((button) => button.addEventListener("click", () => choose(button.dataset.openKind)));
  $("#homeButton").addEventListener("click", () => showPrimary("welcome"));
  $("#refreshProject").addEventListener("click", async () => {
    const started = await api.refresh(); const initial = started.analysis || started.task || started;
    if (!["running", "pending"].includes(initial.state)) { toast("Refresh did not start"); return; }
    showPrimary("progress"); const completed = await pollAnalysis(); if (["complete", "completed"].includes(completed.state)) toast("Project refreshed locally");
  });
  $("#cancelAnalysis").addEventListener("click", async () => { await api.cancelAnalysis(); await pollAnalysis(); });
  $("#searchInput").addEventListener("input", () => {
    clearTimeout(searchM10WholeGraph.timer);
    searchM10WholeGraph.timer = setTimeout(() => searchM10WholeGraph().catch((error) => toast(error.message)), 180);
  });
  $("#filterButton").addEventListener("click", () => { const panel = $("#filterPanel"); panel.hidden = !panel.hidden; $("#filterButton").setAttribute("aria-expanded", String(!panel.hidden)); });
  for (const [id, key] of [["technicalToggle", "include_technical"], ["unresolvedToggle", "include_unresolved"]]) $("#" + id).addEventListener("change", (event) => { state.settings[key] = event.target.checked; renderMap(); api.saveSettings(state.settings).catch(() => {}); });
  $("#aiMapButton").addEventListener("click", () => switchMode("ai")); $("#inspectionMapButton").addEventListener("click", () => switchMode("inspection")); $("#canonicalMapButton").addEventListener("click", () => switchMode("canonical")); $("#technicalMapButton").addEventListener("click", () => switchMode("technical"));
  $("#previousPage").addEventListener("click", previousRoutePage); $("#nextPage").addEventListener("click", nextRoutePage);
  $("#zoomIn").addEventListener("click", () => { $("#zoomValue").textContent = `${Math.round(graph.zoomBy(.1) * 100)}%`; }); $("#zoomOut").addEventListener("click", () => { $("#zoomValue").textContent = `${Math.round(graph.zoomBy(-.1) * 100)}%`; }); $("#fitMap").addEventListener("click", () => { graph.fit(); $("#zoomValue").textContent = `${Math.round(graph.scale * 100)}%`; });
  $("#backToRouteMap").addEventListener("click", () => { showLevel("route_map"); graph.world.querySelector(`[data-element-id="${CSS.escape(state.selectedId || "")}"]`)?.focus(); }); $("#detailView").addEventListener("keydown", (event) => { if (event.key === "Escape") $("#backToRouteMap").click(); });
  $("#canonicalEscapeButton").addEventListener("click", openCanonicalRecord);
  $("#selectVisibleNodes").addEventListener("click", async () => { try { await selectVisibleForAI(); toast("Exact provider-free preview ready"); } catch (error) { toast(error.message); } });
  $("#organizeButton").addEventListener("click", prepareOrganization); $("#resumeOrganization").addEventListener("click", async () => { state.prepared = null; await prepareOrganization(); });
  $("#confirmOrganization").addEventListener("click", async (event) => { event.preventDefault(); $("#consentDialog").close(); await startOrganization(); });
  $("#cancelOrganization").addEventListener("click", async () => { state.organization = await api.cancelOrganization(); renderOrganization(); toast("Run cancelling; validated scopes are preserved"); });
  $("#reviewPartial").addEventListener("click", showReview); $("#closeReview").addEventListener("click", () => $("#reviewDialog").close());
  $("#discardAssembly").addEventListener("click", async () => { if (!state.assemblyId) { toast("Candidate assembly is unavailable"); return; } try { await api.discardAssembly(state.assemblyId); state.organization = await api.organization(); renderOrganization(); $("#reviewDialog").close(); toast("Candidate discarded from the project"); } catch (error) { toast(error.message); } });
  $("#applyAssembly").addEventListener("click", async () => { state.organization = await api.applyAssembly(state.assemblyId); $("#reviewDialog").close(); await resetRoutePaging(); renderOrganization(); toast("Candidate applied; AI Story Map is now the default"); });
  $("#diagnosticsButton").addEventListener("click", showDiagnostics); $("#closeDiagnostics").addEventListener("click", () => $("#diagnosticsDialog").close());
  $("#settingsButton").addEventListener("click", () => { const choices = ["system", "light", "dark"]; state.settings.theme = choices[(choices.indexOf(state.settings.theme) + 1) % choices.length]; document.documentElement.dataset.theme = state.settings.theme; graph.draw(); api.saveSettings(state.settings).catch(() => {}); });
  $("#quitButton").addEventListener("click", async () => { await api.shutdown(); document.body.replaceChildren(element("main", "shutdown-message", "Story Mapper has closed. You can close this tab.")); });
  document.addEventListener("keydown", (event) => { if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) { event.preventDefault(); $("#searchInput").focus(); } });
}

async function start() {
  bind();
  try { const bootstrap = await api.bootstrap(); state.settings = { ...state.settings, ...(bootstrap.settings || {}) }; document.documentElement.dataset.theme = state.settings.theme; $("#technicalToggle").checked = state.settings.include_technical; $("#unresolvedToggle").checked = state.settings.include_unresolved; renderRecent(bootstrap.recent_projects || []); showPrimary("welcome"); } catch (error) { renderRecent([]); toast(error.message); }
}

start();
export { api, graph, state, element, normalizedPage, loadOrganization };
