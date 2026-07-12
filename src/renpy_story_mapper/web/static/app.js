import { LocalApi } from "./api.js";
import { RENDER_LIMITS, safeLevel } from "./contract.js";
import { StoryGraph } from "./graph.js";
import { MockApi } from "./mock-api.js";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const params = new URLSearchParams(location.search);
const mockMode = params.get("mock") === "1";
const api = mockMode ? new MockApi() : new LocalApi();
const REVIEW_PAGE_SIZE = 40;

const state = {
  project: null,
  level: "arcs",
  selected: null,
  parentIds: [],
  view: null,
  draftId: null,
  reviewCandidates: [],
  reviewPage: 0,
  settings: { theme: "system", zoom: 1, include_technical: false, include_unresolved: true, show_requirements: true, show_effects: true },
};

function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = String(value);
  return node;
}

function normalizeNode(node) {
  const payload = node.payload && typeof node.payload === "object" ? node.payload : {};
  return {
    ...node,
    title: node.title || node.name || "Untitled story item",
    summary: node.summary || payload.summary || payload.text || "",
    evidence_count: node.evidence_count ?? payload.evidence_count ?? 0,
    source: node.source || (node.source_path ? { path: node.source_path, start_line: node.start_line, end_line: node.end_line, basis: payload.line_basis || "physical" } : null),
    facts: Array.isArray(node.facts) ? node.facts : [],
    unresolved: node.unresolved === true,
  };
}

function normalizeView(view) {
  const nodes = (view.nodes || []).map(normalizeNode);
  const edges = (view.edges || []).map((edge) => ({ ...edge, source: edge.source || edge.source_id, target: edge.target || edge.target_id }));
  const nodeMore = Boolean(view.node_continuation?.has_more);
  const edgeMore = Boolean(view.edge_continuation?.has_more);
  return { ...view, nodes, edges, overflow: view.overflow || (nodeMore || edgeMore ? { message: "More story items exist beyond this bounded slice." } : null) };
}

const graph = new StoryGraph({
  viewport: $("#mapViewport"), world: $("#mapWorld"), canvas: $("#edgeCanvas"),
  onSelect: (node) => selectNode(node), onOpen: (node) => openNode(node),
});

function showView(name) {
  $("#welcomeView").hidden = name !== "welcome";
  $("#progressView").hidden = name !== "progress";
  $("#workspaceView").hidden = name !== "workspace";
  $("#projectIdentity").hidden = name === "welcome";
  $("#refreshProject").hidden = name !== "workspace" || !state.project;
}

function toast(message) {
  const target = $("#toast");
  target.textContent = message;
  target.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { target.hidden = true; }, 2600);
}

function renderRecent(projects) {
  const host = $("#recentProjects");
  host.replaceChildren();
  $("#recentCount").textContent = `${projects.length} saved locally`;
  for (const [index, project] of projects.entries()) {
    const card = element("button", "recent-card");
    card.type = "button";
    card.dataset.projectId = project.id;
    card.append(element("span", "eyebrow", `${String(index + 1).padStart(2, "0")} · ${project.source_type}`), element("strong", "", project.name));
    const meta = element("span", "recent-meta");
    meta.append(element("span", "", project.last_opened || "Saved locally"), element("span", "", project.organization));
    card.append(meta);
    card.addEventListener("click", () => openSelection({ id: project.id || project.selection_id, display_name: project.name }, true));
    host.append(card);
  }
  if (!projects.length) host.append(element("p", "inspector-empty", "No recent projects."));
}

async function choose(kind) {
  try {
    const result = await api.pick(kind);
    const selection = result.selection || result;
    if (!selection || !(selection.id || selection.selection_id)) return;
    if (kind === "project") await openSelection(selection, true);
    else await createFromSource(selection);
  } catch (error) { toast(error.message); }
}

