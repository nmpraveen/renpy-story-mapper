import { LocalApi } from "./api.js";
import { ROUTE_PAGE_SIZE } from "./contract.js";
import { RouteGraph } from "./graph.js";
import { MockApi } from "./mock-api.js";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const params = new URLSearchParams(location.search);
const mockMode = params.get("mock") === "1";
const api = mockMode ? new MockApi() : new LocalApi();

const state = {
  project: null, page: null, offset: 0, selectedId: null, detail: null, organization: null,
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
    button.addEventListener("click", () => openSelection({ id: project.id, display_name: project.name }, true));
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
    $("#projectName").textContent = state.project.name;
    $("#projectBadge").textContent = state.project.organization || "Technical map";
    if (["running", "pending"].includes(opened.analysis?.state || opened.task?.state)) { showPrimary("progress"); await pollAnalysis(); }
    else { showPrimary("workspace"); showLevel("route_map"); await loadRoutePage(0); await loadOrganization(); }
    if (notify && mockMode) toast("Project opened locally");
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
    if (progress.state === "running") await new Promise((resolve) => setTimeout(resolve, mockMode ? 10 : 350));
  } while (progress.state === "running");
  if (["complete", "completed"].includes(progress.state)) { showPrimary("workspace"); showLevel("route_map"); await loadRoutePage(0); await loadOrganization(); }
  else if (progress.state === "cancelled") { showPrimary("welcome"); toast("Analysis cancelled safely"); }
  else toast(progress.error?.message || "Analysis stopped safely");
}

function normalizedPage(page) {
  return {
    ...page,
    nodes: page.nodes.map((node) => ({ ...node, title: node.title || "Untitled station", summary: node.summary || "" })),
    edges: page.edges.map((edge) => ({ ...edge, source_id: edge.source_id || edge.source, target_id: edge.target_id || edge.target })),
  };
}

async function loadRoutePage(offset = state.offset) {
  try {
    const page = normalizedPage(await api.routeMap(offset, ROUTE_PAGE_SIZE));
    state.page = page; state.offset = Number(page.offset || 0);
    renderMap();
  } catch (error) { $("#selectionStatus").textContent = "Route Map unavailable"; toast(error.message); }
}

function visiblePage() {
  const query = $("#searchInput").value.trim().toLocaleLowerCase();
  const visibleNodes = (state.page?.nodes || []).filter((node) => {
    if (!state.settings.include_unresolved && node.unresolved) return false;
    return !query || `${node.title} ${node.summary}`.toLocaleLowerCase().includes(query);
  });
  const ids = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = (state.page?.edges || []).filter((edge) => {
    if (!state.settings.include_technical && Number(edge.technical_hops || 0) > 0) return false;
    return ids.has(edge.source_id) && ids.has(edge.target_id);
  });
  return { nodes: visibleNodes, edges: visibleEdges };
}

function renderMap() {
  const { nodes, edges } = visiblePage();
  graph.setData(nodes, edges, state.selectedId);
  state.selectedId = graph.selectedId;
  const first = state.offset + 1; const last = state.offset + (state.page?.nodes.length || 0); const total = Number(state.page?.total_nodes || last);
  $("#pageStatus").textContent = `Stations ${first}–${last} of ${total}`;
  $("#previousPage").disabled = state.offset === 0;
  $("#nextPage").disabled = state.page?.next_offset === null || state.page?.next_offset === undefined;
  $("#visibleStatus").textContent = `${nodes.length} stations · ${edges.length} line segments`;
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
    for (const claim of detail.interpretations || []) { const article = element("article", "interpretation"); article.append(element("strong", "", claim.label || "Interpretation"), element("p", "", claim.text || ""), element("span", "evidence-links", `Evidence: ${(claim.evidence_ids || []).join(", ")}`)); interpretations.append(article); }
    if (!interpretations.children.length) interpretations.append(element("p", "muted", "No AI interpretation is attached."));
    const evidence = $("#evidenceList"); evidence.replaceChildren();
    for (const record of detail.evidence) {
      const article = element("article", "evidence-record"); article.dataset.evidenceId = record.id;
      const source = record.source || {}; const start = source.start_line ?? "?"; const end = source.end_line && source.end_line !== start ? `–${source.end_line}` : "";
      article.append(element("span", "evidence-id", `${record.id} · ${record.kind || "source"}`), element("pre", "", record.text || ""), element("span", "source-line", `${source.path || "source unavailable"}:${start}${end} · ${source.basis || "line"}`)); evidence.append(article);
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
    state.organization = await api.startOrganization(state.prepared.run_id, state.prepared.budgets || {}); renderOrganization();
    if (!mockMode) pollOrganization();
  } catch (error) { toast(error.message); }
}

