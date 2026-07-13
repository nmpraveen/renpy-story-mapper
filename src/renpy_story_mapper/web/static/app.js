import { LocalApi } from "./api.js";
import { ROUTE_EDGE_PAGE_SIZE, ROUTE_PAGE_SIZE } from "./contract.js";
import { RouteGraph } from "./graph.js";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const api = new LocalApi();
const CURSOR_HISTORY_LIMIT = 12;

const state = {
  project: null, page: null, offset: 0, edgeOffset: 0, cursorHistory: [], selectedId: null,
  detail: null, organization: null,
  prepared: null, assemblyId: null, settings: { theme: "system", include_technical: true, include_unresolved: true },
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
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { host.hidden = true; }, 2600);
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
    button.append(element("span", "recent-type", project.source_type || "Project"), element("strong", "", project.name || "Saved project"), element("span", "recent-meta", `${project.last_opened || "Saved locally"} · ${project.organization || "Technical map"}`));
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
      state.project = { name: source.display_name || "New story", organization: "Technical map" };
      showPrimary("progress"); await pollAnalysis();
    }
  } catch (error) { toast(error.message); }
}

async function openSelection(selection, notify = false) {
  try {
    const opened = await api.open(selection.selection_id || selection.id);
    state.project = opened.project || { name: selection.display_name || "Story", organization: "Technical map" };
    if (state.project.name === "Opening") state.project.name = selection.display_name || "Story";
    $("#projectName").textContent = state.project.name;
    $("#projectBadge").textContent = state.project.organization || "Technical map";
    if (["running", "pending"].includes(opened.analysis?.state || opened.task?.state)) { showPrimary("progress"); await pollAnalysis(); }
    else { showPrimary("workspace"); showLevel("route_map"); await resetRoutePaging(); await loadOrganization(); }
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
  if (["complete", "completed"].includes(progress.state)) { showPrimary("workspace"); showLevel("route_map"); await resetRoutePaging(); await loadOrganization(); }
  else if (progress.state === "cancelled") { showPrimary("welcome"); toast("Analysis cancelled safely"); }
  else toast(progress.error?.message || "Analysis stopped safely");
  return progress;
}

function normalizedPage(page) {
  return {
    ...page,
    nodes: page.nodes.map((node) => ({ ...node, title: node.title || "Untitled station", summary: node.summary || "" })),
    edges: page.edges.map((edge) => ({ ...edge, source_id: edge.source_id || edge.source, target_id: edge.target_id || edge.target })),
  };
}

async function loadRoutePage(cursor = { offset: state.offset, edgeOffset: state.edgeOffset }) {
  try {
    const page = normalizedPage(await api.routeMap(
      cursor.offset, ROUTE_PAGE_SIZE, cursor.edgeOffset, ROUTE_EDGE_PAGE_SIZE,
    ));
    state.page = page;
    state.offset = Number(page.offset || 0);
    state.edgeOffset = Number(page.edge_offset || 0);
    renderMap();
  } catch (error) { $("#selectionStatus").textContent = "Route Map unavailable"; toast(error.message); }
}

async function resetRoutePaging() {
  state.cursorHistory = [];
  await loadRoutePage({ offset: 0, edgeOffset: 0 });
}

function nextCursor() {
  const navigation = state.page?.global_navigation || state.page?.navigation || {};
  if (navigation.next && Number.isInteger(navigation.next.offset)) {
    return { offset: navigation.next.offset, edgeOffset: navigation.next.edge_offset || 0 };
  }
  if (state.page?.edge_next_offset !== null && state.page?.edge_next_offset !== undefined) {
    return { offset: state.offset, edgeOffset: Number(state.page.edge_next_offset) };
  }
  if (state.page?.next_offset !== null && state.page?.next_offset !== undefined) {
    return { offset: Number(state.page.next_offset), edgeOffset: 0 };
  }
  return null;
}

async function nextRoutePage() {
  const target = nextCursor();
  if (!target) return;
  state.cursorHistory.push({ offset: state.offset, edgeOffset: state.edgeOffset });
  if (state.cursorHistory.length > CURSOR_HISTORY_LIMIT) state.cursorHistory.shift();
  await loadRoutePage(target);
}

async function previousRoutePage() {
  const target = state.cursorHistory.pop();
  if (target) await loadRoutePage(target);
}

function visiblePage() {
  const query = $("#searchInput").value.trim().toLocaleLowerCase();
  const globalSearch = state.page?.global_search || state.page?.search;
  const matchedIds = query && globalSearch?.query === query && Array.isArray(globalSearch.element_ids) ? new Set(globalSearch.element_ids) : null;
  const visibleNodes = (state.page?.nodes || []).filter((node) => {
    if (!state.settings.include_unresolved && node.unresolved) return false;
    return !query || matchedIds?.has(node.id) || `${node.title} ${node.summary}`.toLocaleLowerCase().includes(query);
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
  for (const node of nodes) if (!metadata.has(node.lane_id)) metadata.set(node.lane_id, { id: node.lane_id, kind: node.lane_kind });
  for (const lane of metadata.values()) {
    const row = element("div", "line-key");
    const swatch = element("i", "swatch");
    let hash = 2166136261; for (const character of String(lane.id)) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
    swatch.style.setProperty("--lane-hue", String(Math.abs(hash) % 360));
    row.append(swatch, element("span", "", `${lane.id} · ${String(lane.kind || "route").replaceAll("_", " ")}`));
    host.append(row);
  }
}

function renderMap() {
  const { nodes, edges } = visiblePage();
  graph.setData(nodes, edges, state.selectedId, state.page?.lanes || []);
  renderLanes(nodes);
  state.selectedId = graph.selectedId;
  const first = state.offset + 1; const last = state.offset + (state.page?.nodes.length || 0); const total = Number(state.page?.total_nodes || last);
  const edgeFirst = state.edgeOffset + 1;
  const edgeLast = state.edgeOffset + (state.page?.edges.length || 0);
  const edgeTotal = Number(state.page?.page_edge_total ?? edgeLast);
  const dense = Boolean(state.page?.overflow) || edgeTotal > state.page?.edges.length;
  const lineStatus = edgeTotal ? `Lines ${edgeFirst}–${edgeLast} of ${edgeTotal}` : "No lines";
  $("#pageStatus").textContent = `Stations ${first}–${last} of ${total} · ${lineStatus}${dense ? " · bounded line slice" : ""}`;
  $("#previousPage").disabled = state.cursorHistory.length === 0;
  $("#nextPage").disabled = nextCursor() === null;
  const nodeIds = new Set(nodes.map((node) => node.id));
  const continuations = edges.filter((edge) => !nodeIds.has(edge.source_id) || !nodeIds.has(edge.target_id)).length;
  $("#visibleStatus").textContent = `${nodes.length} stations · ${edges.length} line segments${continuations ? ` · ${continuations} continuations` : ""}${dense ? ` shown from ${edgeTotal}` : ""}`;
  const coverage = state.page?.coverage || {};
  $("#coverageSummary").replaceChildren(element("strong", "", "Technical coverage"), element("span", "", `${coverage.control_nodes ?? "—"} control points`), element("span", "", `${coverage.technical_nodes ?? 0} collapsed steps · ${coverage.corridor_count ?? 0} corridor`));
  const selected = graph.elements().find((item) => item.id === state.selectedId); if (selected) selectItem(selected);
}

function selectItem(item) {
  state.selectedId = item.id;
  const label = item.title || String(item.role || item.kind || "route segment").replaceAll("_", " ");
  $("#selectionStatus").textContent = `${label} · Enter for Detail / Evidence`;
}

function addFactGroup(host, title, items, type) {
  if (!items?.length) return;
  const section = element("section", "fact-group"); section.append(element("h2", "", title));
  const list = element("ul", "fact-list");
  for (const item of items) { const row = element("li", `fact ${type}`); row.append(element("span", "fact-shape", type === "gate" ? "△" : "＋"), element("strong", "", item.label || item.caption || item.text || item.id), element("code", "", item.expression || "")); list.append(row); }
  section.append(list); host.append(section);
}

function evidenceExcerpt(record) {
  const payload = record.payload || {};
  const provenance = Array.isArray(payload.provenance) ? payload.provenance.map((item) => item.source_text).filter(Boolean) : [];
  const choices = Array.isArray(payload.choices) ? payload.choices.map((item) => item.condition ? `“${item.caption}” if ${item.condition}` : `“${item.caption}”`) : [];
  return provenance.join("\n") || choices.join("\n") || record.text || record.excerpt || record.source_text || "Evidence text unavailable";
}

async function openDetail(elementId) {
  try {
    const detail = await api.detail(elementId); state.detail = detail; state.selectedId = elementId;
    const selected = detail.element; $("#detailTitle").textContent = selected.title || String(selected.role || selected.kind || "Route element").replaceAll("_", " ");
    $("#detailKind").textContent = selected.kind || selected.role || "route element";
    $("#detailSummary").textContent = selected.summary || "Authoritative local context and exact source evidence for this route element.";
    const strip = $("#pathStrip"); strip.replaceChildren();
    for (const id of detail.predecessor_ids || []) strip.append(element("span", "path-stop predecessor", `← ${titleFor(id)}`));
    strip.append(element("strong", "path-stop current", $("#detailTitle").textContent));
    for (const id of detail.successor_ids || []) strip.append(element("span", "path-stop successor", `${titleFor(id)} →`));
    const facts = $("#detailFacts"); facts.replaceChildren();
    addFactGroup(facts, "Exact choices", detail.choices, "choice"); addFactGroup(facts, "Requirements", detail.gates || detail.requirements, "gate"); addFactGroup(facts, "Effects", detail.effects, "effect"); addFactGroup(facts, "Dialogue", detail.dialogue, "dialogue"); addFactGroup(facts, "Narration", detail.narration, "narration");
    const interpretations = $("#interpretations"); interpretations.replaceChildren();
    const candidates = detail.ai_candidates || detail.candidates || selected.ai_candidates || [];
    const claims = detail.claims || candidates.flatMap((candidate) => candidate.claims || []);
    for (const candidate of candidates) {
      const article = element("article", "interpretation candidate");
      article.append(element("strong", "", candidate.title || candidate.label || "Candidate"), element("p", "", candidate.summary || candidate.text || ""));
      if (candidate.correction) article.append(element("span", "correction", `Correction: ${candidate.correction.title || candidate.correction.text || "provided"}`));
      if (candidate.pinned) article.append(element("span", "pin", "Pinned by reviewer"));
      interpretations.append(article);
    }
    for (const claim of claims) {
      const article = element("article", "interpretation claim");
      article.append(element("strong", "", claim.label || "Claim"), element("p", "", claim.text || claim.claim || ""), element("span", "evidence-links", `Evidence: ${(claim.evidence_ids || []).join(", ") || "not supplied"}`));
      interpretations.append(article);
    }
    if (!interpretations.children.length) interpretations.append(element("p", "muted", "No AI candidate is attached. The technical map is authoritative."));
    const evidence = $("#evidenceList"); evidence.replaceChildren();
    for (const record of detail.evidence) {
      const article = element("article", "evidence-record"); article.dataset.evidenceId = record.id;
      const source = record.source || record.location || {}; const start = source.start?.line ?? source.start_line ?? record.start_line ?? "?"; const endLine = source.end?.line ?? source.end_line ?? record.end_line; const end = endLine && endLine !== start ? `–${endLine}` : "";
      const excerpt = evidenceExcerpt(record);
      article.append(element("span", "evidence-id", `${record.id} · ${record.kind || "source"}`), element("pre", "", excerpt), element("span", "source-line", `${source.path || record.path || "source unavailable"}:${start}${end} · ${source.basis || record.basis || "line"}`)); evidence.append(article);
    }
    if (!evidence.children.length) evidence.append(element("p", "muted", "No exact evidence was returned."));
    showLevel("detail_evidence"); $("#backToRouteMap").focus();
  } catch (error) { toast(error.message); }
}

function titleFor(id) { return state.page?.nodes.find((node) => node.id === id)?.title || id; }

async function loadOrganization() {
  try { state.organization = await api.organization(); renderOrganization(); } catch (error) { $("#organizationMetrics").replaceChildren(element("p", "muted", "Organization unavailable. The technical Route Map remains usable.")); }
}

function renderOrganization() {
  const value = state.organization || {}; const scopes = value.scopes || {}; const tokens = value.tokens || {}; const coverage = value.coverage || {}; const eta = value.eta || {};
  const host = $("#organizationMetrics"); host.replaceChildren();
  const rows = [
    ["Status", String(value.status || "idle").replaceAll("_", " ")], ["Scopes", `${scopes.validated || 0} validated · ${scopes.fallback || 0} technical · ${scopes.pending || 0} pending`],
    ["Usage", `${value.calls || 0} calls · ${Number(tokens.used || 0).toLocaleString()} / ${Number(tokens.budget || 0).toLocaleString()} tokens`],
    ["Coverage", `${Math.round(Number(coverage.ai || 0) * 100)}% AI · ${Math.round(Number(coverage.technical || 0) * 100)}% technical`],
    ["ETA", eta.low_seconds == null ? "Not running" : `${Math.ceil(eta.low_seconds / 60)}–${Math.ceil(eta.high_seconds / 60)} min`],
  ];
  for (const [label, text] of rows) { const row = element("div", "metric"); row.append(element("span", "", label), element("strong", "", text)); host.append(row); }
  $("#cancelOrganization").hidden = value.status !== "running";
  $("#resumeOrganization").hidden = !["cancelled", "partial"].includes(value.status);
  $("#reviewPartial").hidden = !value.assembly_id;
  if (value.assembly_id) state.assemblyId = value.assembly_id;
}

async function prepareOrganization() {
  try {
    state.prepared = await api.prepareOrganization();
    const facts = $("#consentFacts"); facts.replaceChildren();
    const budgets = state.prepared.budgets || {};
    for (const [label, value] of [["Scopes", state.prepared.scopes || "Prepared"], ["Cached", state.prepared.cached || 0], ["Token budget", budgets.hard_tokens || "Server limit"], ["Call budget", budgets.hard_calls || "Server limit"]]) { facts.append(element("dt", "", label), element("dd", "", value)); }
    $("#consentDialog").showModal();
  } catch (error) { toast(error.message); }
}

async function startOrganization() {
  if (!state.prepared?.run_id) { toast("Prepared run is unavailable"); return; }
  try {
    state.organization = await api.startOrganization(state.prepared); renderOrganization();
    pollOrganization();
  } catch (error) { toast(error.message); }
}

async function pollOrganization() {
  const active = new Set(["running", "starting", "cancelling", "queued"]);
  while (active.has(state.organization?.status)) {
    await new Promise((resolve) => setTimeout(resolve, 900));
    await loadOrganization();
  }
  if (["complete", "partial", "review", "applied", "cancelled", "failed"].includes(state.organization?.status)) renderOrganization();
}

function showReview() {
  const coverage = state.organization?.coverage || {};
  $("#reviewCoverage").textContent = `${Math.round(Number(coverage.ai || 0) * 100)}% AI coverage · ${Math.round(Number(coverage.technical || 0) * 100)}% technical coverage`;
  const host = $("#reviewCandidates"); host.replaceChildren();
  const candidates = state.organization?.candidates || state.organization?.assembly?.items || [];
  for (const candidate of candidates) {
    const result = candidate.result || candidate;
    const article = element("article", "review-candidate");
    article.append(element("strong", "", result.title || result.scope_id || candidate.scope_id || "Validated scope"), element("p", "", result.summary || "Evidence-bounded candidate"));
    const claims = result.claims || result.organization_result?.groups?.flatMap((group) => group.claims || []) || [];
    for (const claim of claims) article.append(element("span", "candidate-claim", claim.text || claim.claim || String(claim)));
    if (candidate.correction || result.correction) article.append(element("span", "correction", "Reviewer correction included"));
    if (candidate.pinned || result.pinned) article.append(element("span", "pin", "Pinned"));
    host.append(article);
  }
  if (!host.children.length) host.append(element("p", "muted", "The backend returned coverage metadata only; candidate content is not exposed."));
  $("#applyAssembly").disabled = !state.assemblyId; $("#reviewDialog").showModal();
}

async function showDiagnostics() {
  try { const data = await api.diagnostics(); const host = $("#diagnosticsContent"); host.replaceChildren(); for (const [label, value] of Object.entries(data)) { const row = element("div", "diagnostic-row"); row.append(element("strong", "", label.replaceAll("_", " ")), element("span", "", Array.isArray(value) ? value.join(" · ") : value)); host.append(row); } $("#diagnosticsDialog").showModal(); } catch (error) { toast(error.message); }
}

function bind() {
  $$('[data-open-kind]').forEach((button) => button.addEventListener("click", () => choose(button.dataset.openKind)));
  $("#homeButton").addEventListener("click", () => showPrimary("welcome"));
  $("#refreshProject").addEventListener("click", async () => {
    const started = await api.refresh();
    const initial = started.analysis || started.task || started;
    if (!["running", "pending"].includes(initial.state)) { toast("Refresh did not start"); return; }
    showPrimary("progress");
    const completed = await pollAnalysis();
    if (["complete", "completed"].includes(completed.state)) toast("Project refreshed locally");
  });
  $("#cancelAnalysis").addEventListener("click", async () => { await api.cancelAnalysis(); await pollAnalysis(); });
  $("#searchInput").addEventListener("input", renderMap);
  $("#filterButton").addEventListener("click", () => { const panel = $("#filterPanel"); panel.hidden = !panel.hidden; $("#filterButton").setAttribute("aria-expanded", String(!panel.hidden)); });
  for (const [id, key] of [["technicalToggle", "include_technical"], ["unresolvedToggle", "include_unresolved"]]) $("#" + id).addEventListener("change", (event) => { state.settings[key] = event.target.checked; renderMap(); api.saveSettings(state.settings).catch(() => {}); });
  $("#previousPage").addEventListener("click", previousRoutePage);
  $("#nextPage").addEventListener("click", nextRoutePage);
  $("#zoomIn").addEventListener("click", () => { $("#zoomValue").textContent = `${Math.round(graph.zoomBy(.1) * 100)}%`; });
  $("#zoomOut").addEventListener("click", () => { $("#zoomValue").textContent = `${Math.round(graph.zoomBy(-.1) * 100)}%`; });
  $("#fitMap").addEventListener("click", () => { graph.fit(); $("#zoomValue").textContent = `${Math.round(graph.scale * 100)}%`; });
  $("#backToRouteMap").addEventListener("click", () => { showLevel("route_map"); graph.world.querySelector(`[data-element-id="${CSS.escape(state.selectedId || "")}"]`)?.focus(); });
  $("#detailView").addEventListener("keydown", (event) => { if (event.key === "Escape") $("#backToRouteMap").click(); });
  $("#organizeButton").addEventListener("click", prepareOrganization); $("#resumeOrganization").addEventListener("click", prepareOrganization);
  $("#confirmOrganization").addEventListener("click", async (event) => { event.preventDefault(); $("#consentDialog").close(); await startOrganization(); });
  $("#cancelOrganization").addEventListener("click", async () => { state.organization = await api.cancelOrganization(); renderOrganization(); toast("Run cancelled; validated scopes preserved"); });
  $("#reviewPartial").addEventListener("click", showReview); $("#closeReview").addEventListener("click", () => $("#reviewDialog").close());
  $("#discardAssembly").addEventListener("click", () => { $("#reviewDialog").close(); toast("Candidate dismissed locally; project unchanged"); });
  $("#applyAssembly").addEventListener("click", async () => { state.organization = await api.applyAssembly(state.assemblyId); $("#reviewDialog").close(); await resetRoutePaging(); renderOrganization(); toast("Candidate applied to the project"); });
  $("#diagnosticsButton").addEventListener("click", showDiagnostics); $("#closeDiagnostics").addEventListener("click", () => $("#diagnosticsDialog").close());
  $("#settingsButton").addEventListener("click", () => { const choices = ["system", "light", "dark"]; state.settings.theme = choices[(choices.indexOf(state.settings.theme) + 1) % choices.length]; document.documentElement.dataset.theme = state.settings.theme; graph.draw(); api.saveSettings(state.settings).catch(() => {}); });
  $("#quitButton").addEventListener("click", async () => { await api.shutdown(); document.body.replaceChildren(element("main", "shutdown-message", "Story Mapper has closed. You can close this tab.")); });
  document.addEventListener("keydown", (event) => { if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) { event.preventDefault(); $("#searchInput").focus(); } });
}

async function start() {
  bind();
  try {
    const bootstrap = await api.bootstrap(); state.settings = { ...state.settings, ...(bootstrap.settings || {}) }; document.documentElement.dataset.theme = state.settings.theme;
    $("#technicalToggle").checked = state.settings.include_technical; $("#unresolvedToggle").checked = state.settings.include_unresolved; renderRecent(bootstrap.recent_projects || []); showPrimary("welcome");
  } catch (error) { renderRecent([]); toast(error.message); }
}

start();
export { api, graph, state, element, normalizedPage };