async function createFromSource(sourceSelection) {
  const sourceId = sourceSelection.id || sourceSelection.selection_id;
  if (api.create && api.chooseSave) {
    const save = await api.chooseSave();
    const target = save?.selection || save;
    if (!target) return;
    const targetId = target.id || target.selection_id;
    if (!targetId) throw new Error("The project destination is unavailable");
    await api.create(sourceId, targetId);
    state.project = { id: sourceId, name: sourceSelection.display_name || "New story", organization: "Technical organization" };
    showView("progress");
    await pollProgress();
    return;
  }
  await openSelection(sourceSelection, false);
}

async function openSelection(selection, existing) {
  const selectionId = selection.id || selection.selection_id;
  const result = await api.open(selectionId);
  state.project = result.project || { id: selectionId, name: selection.display_name || "The Lantern House", organization: "Technical organization" };
  $("#projectName").textContent = state.project.name;
  $("#projectBadge").textContent = state.project.organization || "Technical organization";
  showView(result.analysis?.state === "running" || result.task?.state === "running" ? "progress" : "workspace");
  if (result.analysis?.state === "running" || result.task?.state === "running") await pollProgress();
  else await loadView();
  if (existing && mockMode) toast("Project opened locally");
}

async function refreshProject() {
  if (!state.project) return;
  try {
    const started = await api.refresh();
    if (started.analysis?.state === "running" || started.task?.state === "running") await pollProgress();
    else await loadView();
    toast("Project refreshed locally");
  } catch (error) {
    toast(error.message);
  }
}

async function pollProgress() {
  showView("progress");
  let result;
  do {
    result = await api.progress();
    result = result.task || result;
    updateProgress(result);
    if (result.state !== "running") break;
    await new Promise((resolve) => setTimeout(resolve, mockMode ? 10 : 400));
  } while (result.state === "running");
  if (result.state === "completed" || result.state === "complete") {
    const bootstrap = await api.bootstrap();
    if (bootstrap.project?.name) {
      state.project = { ...state.project, ...bootstrap.project };
      $("#projectName").textContent = bootstrap.project.name;
    }
    showView("workspace");
    await loadView();
  }
  if (result.state === "cancelled") { showView("welcome"); toast("Analysis cancelled safely"); }
  if (result.state === "failed") { showView("workspace"); toast(result.error?.message || "The operation failed safely"); }
}