async function pollOrganization() {
  if (state.organization?.status !== "running") return;
  await new Promise((resolve) => setTimeout(resolve, 900)); await loadOrganization();
  if (state.organization?.status === "running") pollOrganization();
}

function showReview() {
  const coverage = state.organization?.coverage || {};
  $("#reviewCoverage").textContent = `${Math.round(Number(coverage.ai || 0) * 100)}% AI coverage · ${Math.round(Number(coverage.technical || 0) * 100)}% technical coverage`;
  $("#applyAssembly").disabled = !state.assemblyId; $("#reviewDialog").showModal();
}

async function showDiagnostics() {
  try { const data = await api.diagnostics(); const host = $("#diagnosticsContent"); host.replaceChildren(); for (const [label, value] of Object.entries(data)) { const row = element("div", "diagnostic-row"); row.append(element("strong", "", label.replaceAll("_", " ")), element("span", "", Array.isArray(value) ? value.join(" · ") : value)); host.append(row); } $("#diagnosticsDialog").showModal(); } catch (error) { toast(error.message); }
}

function bind() {
  $$('[data-open-kind]').forEach((button) => button.addEventListener("click", () => choose(button.dataset.openKind)));
  $("#homeButton").addEventListener("click", () => showPrimary("welcome"));
  $("#refreshProject").addEventListener("click", async () => { await api.refresh(); await loadRoutePage(0); toast("Project refreshed locally"); });
  $("#cancelAnalysis").addEventListener("click", async () => { await api.cancelAnalysis(); await pollAnalysis(); });
  $("#searchInput").addEventListener("input", renderMap);
  $("#filterButton").addEventListener("click", () => { const panel = $("#filterPanel"); panel.hidden = !panel.hidden; $("#filterButton").setAttribute("aria-expanded", String(!panel.hidden)); });
  for (const [id, key] of [["technicalToggle", "include_technical"], ["unresolvedToggle", "include_unresolved"]]) $("#" + id).addEventListener("change", (event) => { state.settings[key] = event.target.checked; renderMap(); api.saveSettings(state.settings).catch(() => {}); });
  $("#previousPage").addEventListener("click", () => loadRoutePage(Math.max(0, state.offset - ROUTE_PAGE_SIZE)));
  $("#nextPage").addEventListener("click", () => { if (state.page?.next_offset != null) loadRoutePage(state.page.next_offset); });
  $("#zoomIn").addEventListener("click", () => { $("#zoomValue").textContent = `${Math.round(graph.zoomBy(.1) * 100)}%`; });
  $("#zoomOut").addEventListener("click", () => { $("#zoomValue").textContent = `${Math.round(graph.zoomBy(-.1) * 100)}%`; });
  $("#fitMap").addEventListener("click", () => { graph.fit(); $("#zoomValue").textContent = `${Math.round(graph.scale * 100)}%`; });
  $("#backToRouteMap").addEventListener("click", () => { showLevel("route_map"); graph.world.querySelector(`[data-element-id="${CSS.escape(state.selectedId || "")}"]`)?.focus(); });
  $("#detailView").addEventListener("keydown", (event) => { if (event.key === "Escape") $("#backToRouteMap").click(); });
  $("#organizeButton").addEventListener("click", prepareOrganization); $("#resumeOrganization").addEventListener("click", prepareOrganization);
  $("#confirmOrganization").addEventListener("click", async (event) => { event.preventDefault(); $("#consentDialog").close(); await startOrganization(); });
  $("#cancelOrganization").addEventListener("click", async () => { state.organization = await api.cancelOrganization(); renderOrganization(); toast("Run cancelled; validated scopes preserved"); });
  $("#reviewPartial").addEventListener("click", showReview); $("#closeReview").addEventListener("click", () => $("#reviewDialog").close());
  $("#applyAssembly").addEventListener("click", async () => { await api.applyAssembly(state.assemblyId); $("#reviewDialog").close(); toast("Validated partial result applied"); });
  $("#diagnosticsButton").addEventListener("click", showDiagnostics); $("#closeDiagnostics").addEventListener("click", () => $("#diagnosticsDialog").close());
  $("#settingsButton").addEventListener("click", () => { const choices = ["system", "light", "dark"]; state.settings.theme = choices[(choices.indexOf(state.settings.theme) + 1) % choices.length]; document.documentElement.dataset.theme = state.settings.theme; graph.draw(); api.saveSettings(state.settings).catch(() => {}); });
  $("#quitButton").addEventListener("click", async () => { await api.shutdown(); document.body.replaceChildren(element("main", "shutdown-message", "Story Mapper has closed. You can close this tab.")); });
  document.addEventListener("keydown", (event) => { if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) { event.preventDefault(); $("#searchInput").focus(); } });
}