function updateProgress(progress) {
  const percent = Math.max(0, Math.min(100, Number(progress.percent || 0)));
  $("#progressStage").textContent = String(progress.stage || "Preparing analysis").replaceAll("_", " ");
  $("#progressBar").style.width = `${percent}%`;
  $(".progress-track").setAttribute("aria-valuenow", String(percent));
  $("#progressPercent").textContent = `${percent}%`;
  const seconds = Number(progress.elapsed_seconds || 0);
  $("#progressElapsed").textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

async function loadView({ preserveSelection = true } = {}) {
  const query = $("#searchInput").value.trim();
  const request = {
    level: state.level,
    parent_ids: state.parentIds,
    selected_id: preserveSelection ? state.selected?.id || null : null,
    query,
    include_technical: state.settings.include_technical,
    include_unresolved: state.settings.include_unresolved,
  };
  try {
    if (query && !mockMode && api.search) {
      const search = await api.search(query);
      request.focus_ids = (search.items || []).slice(0, 80).map((hit) => hit.node_id);
    }
    const response = normalizeView(await api.view(request));
    if (!state.settings.include_unresolved) {
      const allowed = new Set(response.nodes.filter((node) => !node.unresolved).map((node) => node.id));
      response.nodes = response.nodes.filter((node) => allowed.has(node.id));
      response.edges = response.edges.filter((edge) => allowed.has(edge.source) && allowed.has(edge.target));
    }
    state.view = response;
    renderWorkspace();
  } catch (error) {
    $("#overflowStatus").textContent = error instanceof RangeError ? "Safety boundary rejected this view" : "Map unavailable";
    toast(error.message);
  }
}

function renderWorkspace() {
  const view = state.view;
  if (!view) return;
  const labels = { arcs: ["Level 1 · Arcs", "Story overview"], events: ["Level 2 · Events", state.selected?.title || "Story events"], evidence: ["Level 3 · Evidence", state.selected?.title || "Evidence timeline"] };
  $("#levelLabel").textContent = labels[state.level][0];
  $("#mapTitle").textContent = labels[state.level][1];
  renderBreadcrumbs();
  renderNavigator(view.nodes);
  const selectedId = view.nodes.some((node) => node.id === state.selected?.id) ? state.selected.id : view.selected_id;
  graph.setData(view.nodes, view.edges, selectedId);
  $("#visibleStatus").textContent = `${view.nodes.length} nodes · ${view.edges.length} edges · ${view.nodes.length + view.edges.length}/${RENDER_LIMITS.items} items`;
  $("#overflowStatus").textContent = view.overflow?.message || "";
  $("#zoomValue").textContent = `${Math.round(graph.scale * 100)}%`;
  const chosen = view.nodes.find((node) => node.id === graph.selectedId);
  if (chosen) selectNode(chosen, false);
}

function renderBreadcrumbs() {
  const host = $("#breadcrumbs");
  host.replaceChildren();
  const levels = [["arcs", "Arcs"], ["events", "Events"], ["evidence", "Evidence"]];
  for (const [index, [level, label]] of levels.entries()) {
    if (index) host.append(element("span", "", "›"));
    const button = element("button", "breadcrumb", label);
    button.type = "button";
    button.disabled = levels.findIndex(([item]) => item === state.level) < index;
    if (level === state.level) button.setAttribute("aria-current", "page");
    button.addEventListener("click", () => changeLevel(level));
    host.append(button);
    if (level === state.level) break;
  }
}

function renderNavigator(nodes) {
  const host = $("#storyNavigator");
  host.replaceChildren();
  const items = state.level === "arcs" ? nodes : nodes.slice(0, 12);
  for (const [index, node] of items.entries()) {
    const button = element("button", "nav-item");
    button.type = "button";
    button.setAttribute("aria-current", String(node.id === state.selected?.id));
    button.append(element("span", "nav-index", String(index + 1).padStart(2, "0")), element("span", "", node.title), element("span", "nav-count", node.child_count ?? node.evidence_count ?? ""));
    button.addEventListener("click", () => { graph.select(node.id, true); $("#mapViewport").focus(); });
    host.append(button);
  }
}

async function selectNode(node, fetchAuthority = true) {
  state.selected = node;
  $("#selectionKind").textContent = node.kind || "story";
  renderNavigator(state.view?.nodes || []);
  renderInspector(node, node.facts || [], []);
  if (!fetchAuthority) return;
  try {
    const [factsResponse, evidenceResponse] = await Promise.all([api.facts ? api.facts(node.id) : { items: node.facts || [] }, api.evidence(node.id)]);
    const facts = factsResponse.items || factsResponse.records || node.facts || [];
    const evidence = evidenceResponse.items || evidenceResponse.records || [];
    renderInspector(node, facts, evidence);
  } catch (error) { toast(error.message); }
}

function renderInspector(node, facts, evidence) {
  const summary = $("#panel-summary");
  summary.replaceChildren(element("h3", "inspector-title", node.title), element("p", "inspector-summary", node.summary || "No summary is available for this deterministic item."));
  if (node.characters?.length) summary.append(element("p", "code", `Characters · ${node.characters.join(", ")}`));
  const statePanel = $("#panel-state");
  statePanel.replaceChildren();
  const list = element("ul", "fact-list");
  for (const fact of facts) {
    const type = fact.type || fact.kind || "fact";
    if ((type === "requirement" && !state.settings.show_requirements) || (type === "effect" && !state.settings.show_effects)) continue;
    const item = element("li", "fact");
    item.dataset.type = type;
    item.append(element("span", "fact-label", fact.label || `${fact.variable || type} · ${fact.status || fact.certainty || ""}`), element("span", "code", fact.expression || ""));
    list.append(item);
  }
  statePanel.append(list.childElementCount ? list : element("p", "inspector-empty", "No deterministic state facts."));
  const evidencePanel = $("#panel-evidence");
  evidencePanel.replaceChildren();
  const evidenceList = element("ol", "evidence-list");
  for (const [index, record] of evidence.entries()) {
    const item = element("li", "evidence-record");
    item.tabIndex = 0;
    item.dataset.evidenceId = record.id;
    if (index === 0) item.setAttribute("aria-current", "true");
    if (record.speaker) item.append(element("span", "speaker", record.speaker));
    item.append(element("p", "", record.text || ""));
    const source = record.source || { path: record.source_path, start_line: record.start_line, end_line: record.end_line, basis: "physical" };
    const link = element("button", "source-link", `${source.path || "source"}:${source.start_line || "?"}${source.basis === "reconstructed" ? " · reconstructed" : ""}`);
    link.type = "button";
    link.addEventListener("click", () => { for (const row of evidenceList.children) row.removeAttribute("aria-current"); item.setAttribute("aria-current", "true"); toast(`Evidence ${record.id} selected`); });
    item.append(link);
    evidenceList.append(item);
  }
  evidencePanel.append(evidenceList.childElementCount ? evidenceList : element("p", "inspector-empty", "Select an event to load exact evidence."));
  const details = $("#panel-details");
  details.replaceChildren();
  const detailList = element("dl", "detail-list");
  const rows = [["Stable ID", node.id], ["Kind", node.kind], ["Children", node.child_count ?? 0], ["Authority", "Deterministic"], ["Source", node.source?.path || node.source_path || "—"]];
  for (const [label, value] of rows) { const row = element("div", "detail-row"); row.append(element("dt", "", label), element("dd", "code", value)); detailList.append(row); }
  details.append(detailList);
}

async function openNode(node) {
  if (state.level === "arcs") { state.parentIds = [node.id]; state.selected = node; await changeLevel("events"); }
  else if (state.level === "events") { state.parentIds = [node.id]; state.selected = node; await changeLevel("evidence"); }
  else { activateTab("evidence"); $("#panel-evidence").querySelector("[tabindex]")?.focus(); }
}

async function changeLevel(level) {
  const ordered = ["arcs", "events", "evidence"];
  if (ordered.indexOf(level) < ordered.indexOf(state.level)) state.parentIds = level === "arcs" ? [] : state.parentIds.slice(0, 1);
  state.level = safeLevel(level);
  await loadView({ preserveSelection: false });
}

function activateTab(name, focus = false) {
  for (const tab of $$("#inspectorTabs [role=tab]")) {
    const selected = tab.id === `tab-${name}`;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    if (selected && focus) tab.focus();
  }
  for (const panel of $$(".tab-panel")) panel.hidden = panel.id !== `panel-${name}`;
}

function saveSettings() {
  try { localStorage.setItem("rsm.view.v1", JSON.stringify(state.settings)); } catch { /* server persistence remains authoritative */ }
  if (!mockMode) api.saveSettings(state.settings).catch(() => {});
}

async function showReview() {
  try {
    const envelope = await api.draft();
    const drafts = Array.isArray(envelope.drafts) ? envelope.drafts : [];
    const draft = drafts.find((item) => item.id === envelope.id) || drafts.find((item) => item.status === "pending") || drafts[0];
    if (!draft) { toast("No organization draft is ready"); return; }
    state.draftId = draft.id;
    state.reviewPage = 0;
    const persisted = Array.isArray(envelope.reviews?.[draft.id]) ? envelope.reviews[draft.id] : [];
    const decisions = new Map(persisted.map((review) => [`${review.target_kind}:${review.target_id}`, review.decision]));
    const arcs = Array.isArray(draft.candidate?.arcs) ? draft.candidate.arcs : [];
    const events = Array.isArray(draft.candidate?.events) ? draft.candidate.events : [];
    state.reviewCandidates = [
      ...arcs.map((group) => ({ ...group, kind: "arc", memberCount: Array.isArray(group.event_ids) ? group.event_ids.length : 0 })),
      ...events.map((group) => ({ ...group, kind: "event", memberCount: Array.isArray(group.beat_ids) ? group.beat_ids.length : 0 })),
    ].map((group) => ({
      id: group.id,
      kind: group.kind,
      title: group.title || "Untitled candidate",
      summary: group.summary || "",
      memberCount: group.memberCount,
      decision: ["approved", "rejected"].includes(decisions.get(`${group.kind}:${group.id}`)) ? decisions.get(`${group.kind}:${group.id}`) : null,
    })).filter((group) => group.id);
    $("#reviewMeta").textContent = `${draft.provider || "Configured provider"} · ${draft.elapsed || "—"} · ${draft.cache_hits || 0} cache hits · ${draft.provider_calls || 0} provider calls`;
    renderReviewCandidates();
    $("#reviewDialog").showModal();
  } catch (error) { toast(error.message); }
}

function renderReviewCandidates() {
  const candidates = state.reviewCandidates;
  const decided = candidates.filter((candidate) => candidate.decision === "approved" || candidate.decision === "rejected").length;
  const pages = Math.max(1, Math.ceil(candidates.length / REVIEW_PAGE_SIZE));
  state.reviewPage = Math.min(state.reviewPage, pages - 1);
  const start = state.reviewPage * REVIEW_PAGE_SIZE;
  const visible = candidates.slice(start, start + REVIEW_PAGE_SIZE);
  $("#reviewProgress").textContent = `${decided} decided · ${candidates.length - decided} remaining · ${candidates.length} candidates`;
  $("#reviewPage").textContent = `Page ${state.reviewPage + 1} of ${pages}`;
  $("#reviewPrevious").disabled = state.reviewPage === 0;
  $("#reviewNext").disabled = state.reviewPage >= pages - 1;
  $("#applyDraft").disabled = candidates.length === 0 || decided !== candidates.length;
  const host = $("#reviewComparison");
  host.replaceChildren();
  for (const candidate of visible) {
    const row = element("article", "review-change");
    row.dataset.candidateId = candidate.id;
    row.append(element("strong", "", candidate.kind));
    const copy = element("div", "review-copy");
    copy.append(element("h3", "", candidate.title), element("p", "", candidate.summary), element("span", "", `${candidate.memberCount} members`));
    const actions = element("div", "review-decisions");
    actions.setAttribute("role", "group");
    actions.setAttribute("aria-label", `Decision for ${candidate.title}`);
    for (const [decision, label] of [["approved", "Approve"], ["rejected", "Reject"]]) {
      const button = element("button", "secondary-button", label);
      button.type = "button";
      button.dataset.decision = decision;
      button.setAttribute("aria-pressed", String(candidate.decision === decision));
      button.addEventListener("click", () => reviewCandidate(candidate.id, candidate.kind, decision));
      actions.append(button);
    }
    row.append(copy, actions);
    host.append(row);
  }
  if (!visible.length) host.append(element("p", "inspector-empty", "No candidate groups are available."));
}

async function reviewCandidate(targetId, targetKind, decision) {
  const candidate = state.reviewCandidates.find((item) => item.id === targetId && item.kind === targetKind);
  if (!candidate || !state.draftId) return;
  if (candidate.decision === decision) return;
  try {
    const response = await api.reviewDraftGroup(state.draftId, targetKind, targetId, decision);
    if (response.decision !== "approved" && response.decision !== "rejected") throw new Error("The review decision was not persisted");
    candidate.decision = response.decision;
    renderReviewCandidates();
    $("#reviewComparison").querySelector(`[data-candidate-id="${CSS.escape(targetId)}"] [data-decision="${CSS.escape(response.decision)}"]`)?.focus();
  } catch (error) {
    toast(error.message);
  }
}

async function showDiagnostics() {
  try {
    const data = await api.diagnostics();
    const host = $("#diagnosticsContent"); host.replaceChildren();
    for (const [label, value] of Object.entries(data)) { const row = element("div", "diagnostic-row"); row.append(element("strong", "", label.replaceAll("_", " ")), element("span", "", Array.isArray(value) ? value.join(" · ") : value)); host.append(row); }
    $("#diagnosticsDialog").showModal();
  } catch (error) { toast(error.message); }
}

function bind() {
  $$('[data-open-kind]').forEach((button) => button.addEventListener("click", () => choose(button.dataset.openKind)));
  $("#homeButton").addEventListener("click", () => showView("welcome"));
  $("#refreshProject").addEventListener("click", refreshProject);
  $("#cancelAnalysis").addEventListener("click", async () => { await api.cancel(); await pollProgress(); });
  $("#filterButton").addEventListener("click", () => { const panel = $("#filterPanel"); panel.hidden = !panel.hidden; $("#filterButton").setAttribute("aria-expanded", String(!panel.hidden)); });
  const toggles = [["technicalToggle", "include_technical"], ["unresolvedToggle", "include_unresolved"], ["requirementsToggle", "show_requirements"], ["effectsToggle", "show_effects"]];
  for (const [id, key] of toggles) $("#" + id).addEventListener("change", (event) => { state.settings[key] = event.target.checked; saveSettings(); loadView(); });
  let searchTimer;
  $("#searchInput").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadView(), 180); });
  $("#organizeButton").addEventListener("click", () => $("#consentDialog").showModal());
  $("#confirmOrganization").addEventListener("click", async (event) => {
    event.preventDefault();
    $("#consentDialog").close();
    try {
      const started = await api.consent(state.parentIds);
      if (started.analysis?.state === "running" || started.task?.state === "running") await pollProgress();
      await showReview();
    } catch (error) {
      toast(error.message);
    }
  });
  $("#closeReview").addEventListener("click", () => $("#reviewDialog").close());
  $("#reviewPrevious").addEventListener("click", () => { state.reviewPage -= 1; renderReviewCandidates(); });
  $("#reviewNext").addEventListener("click", () => { state.reviewPage += 1; renderReviewCandidates(); });
  $("#applyDraft").addEventListener("click", async () => {
    if (!state.reviewCandidates.length || state.reviewCandidates.some((candidate) => candidate.decision !== "approved" && candidate.decision !== "rejected")) return;
    await api.applyDraft(state.draftId);
    $("#reviewDialog").close();
    toast("Draft applied atomically");
  });
  $("#discardDraft").addEventListener("click", async () => { await api.discardDraft(state.draftId); $("#reviewDialog").close(); toast("Draft discarded"); });
  $("#diagnosticsButton").addEventListener("click", showDiagnostics);
  $("#closeDiagnostics").addEventListener("click", () => $("#diagnosticsDialog").close());
  $("#quitButton").addEventListener("click", async () => {
    const button = $("#quitButton");
    button.disabled = true;
    button.textContent = "Closing…";
    try {
      await api.shutdown();
      document.body.replaceChildren(element("main", "shutdown-message", "Story Mapper has closed. You can close this tab."));
    } catch (error) {
      button.disabled = false;
      button.textContent = "Quit";
      toast(error.message);
    }
  });
  $("#zoomIn").addEventListener("click", () => { $("#zoomValue").textContent = `${Math.round(graph.zoomBy(.1) * 100)}%`; });
  $("#zoomOut").addEventListener("click", () => { $("#zoomValue").textContent = `${Math.round(graph.zoomBy(-.1) * 100)}%`; });
  $("#fitMap").addEventListener("click", () => { graph.fit(); $("#zoomValue").textContent = `${Math.round(graph.scale * 100)}%`; });
  $("#themeButton").addEventListener("click", () => { const themes = ["system", "light", "dark"]; state.settings.theme = themes[(themes.indexOf(state.settings.theme) + 1) % themes.length]; document.documentElement.dataset.theme = state.settings.theme; saveSettings(); graph.draw(); });
  const tabs = $$("#inspectorTabs [role=tab]");
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activateTab(tab.id.slice(4)));
    tab.addEventListener("keydown", (event) => { if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return; event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length; activateTab(tabs[next].id.slice(4), true); });
  });
  document.addEventListener("keydown", (event) => { if (event.key === "/" && !event.ctrlKey && !event.metaKey && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) { event.preventDefault(); $("#searchInput").focus(); } });
}

async function acceptanceScenario() {
  const scenario = params.get("state");
  if (!mockMode || !scenario || scenario === "welcome") return;
  if (scenario === "review-pages") api.largeReview = true;
  if (scenario === "create") await choose("folder");
  else await openSelection({ id: "opaque-project", display_name: "The Lantern House" }, true);
  if (scenario === "refresh") await refreshProject();
  if (["events", "evidence", "review", "review-pages"].includes(scenario)) await openNode(state.view.nodes[0]);
  if (scenario === "events") {
    $("#mapViewport").focus();
    $("#mapViewport").dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
  }
  if (scenario === "evidence") {
    await openNode(state.view.nodes[1] || state.view.nodes[0]);
    await selectNode(state.view.nodes[0], true);
    activateTab("evidence");
  }
  if (scenario === "review" || scenario === "review-pages") {
    await showReview();
    document.body.dataset.applyInitiallyDisabled = String($("#applyDraft").disabled);
    for (const [index, candidate] of state.reviewCandidates.entries()) {
      if (!candidate.decision) await reviewCandidate(candidate.id, candidate.kind, index % 2 ? "rejected" : "approved");
    }
    if (scenario === "review-pages") {
      state.reviewPage = Math.ceil(state.reviewCandidates.length / REVIEW_PAGE_SIZE) - 1;
      renderReviewCandidates();
    }
    document.body.dataset.applyEnabled = String(!$("#applyDraft").disabled);
  }
  if (scenario === "progress") { showView("progress"); updateProgress({ stage: "Indexing story evidence", percent: 47, elapsed_seconds: 12 }); }
  if (params.get("zoom") === "200") document.documentElement.dataset.zoom = "200";
  document.body.dataset.keyboardSelected = graph.selectedId || "";
  document.body.dataset.visibleItems = String((state.view?.nodes.length || 0) + (state.view?.edges.length || 0));
  document.body.dataset.exactEvidence = $("#panel-evidence [data-evidence-id]")?.dataset.evidenceId || "";
  document.body.dataset.organizationStarts = String(api.calls?.filter((call) => call.name === "organizationConsent").length || 0);
  const createCall = api.calls?.find((call) => call.name === "create");
  document.body.dataset.createProjectSelection = createCall?.payload.projectSelectionId || "";
  document.body.dataset.refreshCalls = String(api.calls?.filter((call) => call.name === "refresh").length || 0);
  const reviewCalls = api.calls?.filter((call) => call.name === "reviewDraftGroup") || [];
  document.body.dataset.reviewCalls = String(reviewCalls.length);
  document.body.dataset.reviewRequestKeys = reviewCalls[0] ? Object.keys(reviewCalls[0].payload).sort().join(",") : "";
  document.body.dataset.reviewRows = String($("#reviewComparison").children.length);
  document.body.dataset.reviewCandidates = String(state.reviewCandidates.length);
  document.body.dataset.refreshVisible = String(!$("#refreshProject").hidden);
  document.body.dataset.acceptanceReady = "true";
}

async function start() {
  bind();
  try {
    const bootstrap = await api.bootstrap();
    const stored = (() => { try { return JSON.parse(localStorage.getItem("rsm.view.v1") || "null"); } catch { return null; } })();
    state.settings = { ...state.settings, ...bootstrap.settings, ...(stored || {}) };
    document.documentElement.dataset.theme = state.settings.theme;
    $("#technicalToggle").checked = state.settings.include_technical;
    $("#unresolvedToggle").checked = state.settings.include_unresolved;
    $("#requirementsToggle").checked = state.settings.show_requirements;
    $("#effectsToggle").checked = state.settings.show_effects;
    renderRecent(bootstrap.recent_projects || []);
    showView("welcome");
    await acceptanceScenario();
    if (!document.body.dataset.acceptanceReady) document.body.dataset.acceptanceReady = "true";
  } catch (error) { renderRecent([]); toast(error.message); document.body.dataset.acceptanceReady = "error"; }
}

start();

export { api, graph, state, element, normalizeView };