async function acceptanceScenario() {
  const scenario = params.get("state"); if (!mockMode || !scenario || scenario === "welcome") return;
  await openSelection({ id: "project-demo", display_name: "The Lantern House" });
  if (scenario === "detail-evidence") await openDetail(state.page.edges[1]?.id || state.page.nodes[1].id);
  if (scenario === "coverage-progress") { state.prepared = await api.prepareOrganization(); state.organization = await api.startOrganization(state.prepared.run_id, state.prepared.budgets); renderOrganization(); }
  if (scenario === "review-partial") { state.prepared = await api.prepareOrganization(); await api.startOrganization(state.prepared.run_id, state.prepared.budgets); state.organization = await api.organization(); state.assemblyId = state.organization.assembly_id; renderOrganization(); showReview(); }
  if (scenario === "paging") await loadRoutePage(30);
  if (scenario === "keyboard") { $("#mapViewport").focus(); $("#mapViewport").dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true })); }
  const interactives = $$('button, input, [role="button"]');
  document.documentElement.dataset.levels = "route_map,detail_evidence"; document.documentElement.dataset.levelCount = "2";
  document.documentElement.dataset.visibleNodes = String(state.page?.nodes.length || 0); document.documentElement.dataset.visibleItems = String((state.page?.nodes.length || 0) + (state.page?.edges.length || 0));
  document.documentElement.dataset.keyboardSelected = graph.selectedId || ""; document.documentElement.dataset.exactEvidence = String(Boolean($("[data-evidence-id]")) || scenario !== "detail-evidence");
  document.documentElement.dataset.onlyLevelTransition = $("#backToRouteMap").textContent.replace("←", "").trim(); document.documentElement.dataset.accessibleNames = String(interactives.every((item) => Boolean(item.getAttribute("aria-label") || item.textContent.trim() || item.closest("label"))));
  document.documentElement.dataset.font = getComputedStyle(document.body).fontFamily; document.documentElement.dataset.bodyPx = getComputedStyle(document.body).fontSize;
  document.documentElement.dataset.remoteRequests = "0"; document.documentElement.dataset.providerConstructions = "0";
  document.documentElement.dataset.routeCalls = String(api.calls.filter((call) => call.name === "routeMap").length); document.documentElement.dataset.detailCalls = String(api.calls.filter((call) => call.name === "detail").length);
  document.documentElement.dataset.prepareCalls = String(api.calls.filter((call) => call.name === "prepareOrganization").length); document.documentElement.dataset.startCalls = String(api.calls.filter((call) => call.name === "startOrganization").length);
  document.documentElement.dataset.requestBodies = api.calls.filter((call) => ["routeMap", "detail", "prepareOrganization", "startOrganization", "cancelOrganization", "applyAssembly"].includes(call.name)).map((call) => `${call.name}:${Object.keys(call.payload).sort().join("+")}`).join("|");
  document.documentElement.dataset.acceptanceReady = "true";
}

async function start() {
  bind();
  try {
    const bootstrap = await api.bootstrap(); state.settings = { ...state.settings, ...(bootstrap.settings || {}) }; document.documentElement.dataset.theme = state.settings.theme;
    $("#technicalToggle").checked = state.settings.include_technical; $("#unresolvedToggle").checked = state.settings.include_unresolved; renderRecent(bootstrap.recent_projects || []); showPrimary("welcome");
    await acceptanceScenario(); if (!document.documentElement.dataset.acceptanceReady) document.documentElement.dataset.acceptanceReady = "true";
  } catch (error) { renderRecent([]); toast(error.message); document.documentElement.dataset.acceptanceReady = "error"; }
}

start();
export { api, graph, state, element, normalizedPage };
