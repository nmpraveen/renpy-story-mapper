import { DEFAULT_NARRATIVE_BATCH_LIMITS, DEFAULT_NARRATIVE_LIMITS, LocalApi } from "./api.js";
import { ROUTE_EDGE_PAGE_SIZE, ROUTE_PAGE_SIZE } from "./contract.js";
import { RouteGraph } from "./graph.js";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const api = new LocalApi();
const CURSOR_HISTORY_LIMIT = 12;

const state = {
  project: null, page: null, narrativeMapPage: null, inspectionPage: null, canonicalPage: null, narrativeReason: null, mode: "narrative",
  analysisStatus: null,
  offset: 0, edgeOffset: 0, edgeCursor: null, cursorHistory: [], selectedId: null, detail: null, detailRunToken: 0,
  narrativeEnabled: false, narrativeSnapshot: null, narrativeJobs: [], narrativeByOwner: new Map(),
  narrativeRun: null, narrativePreparation: null, narrativeLastRequest: null, narrativePollToken: 0, narrativeStatusToken: 0,
  narrativeCitationSelection: null,
  settings: { theme: "system", include_technical: true, include_unresolved: true },
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function renderNarrativeCoverage() {
  const host = $("#narrativeCoverage"); host.replaceChildren();
  const coverage = state.narrativeSnapshot?.coverage;
  if (!coverage) { host.append(element("span", "muted", "Narrative authority is unavailable.")); return; }
  const percent = Number(coverage.scene_coverage_basis_points || 0) / 100;
  host.append(
    element("strong", "", `${percent.toLocaleString(undefined, { maximumFractionDigits: 2 })}% scene coverage`),
    element("span", "", `${coverage.published_scene_jobs || 0} of ${coverage.expected_scene_jobs || 0} scene jobs published`),
    element("span", "", `${coverage.stale_jobs || 0} stale · ${coverage.unavailable_jobs || 0} unavailable`),
    element("span", "", `${coverage.m12_selected_results || 0} current M12 result(s) included`),
  );
}

function narrativeCitationSelection(claim, response, citation) {
  return {
    claim_id: claim.claim_id,
    claim_path: [...citation.claim_path],
    traversed_claim_ids: [...response.traversed_claim_ids],
    citation_count: response.citation_count,
    authority_labels: [...response.authority_labels],
    authority: citation.authority,
    record_kind: citation.record_kind,
    record_id: citation.record_id,
    owner_id: citation.owner_id,
    label: citation.label,
    navigation: { ...citation.navigation },
  };
}

function narrativeCitationControls(claim, response, openCitation) {
  if (!Array.isArray(response.citations)) throw new TypeError("Resolved citations are unavailable");
  return response.citations.map((citation) => ({
    label: citation.label,
    record_id: citation.record_id,
    authority: citation.authority,
    select: (button) => openCitation(claim, response, citation, button),
  }));
}

function appendNarrativeClaimPath(host, selection) {
  const path = element("div", "narrative-claim-path");
  path.append(element("strong", "", "M13 claim path"));
  for (const [index, claimId] of selection.claim_path.entries()) {
    const step = element("span", "narrative-claim-step", `Claim ${index + 1}`); step.title = claimId; step.dataset.claimId = claimId; path.append(step);
  }
  host.append(path);
}

function markNarrativeCitationSelection(selection) {
  state.narrativeCitationSelection = selection;
  state.detail = { ...state.detail, citation_selection: selection };
  state.selectedId = selection.navigation.focus_record_id;
  const record = element("article", "narrative-citation-selection"); record.dataset.recordId = selection.record_id;
  record.append(element("strong", "", selection.label), element("span", "", `Selected ${selection.record_kind.replaceAll("_", " ")} ${selection.record_id}`));
  appendNarrativeClaimPath(record, selection);
  $("#evidenceList").prepend(record);
}

function renderM12NarrativeCitation(result, selection) {
  state.narrativeCitationSelection = selection;
  state.selectedId = selection.navigation.focus_record_id;
  state.detail = {
    level: "m12_result_detail",
    element: {
      id: result.request_identity,
      kind: "M12 route result",
      title: "Exact M12 route result",
      summary: `Technical status ${String(result.status).replaceAll("_", " ")} with badge ${String(result.badge).replaceAll("_", " ")}.`,
    },
    citation_selection: selection,
    route_result: result,
  };
  $("#detailTitle").textContent = "Exact M12 route result";
  $("#detailKind").textContent = "M12 route result";
  $("#detailSummary").textContent = state.detail.element.summary;
  $("#canonicalEscapeButton").hidden = true;
  const strip = $("#pathStrip"); strip.replaceChildren(element("strong", "path-stop current", result.request_identity));
  $("#memberGraph").replaceChildren(); $("#technicalMembers").hidden = true;
  $("#regionDerivation").replaceChildren(); $("#proofDerivation").replaceChildren(); $("#linkedRecords").replaceChildren(); $("#derivationPanel").hidden = true;
  const facts = $("#detailFacts"); facts.replaceChildren();
  addFactGroup(facts, "Exact route-result authority", [
    { label: "Technical status", expression: result.status },
    { label: "Badge", expression: result.badge },
    { label: "Completion", expression: String(result.complete) },
    { label: "Termination", expression: result.termination_reason || "none" },
    { label: "Request identity", expression: result.request_identity },
  ], "gate");
  const interpretations = $("#interpretations"); interpretations.replaceChildren();
  const selected = element("article", "interpretation claim"); selected.append(element("strong", "", "Narrative authority selection"), element("p", "", `${selection.label}; deterministic M12 authority remains unchanged.`)); appendNarrativeClaimPath(selected, selection); interpretations.append(selected); $("#interpretationPanel").hidden = false;
  const evidence = $("#evidenceList"); evidence.replaceChildren();
  const exact = element("article", "narrative-citation-selection"); exact.dataset.recordId = selection.record_id;
  exact.append(element("strong", "", selection.label), element("span", "", `Selected exact route result ${result.request_identity}`)); appendNarrativeClaimPath(exact, selection); evidence.append(exact);
  showLevel("detail_evidence"); $("#backToRouteMap").focus();
}

async function openNarrativeDetailEvidence(claim, response, citation, button) {
  const label = button.textContent;
  button.disabled = true; button.textContent = "Opening…";
  try {
    const selection = narrativeCitationSelection(claim, response, citation);
    $("#narrativeDrawer").hidden = true;
    const navigation = citation.navigation;
    if (navigation.mode === "m12_result") {
      const result = await api.routeResult(navigation.request_identity);
      renderM12NarrativeCitation(result, selection);
      return;
    }
    if (navigation.mode === "scenes") await openDetail(navigation.element_id, true, "scenes");
    else {
      if (state.mode !== "canonical") await switchMode("canonical");
      await openDetail(navigation.element_id, true, "canonical");
    }
    if (document.documentElement.dataset.activeLevel !== "detail_evidence") throw new TypeError("The cited authority detail is unavailable");
    markNarrativeCitationSelection(selection);
  } catch (error) { button.disabled = false; button.textContent = label; toast(error.message); }
}

async function loadNarrativeCitationControls(claim, host, button) {
  button.disabled = true; button.textContent = "Loading citations…";
  try {
    const response = await api.narrativeCitations(claim.claim_id);
    const controls = narrativeCitationControls(claim, response, openNarrativeDetailEvidence);
    if (!controls.length) throw new TypeError("No direct citation leaf was resolved");
    const group = element("div", "narrative-citation-controls"); group.setAttribute("role", "group"); group.setAttribute("aria-label", "Detail and Evidence citations");
    for (const control of controls) {
      const citationButton = element("button", "quiet-button narrative-citation-control", `${control.authority.toUpperCase()} · ${control.label}`);
      citationButton.type = "button"; citationButton.dataset.recordId = control.record_id; citationButton.setAttribute("aria-label", `Open ${control.label} in Detail and Evidence`);
      citationButton.addEventListener("click", () => control.select(citationButton)); group.append(citationButton);
    }
    host.replaceChildren(group);
  } catch (error) { button.disabled = false; button.textContent = "Open Detail and Evidence"; toast(error.message); }
}

function renderNarrativeClaims(host, artifact) {
  for (const claim of artifact.claims || []) {
    const article = element("article", "narrative-claim"); article.dataset.claimClass = claim.claim_class;
    const label = claim.claim_class === "factual" ? "Factual claim" : claim.claim_class === "interpretive" ? "AI interpretation" : "Review suggestion";
    const scope = claim.context_scope === "comparison" ? " · route comparison" : claim.context_scope === "ordered_summary" ? " · ordered summary" : "";
    article.append(element("strong", "", `${label}${scope}`), element("p", "", claim.text));
    const actions = element("div", "narrative-claim-actions");
    const button = element("button", "quiet-button", "Open Detail and Evidence"); button.type = "button";
    button.addEventListener("click", () => loadNarrativeCitationControls(claim, actions, button));
    actions.append(button); article.append(actions); host.append(article);
  }
}

function narrativeSectionLabel(entry) {
  const path = entry?.path || {}; const section = path.section;
  if (section === "persistent_route") return `Persistent route · ${path.route_id || "unresolved"}`;
  if (section === "temporary_branch") return `Temporary branch · ${path.temporary_container_id || "bounded detour"}`;
  if (section === "ending") return `Ending · ${path.ending_id || "unresolved"}${path.route_id ? ` · ${path.route_id}` : ""}`;
  if (section === "unresolved") return "Unresolved or missing coverage";
  return "Shared story";
}

function renderNarrativeHierarchy(host, artifact) {
  const entries = artifact.hierarchy?.section_entries;
  if (!Array.isArray(entries) || !entries.length) return;
  const section = element("section", "narrative-hierarchy");
  section.append(element("strong", "", "Route-aware structure"));
  for (const entry of entries.slice(0, 32)) {
    const stateLabel = entry.available === false ? " · missing" : "";
    section.append(element("span", "", `${narrativeSectionLabel(entry)}${stateLabel}`));
  }
  host.append(section);
}

async function expandNarrativeJob(job, host, button) {
  if (!job.artifact) return;
  button.disabled = true;
  try {
    const artifact = await api.narrativeArtifact(job.artifact.artifact_id);
    host.append(
      element("strong", "", artifact.summary_class === "interpretive" ? "AI interpretation" : "Narrative summary"),
      element("p", "", artifact.summary),
    );
    renderNarrativeHierarchy(host, artifact);
    for (const warning of artifact.warnings || []) host.append(element("span", "correction", warning));
    renderNarrativeClaims(host, artifact); button.remove();
  } catch (error) { button.disabled = false; toast(error.message); }
}

function renderNarrativeDrawer() {
  renderNarrativeCoverage();
  const host = $("#narrativeJobList"); host.replaceChildren();
  const jobs = state.narrativeJobs.slice(0, 120);
  for (const job of jobs) {
    const record = element("article", "narrative-job");
    record.append(element("strong", "", job.artifact?.title || job.owner_id), element("span", "", `${job.kind.replaceAll("_", " ")} · ${job.state.replaceAll("_", " ")}`));
    if (job.artifact) {
      const button = element("button", "quiet-button", "Open summary and claims"); button.type = "button";
      button.addEventListener("click", () => expandNarrativeJob(job, record, button)); record.append(button);
    } else if (job.latest_error?.code) record.append(element("span", "correction", job.latest_error.code.replaceAll("_", " ")));
    host.append(record);
  }
  if (!jobs.length) host.append(element("p", "muted", "No narrative jobs have been published. The deterministic product remains fully available."));
  if (state.narrativeJobs.length > jobs.length) host.append(element("p", "muted", `${state.narrativeJobs.length - jobs.length} more jobs are retained; this drawer is intentionally bounded.`));
}

const NARRATIVE_ACTIVE_STATES = new Set(["running", "cancelling"]);
const NARRATIVE_RETRY_STATES = new Set(["partial", "failed", "cancelled", "hard_limit"]);

function narrativeRunRequest() {
  const positiveInteger = (selector, label) => {
    const value = Number($(selector).value);
    if (!Number.isInteger(value) || value < 1) throw new TypeError(`${label} must be a positive integer`);
    return value;
  };
  const total = positiveInteger("#narrativeTokenLimit", "Total token limit");
  const input = Math.max(1, Math.floor(total * 5 / 7));
  const output = Math.max(1, total - input);
  return {
    requested_model: $("#narrativeModel").value.trim(),
    provider_settings: {
      model_reasoning_effort: $("#narrativeReasoningEffort").value,
      fast_mode: $("#narrativeFastMode").checked,
    },
    mode: $("#narrativeMode").value,
    include_m12_material: $("#narrativeIncludeM12").checked,
    limits: {
      ...DEFAULT_NARRATIVE_LIMITS,
      max_provider_calls: positiveInteger("#narrativeCallLimit", "Provider call limit"),
      max_input_tokens: input,
      max_output_tokens: output,
      max_total_tokens: total,
      timeout_seconds: positiveInteger("#narrativeTimeLimit", "Time limit"),
      max_concurrency: positiveInteger("#narrativeConcurrency", "Concurrency limit"),
    },
    batch_limits: { ...DEFAULT_NARRATIVE_BATCH_LIMITS },
  };
}

function renderNarrativeRun() {
  const run = state.narrativeRun; const status = $("#narrativeRunStatus");
  if (run?.retry_available && run.retry_request) state.narrativeLastRequest = { ...run.retry_request };
  const active = NARRATIVE_ACTIVE_STATES.has(run?.state);
  $("#prepareNarrative").disabled = active;
  $("#cancelNarrative").hidden = !active;
  $("#retryNarrative").hidden = !NARRATIVE_RETRY_STATES.has(run?.state) || !run?.retry_available || !state.narrativeLastRequest;
  if (!run || run.state === "disabled") status.textContent = "Cloud AI is off. Preparing a manifest sends no story material.";
  else if (run.state === "prepared") status.textContent = "Prepared locally. No story material has been sent; confirmation is still required.";
  else if (run.state === "running") status.textContent = "Narrative jobs are running. Valid results are committed independently.";
  else if (run.state === "cancelling") status.textContent = "Cancelling provider work. Validated completed artifacts are being preserved.";
  else {
    const latest = run.latest_run || {}; const usage = latest.cumulative_usage || latest.usage || {};
    const counts = `${Number(latest.succeeded_jobs || 0)} complete, ${Number(latest.partial_jobs || 0)} partial, ${Number(latest.failed_jobs || 0) + Number(latest.refused_jobs || 0)} unavailable`;
    status.textContent = `${run.state.replaceAll("_", " ")} - ${counts}; ${Number(usage.provider_calls || 0)} provider call(s).`;
  }
}

function showNarrativeConsent(prepared) {
  const facts = $("#narrativeConsentFacts"); facts.replaceChildren();
  const estimate = prepared.estimate; const limits = prepared.limits; const provider = prepared.provider;
  const cost = estimate.estimated_cost_micros === null ? "Unavailable for this adapter" : `$${(estimate.estimated_cost_micros / 1000000).toFixed(2)} (${estimate.cost_confidence})`;
  const rows = [
    ["Provider", `${provider.provider} / ${provider.adapter} ${provider.adapter_version}`],
    ["Requested / resolved model", `${provider.requested_model} / ${provider.resolved_model}`],
    ["Provider settings", `${provider.settings.model_reasoning_effort} reasoning / fast mode ${provider.settings.fast_mode ? "on" : "off"}`],
    ["Consent manifest", prepared.consent_manifest_id],
    ["Selected scope", prepared.selected_scope_ids.join(", ")],
    ["Privacy mode", prepared.privacy_mode === "fact_only" ? "Fact only" : "Story text"],
    ["Logical jobs", estimate.logical_job_count.toLocaleString()],
    ["Estimated provider calls", estimate.provider_call_count.toLocaleString()],
    ["Estimated tokens", `${estimate.input_tokens.toLocaleString()} input / ${estimate.output_tokens.toLocaleString()} output`],
    ["Estimated cost", cost],
    ["Hard limits", `${limits.max_provider_calls.toLocaleString()} calls / ${limits.max_total_tokens.toLocaleString()} tokens / ${limits.timeout_seconds.toLocaleString()} seconds / ${limits.max_concurrency} concurrent`],
    ["M12 material", prepared.includes_m12_material ? "Included" : "Not included"],
  ];
  for (const [label, value] of rows) facts.append(element("dt", "", label), element("dd", "", value));
  $("#confirmNarrative").disabled = !prepared.provider_available;
  $("#narrativeConsentDialog").showModal();
  if (!prepared.provider_available) toast("The selected provider is unavailable; no story material can be sent");
}

async function prepareNarrativeRequest(request) {
  const token = ++state.narrativeStatusToken;
  state.narrativeLastRequest = request;
  state.narrativePreparation = await api.prepareNarrative(request);
  const run = await api.narrativeStatus();
  if (token !== state.narrativeStatusToken) return;
  state.narrativeRun = run;
  renderNarrativeRun(); showNarrativeConsent(state.narrativePreparation);
}

async function prepareNarrativeRun(event) {
  event?.preventDefault();
  try { await prepareNarrativeRequest(narrativeRunRequest()); }
  catch (error) { toast(error.message); }
}

async function confirmNarrativeRun(event) {
  event.preventDefault();
  ++state.narrativeStatusToken;
  const preparationId = state.narrativePreparation?.preparation_id;
  if (!preparationId) { toast("Narrative preparation is unavailable"); return; }
  $("#narrativeConsentDialog").close();
  try {
    state.narrativeRun = await api.startNarrative(preparationId);
    state.narrativePreparation = null; renderNarrativeRun(); pollNarrativeRun();
  } catch (error) { toast(error.message); }
}

async function pollNarrativeRun() {
  const token = ++state.narrativePollToken; let ticks = 0;
  while (token === state.narrativePollToken && NARRATIVE_ACTIVE_STATES.has(state.narrativeRun?.state)) {
    await new Promise((resolve) => setTimeout(resolve, 900));
    if (token !== state.narrativePollToken) return;
    try {
      state.narrativeRun = await api.narrativeStatus(); ticks += 1; renderNarrativeRun();
      if (ticks % 4 === 0) await loadNarrative();
    } catch (error) { toast(error.message); return; }
  }
  if (token === state.narrativePollToken) { await loadNarrative(); renderNarrativeRun(); }
}

async function cancelNarrativeRun() {
  ++state.narrativeStatusToken;
  try { state.narrativeRun = await api.cancelNarrative(); renderNarrativeRun(); toast("Cancellation requested; validated work is preserved"); }
  catch (error) { toast(error.message); }
}

async function retryNarrativeRun() {
  if (!state.narrativeLastRequest) { toast("No prior Narrative scope is available"); return; }
  try { await prepareNarrativeRequest(state.narrativeLastRequest); }
  catch (error) { toast(error.message); }
}

async function loadNarrativeRunStatus() {
  const token = state.narrativeStatusToken;
  try {
    const run = await api.narrativeStatus();
    if (token !== state.narrativeStatusToken || state.narrativePreparation) return;
    state.narrativeRun = run; renderNarrativeRun();
    if (NARRATIVE_ACTIVE_STATES.has(state.narrativeRun.state)) pollNarrativeRun();
  } catch (_error) { if (token === state.narrativeStatusToken) { state.narrativeRun = null; renderNarrativeRun(); } }
}

async function loadNarrative() {
  const jobs = []; let offset = 0; let first = null; let pages = 0;
  try {
    while (pages < 50) {
      const page = await api.narrativeSnapshot(offset, 200);
      if (!first) first = page;
      if (page.status !== "available") break;
      if (page.authority_hash !== first.authority_hash) throw new Error("Narrative authority changed while paging");
      jobs.push(...page.jobs); pages += 1;
      if (page.next_offset === null) break;
      offset = page.next_offset;
    }
    state.narrativeSnapshot = first;
    state.narrativeJobs = jobs;
    state.narrativeByOwner = new Map(jobs.map((job) => [job.owner_id, job]));
  } catch (_error) {
    state.narrativeSnapshot = null; state.narrativeJobs = []; state.narrativeByOwner = new Map();
  }
  renderNarrativeDrawer();
}

const graph = new RouteGraph({
  viewport: $("#mapViewport"), world: $("#mapWorld"), canvas: $("#edgeCanvas"),
  onSelect: (item) => selectItem(item), onOpen: (item) => openDetail(item.id),
  onViewportChange: (scale) => { $("#zoomValue").textContent = `${Math.round(scale * 100)}%`; },
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

function normalizedPage(page, mode = state.mode) {
  if (mode === "narrative") {
    return {
      ...page,
      nodes: page.nodes.map((node) => ({ ...node, title: node.title || "Untitled story event", summary: node.summary || "" })),
      edges: page.edges.map((edge) => ({ ...edge, source_id: edge.source_id, target_id: edge.target_id })),
      offset: 0,
      edge_offset: 0,
      next_offset: null,
      edge_next_offset: null,
      page_edge_total: page.total_edges,
      generation_status: { freshness: "current", analysis_status: "current_complete" },
    };
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
  let narrative = null; let simplified = null; let canonical = null;
  try { narrative = await api.narrativeMap(); } catch (_error) { narrative = null; }
  state.narrativeMapPage = narrative?.status === "available" ? normalizedPage(narrative, "narrative") : null;
  state.narrativeReason = narrative?.reason || "narrative map not yet available";
  try { simplified = await api.inspectionMap("simplified", 0, ROUTE_PAGE_SIZE, 0, ROUTE_EDGE_PAGE_SIZE); } catch (_error) { simplified = null; }
  try { canonical = await api.inspectionMap("canonical", 0, ROUTE_PAGE_SIZE, 0, ROUTE_EDGE_PAGE_SIZE); } catch (_error) { canonical = null; }
  state.inspectionPage = simplified?.status === "available" ? normalizedPage(simplified, "inspection") : null;
  state.canonicalPage = canonical?.status === "available" ? normalizedPage(canonical, "canonical") : null;
  const inspectionCurrent = state.inspectionPage?.generation_status?.freshness === "current";
  const canonicalCurrent = state.canonicalPage?.generation_status?.freshness === "current";
  if (state.narrativeMapPage) { state.mode = "narrative"; state.page = state.narrativeMapPage; }
  else if (inspectionCurrent) { state.mode = "inspection"; state.page = state.inspectionPage; }
  else if (canonicalCurrent) { state.mode = "canonical"; state.page = state.canonicalPage; }
  else if (state.inspectionPage) { state.mode = "inspection"; state.page = state.inspectionPage; }
  else { state.mode = "inspection"; state.page = null; }
  const status = state.page?.generation_status || simplified?.generation_status || canonical?.generation_status || null;
  const hasMap = Boolean(state.page);
  renderAnalysisAvailability(status, hasMap);
  $("#fallbackNotice").hidden = !hasMap || Boolean(state.narrativeMapPage);
  $("#fallbackTitle").textContent = "Narrative Map unavailable.";
  $("#fallbackReason").textContent = `${String(state.narrativeReason).replaceAll("_", " ")}. ${state.mode === "inspection" ? "Deterministic inspection fallback" : "Canonical fallback"} is shown.`;
  updateModeHeader();
  if (hasMap) renderMap();
  else graph.setData([], [], null, []);
  return hasMap;
}

async function loadRoutePage(cursor = { offset: state.offset, edgeOffset: state.edgeOffset, edgeCursor: state.edgeCursor }) {
  try {
    const raw = state.mode === "narrative"
      ? await api.narrativeMap()
      : await api.inspectionMap(state.mode === "canonical" ? "canonical" : "simplified", cursor.offset, ROUTE_PAGE_SIZE, cursor.edgeOffset, ROUTE_EDGE_PAGE_SIZE);
    if (raw.status === "unavailable") { renderAnalysisAvailability(raw.generation_status, false); return false; }
    const page = normalizedPage(raw, state.mode);
    state.page = page;
    if (state.mode === "narrative") state.narrativeMapPage = page;
    else if (state.mode === "inspection") state.inspectionPage = page;
    else state.canonicalPage = page;
    state.offset = Number(page.offset || 0);
    state.edgeOffset = Number(page.edge_offset || 0);
    state.edgeCursor = null;
    updateModeHeader(); renderMap(); return true;
  } catch (error) { $("#selectionStatus").textContent = "Map unavailable"; toast(error.message); }
}

async function resetRoutePaging() {
  state.cursorHistory = [];
  state.offset = 0; state.edgeOffset = 0; state.edgeCursor = null;
  return loadComparison();
}

async function enterAvailableWorkspace() {
  showPrimary("workspace"); showLevel("route_map");
  const available = await resetRoutePaging();
  await loadNarrative();
  await loadNarrativeRunStatus();
  if (available) renderMap();
  return available;
}

function nextCursor() {
  const navigation = state.page?.global_navigation || state.page?.navigation || {};
  if (navigation.next && Number.isInteger(navigation.next.offset)) return { offset: navigation.next.offset, edgeOffset: navigation.next.edge_offset || 0 };
  if (state.page?.edge_next_offset !== null && state.page?.edge_next_offset !== undefined) return { offset: state.offset, edgeOffset: Number(state.page.edge_next_offset), edgeCursor: null };
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
  if (state.mode === "narrative") {
    const raw = await api.narrativeMap(query || null, state.selectedId || null);
    if (requestId !== searchM10WholeGraph.requestId || $("#searchInput").value.trim() !== query) return;
    if (raw.status === "unavailable") { renderAnalysisAvailability(raw.generation_status, Boolean(state.page)); return; }
    const page = normalizedPage(raw, "narrative"); state.page = page; state.narrativeMapPage = page;
    const matches = page.search?.matches || [];
    if (query && !matches.length) $("#selectionStatus").textContent = "No Narrative Map matches";
    else if (query && matches.length) state.selectedId = matches[0].id;
    renderMap({ preserveViewport: true });
    if (state.selectedId) graph.world.querySelector(`[data-element-id="${CSS.escape(state.selectedId)}"]`)?.focus();
    return;
  }
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
  const resultIds = Array.isArray(globalSearch?.matches) ? globalSearch.matches.map((item) => item.id) : globalSearch?.element_ids;
  const matchedIds = query && globalSearch?.query?.toLocaleLowerCase() === query && Array.isArray(resultIds) ? new Set(resultIds) : null;
  const visibleNodes = (state.page?.nodes || []).filter((node) => {
    if (!state.settings.include_unresolved && node.unresolved) return false;
    if (!state.settings.include_technical && node.kind === "technical_coverage") return false;
    if (state.mode === "narrative") return true;
    return !query || matchedIds?.has(node.id) || `${node.id} ${node.title} ${node.summary} ${node.reachability || ""}`.toLocaleLowerCase().includes(query);
  }).map((node) => ({ ...node, search_match: !query || matchedIds?.has(node.id) }));
  const ids = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = (state.page?.edges || []).filter((edge) => {
    const continuation = !ids.has(edge.source_id) || !ids.has(edge.target_id);
    if (!continuation && !state.settings.include_technical && Number(edge.technical_hops || 0) > 0) return false;
    if (state.mode === "narrative") return ids.has(edge.source_id) && ids.has(edge.target_id);
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

function renderChapters() {
  const host = $("#chapterList"); host.replaceChildren();
  $("#chapterIndex").hidden = true;
}

function renderMap({ preserveViewport = false } = {}) {
  if (!state.page) { renderAnalysisAvailability(state.analysisStatus, false); return; }
  const visible = visiblePage();
  const nodes = visible.nodes;
  const edges = visible.edges;
  graph.setData(nodes, edges, state.selectedId, state.page?.lanes || [], { preserveViewport });
  renderLanes(nodes); renderChapters(); state.selectedId = graph.selectedId;
  const first = state.offset + 1; const last = state.offset + (state.page?.nodes.length || 0); const total = Number(state.page?.total_nodes || last);
  const edgeFirst = state.edgeOffset + 1; const edgeLast = state.edgeOffset + (state.page?.edges.length || 0); const edgeTotal = Number(state.page?.page_edge_total ?? edgeLast);
  const dense = Boolean(state.page?.overflow) || edgeTotal > state.page?.edges.length;
  $("#pageStatus").textContent = `${state.mode === "narrative" ? "Story elements" : "Nodes"} ${first}–${last} of ${total} · routes ${edgeTotal ? `${edgeFirst}–${edgeLast} of ${edgeTotal}` : "none"}${dense ? " · bounded" : ""}`;
  $("#previousPage").disabled = state.cursorHistory.length === 0; $("#nextPage").disabled = nextCursor() === null;
  const nodeIds = new Set(nodes.map((node) => node.id)); const continuations = edges.filter((edge) => !nodeIds.has(edge.source_id) || !nodeIds.has(edge.target_id)).length;
  $("#visibleStatus").textContent = `${nodes.length} ${state.mode === "narrative" ? "story elements" : "nodes"} · ${edges.length} routes${continuations ? ` · ${continuations} continuations` : ""}`;
  const generation = state.page?.generation_status;
  renderAnalysisAvailability(generation, true);
  $("#generationStatus").hidden = !generation;
  if (generation) $("#generationStatus").textContent = `${generation.freshness} · ${String(generation.analysis_status || "unknown").replaceAll("_", " ")}`;
  const coverage = state.page?.coverage || {}; const summary = $("#coverageSummary"); summary.replaceChildren();
  if (state.mode === "narrative") summary.append(element("strong", "", "Narrative Map"), element("span", "", `${nodes.filter((node) => node.kind === "event_cluster").length} event clusters`), element("span", "", `${state.page.hidden_technical_count || 0} technical atoms collapsed`));
  else if (["inspection", "canonical"].includes(state.mode)) summary.append(element("strong", "", state.mode === "canonical" ? "Canonical authority" : "Inspection coverage"), element("span", "", `${coverage.control_nodes ?? "—"} canonical records`), element("span", "", `${coverage.suppressed_records ?? 0} presentation suppressions`));
  const selected = graph.elements().find((item) => item.id === state.selectedId); if (selected) selectItem(selected);
}

function updateModeHeader() {
  const narrative = state.mode === "narrative";
  const inspection = state.mode === "inspection"; const canonical = state.mode === "canonical";
  $("#inspectionMapButton").disabled = !state.inspectionPage;
  $("#canonicalMapButton").disabled = !state.canonicalPage;
  $("#mapEyebrow").textContent = narrative ? "Story Map" : inspection ? "Advanced deterministic inspection" : "Advanced canonical graph";
  $("#mapTitle").textContent = narrative ? "Chronological story" : inspection ? "Choices, routes, and rejoins" : "Every canonical record";
  $("#projectBadge").textContent = narrative ? "Narrative Map" : inspection ? "M10 Inspection · advanced" : "M10 Canonical · advanced";
  if (!state.narrativeMapPage) $("#fallbackReason").textContent = `${String(state.narrativeReason || "narrative map not yet available").replaceAll("_", " ")}. ${inspection ? "Deterministic inspection fallback" : canonical ? "Canonical fallback" : "No fallback"} is shown.`;
}

async function switchMode(mode) {
  const page = mode === "narrative" ? state.narrativeMapPage : mode === "inspection" ? state.inspectionPage : mode === "canonical" ? state.canonicalPage : null;
  if (!page) { toast("That map is unavailable for this analysis result"); return; }
  state.mode = mode; state.page = page; state.cursorHistory = []; state.offset = Number(state.page?.offset || 0); state.edgeOffset = Number(state.page?.edge_offset || 0); state.edgeCursor = null; state.selectedId = null;
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

function renderInspectionDerivations(detail, detailMode = state.mode) {
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
  for (const linked of detail.linked_records || []) { if (linked.id === detail.element?.id) continue; const button = element("button", "quiet-button linked-record", `${String(linked.kind || "record").replaceAll("_", " ")} · ${linked.title || linked.id}`); button.type = "button"; button.addEventListener("click", () => openDetail(linked.id, false, detailMode)); linkHost.append(button); }
  $("#derivationPanel").hidden = !(regionHost.children.length || proofHost.children.length || linkHost.children.length);
}

function normalizedSceneDetail(detail, elementId) {
  const occurrence = detail.selected_occurrence || detail.call_occurrences?.find((item) => item.id === detail.selected_occurrence_id);
  const selected = occurrence || detail.temporary_branch || detail.boundary || detail.chapter || detail.lane || detail.scene || detail.loop_hubs?.[0] || { id: elementId, kind: "scene" };
  const pageNode = state.page?.nodes.find((node) => node.id === elementId);
  const atoms = detail.atoms || [];
  const relatedScenes = detail.related_scenes || [];
  const kind = occurrence ? "call-site occurrence" : detail.temporary_branch ? "temporary branch" : detail.boundary ? "scene boundary" : detail.chapter ? "chapter" : detail.lane ? "persistent lane" : detail.loop_hubs?.length ? "repeatable scene" : "scene";
  const summary = occurrence
    ? `${occurrence.referenced_atom_ids?.length || 0} narrative atom references at this call site.`
    : detail.temporary_branch
      ? `${detail.temporary_branch.arms?.length || 0} temporary arms nested inside the parent scene.`
      : detail.chapter || detail.lane || detail.boundary
        ? `${relatedScenes.length} related scenes in this bounded detail response.`
        : `${atoms.length} deterministic story atoms with canonical and source provenance.`;
  const choices = (detail.temporary_branch?.arms || []).map((arm) => ({ id: arm.id, caption: `Arm ${Number(arm.ordinal || 0) + 1}`, label: `${arm.scene_ids?.length || 0} arm-local scenes`, expression: "" }));
  const requirements = (occurrence?.guard_fact_ids || []).map((id) => ({ id, label: "Call-site guard", expression: id }));
  const canonicalFocus = detail.canonical_records?.[0]?.id || detail.canonical_escape_ids?.[0] || null;
  const linkedRecords = [];
  if (occurrence && detail.caller_scene) linkedRecords.push({ ...detail.caller_scene, kind: "caller scene" });
  if (detail.scene && detail.boundary && detail.boundary.id !== elementId) linkedRecords.push({ ...detail.boundary, title: `${String(detail.boundary.strength || "scene").replaceAll("_", " ")} boundary`, kind: "scene boundary" });
  return {
    ...detail,
    element: { ...selected, id: elementId, title: pageNode?.title || selected.title || kind, kind, summary },
    member_route_nodes: [...atoms.map((atom) => ({ ...atom, title: atom.label || String(atom.kind || "story atom").replaceAll("_", " ") })), ...relatedScenes.map((scene) => ({ ...scene, title: scene.title || "Related scene" }))],
    member_route_edges: [], predecessor_ids: [], successor_ids: [], choices, requirements, effects: [],
    dialogue: atoms.filter((atom) => atom.kind === "dialogue"), narration: atoms.filter((atom) => atom.kind === "narration"), facts: [],
    linked_records: linkedRecords, canonical_focus_id: canonicalFocus, canonical_focus_offset: 0,
  };
}

async function openDetail(elementId, strict = false, detailMode = state.mode) {
  const token = state.detailRunToken + 1; state.detailRunToken = token;
  try {
    const sceneCitation = detailMode === "scenes";
    let detail = sceneCitation ? await api.sceneDetail(elementId) : detailMode === "narrative" ? await api.narrativeDetail(elementId) : await api.inspectionDetail(detailMode === "canonical" ? "canonical" : "simplified", elementId);
    if (token !== state.detailRunToken) {
      if (strict) throw new TypeError("The cited authority detail was superseded");
      return;
    }
    if (detail.status === "unavailable") {
      renderAnalysisAvailability(detail.generation_status, Boolean(state.page)); toast("This inspection result is unavailable for the retained generation");
      if (strict) throw new TypeError("The cited authority detail is unavailable");
      return;
    }
    if (sceneCitation) detail = normalizedSceneDetail(detail, elementId);
    state.detail = detail; state.selectedId = elementId;
    const selected = detail.element; $("#detailTitle").textContent = selected.title || String(selected.presentation_role || selected.role || selected.kind || "Story element").replaceAll("_", " ");
    $("#detailKind").textContent = String(selected.source_kind || selected.presentation_role || selected.kind || selected.role || "route element").replaceAll("_", " ");
    $("#detailSummary").textContent = selected.unsupported_status || selected.summary || "Authoritative local context and exact source evidence.";
    $("#canonicalEscapeButton").hidden = detailMode === "canonical" || !detail.canonical_focus_id;
    const strip = $("#pathStrip"); strip.replaceChildren();
    for (const id of detail.predecessor_ids || []) strip.append(element("span", "path-stop predecessor", `← ${titleFor(id)}`));
    strip.append(element("strong", "path-stop current", $("#detailTitle").textContent));
    for (const id of detail.successor_ids || []) strip.append(element("span", "path-stop successor", `${titleFor(id)} →`));
    renderTechnicalMembers(detail);
    renderInspectionDerivations(detail, detailMode);
    const facts = $("#detailFacts"); facts.replaceChildren(); const allFacts = detail.facts || [];
    addFactGroup(facts, "Exact choices", detail.choices, "choice"); addFactGroup(facts, "Requirements", detail.gates || detail.requirements || allFacts.filter((item) => String(item.kind || "").includes("gate") || String(item.type || "").includes("require")), "gate"); addFactGroup(facts, "Effects", detail.effects || allFacts.filter((item) => String(item.kind || "").includes("effect")), "effect"); addFactGroup(facts, "Dialogue", detail.dialogue, "dialogue"); addFactGroup(facts, "Narration", detail.narration, "narration");
    const interpretations = $("#interpretations"); interpretations.replaceChildren();
    $("#interpretationPanel").hidden = detailMode === "narrative" || sceneCitation;
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
  } catch (error) { if (token === state.detailRunToken) toast(error.message); if (strict) throw error; }
}

async function openCanonicalRecord() {
  const focusId = state.detail?.canonical_focus_id; if (!focusId) return;
  if (state.detail?.level === "scene_detail") {
    const raw = await api.inspectionMap("canonical", 0, ROUTE_PAGE_SIZE, 0, ROUTE_EDGE_PAGE_SIZE, { focus: focusId });
    if (raw.status === "unavailable") { toast("The matching M10 canonical record is unavailable"); return; }
    const page = normalizedPage(raw, "canonical");
    showLevel("route_map"); state.mode = "canonical"; state.page = page; state.canonicalPage = page; state.cursorHistory = []; state.offset = Number(page.offset || 0); state.edgeOffset = 0; state.selectedId = focusId;
    updateModeHeader(); renderMap(); graph.world.querySelector(`[data-element-id="${CSS.escape(focusId)}"]`)?.focus();
    return;
  }
  showLevel("route_map"); state.mode = "canonical"; state.page = null; state.canonicalPage = null; state.cursorHistory = []; state.offset = Number(state.detail.canonical_focus_offset || 0); state.edgeOffset = 0; state.selectedId = focusId;
  await loadRoutePage({ offset: state.offset, edgeOffset: 0 });
  graph.world.querySelector(`[data-element-id="${CSS.escape(focusId)}"]`)?.focus();
}

function titleFor(id) { return state.page?.nodes.find((node) => node.id === id)?.title || "Adjacent event"; }

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
  $("#narrativeJobsButton").addEventListener("click", () => {
    const drawer = $("#narrativeDrawer"); drawer.hidden = !drawer.hidden;
    $("#narrativeJobsButton").setAttribute("aria-expanded", String(!drawer.hidden));
    if (!drawer.hidden) renderNarrativeDrawer();
  });
  $("#closeNarrativeDrawer").addEventListener("click", () => { $("#narrativeDrawer").hidden = true; $("#narrativeJobsButton").setAttribute("aria-expanded", "false"); });
  $("#narrativeRunForm").addEventListener("submit", prepareNarrativeRun);
  $("#confirmNarrative").addEventListener("click", confirmNarrativeRun);
  $("#cancelNarrative").addEventListener("click", cancelNarrativeRun);
  $("#retryNarrative").addEventListener("click", retryNarrativeRun);
  for (const [id, key] of [["technicalToggle", "include_technical"], ["unresolvedToggle", "include_unresolved"]]) $("#" + id).addEventListener("change", (event) => { state.settings[key] = event.target.checked; renderMap(); api.saveSettings(state.settings).catch(() => {}); });
  $("#inspectionMapButton").addEventListener("click", () => switchMode("inspection")); $("#canonicalMapButton").addEventListener("click", () => switchMode("canonical"));
  $("#previousPage").addEventListener("click", previousRoutePage); $("#nextPage").addEventListener("click", nextRoutePage);
  $("#zoomIn").addEventListener("click", () => { $("#zoomValue").textContent = `${Math.round(graph.zoomBy(.1) * 100)}%`; }); $("#zoomOut").addEventListener("click", () => { $("#zoomValue").textContent = `${Math.round(graph.zoomBy(-.1) * 100)}%`; }); $("#fitMap").addEventListener("click", () => { graph.fit(); $("#zoomValue").textContent = `${Math.round(graph.scale * 100)}%`; });
  $("#backToRouteMap").addEventListener("click", () => { showLevel("route_map"); graph.world.querySelector(`[data-element-id="${CSS.escape(state.selectedId || "")}"]`)?.focus(); }); $("#detailView").addEventListener("keydown", (event) => { if (event.key === "Escape") $("#backToRouteMap").click(); });
  $("#canonicalEscapeButton").addEventListener("click", openCanonicalRecord);
  $("#diagnosticsButton").addEventListener("click", showDiagnostics); $("#closeDiagnostics").addEventListener("click", () => $("#diagnosticsDialog").close());
  $("#settingsButton").addEventListener("click", () => { const choices = ["system", "light", "dark"]; state.settings.theme = choices[(choices.indexOf(state.settings.theme) + 1) % choices.length]; document.documentElement.dataset.theme = state.settings.theme; graph.draw(); api.saveSettings(state.settings).catch(() => {}); });
  $("#quitButton").addEventListener("click", async () => { await api.shutdown(); document.body.replaceChildren(element("main", "shutdown-message", "Story Mapper has closed. You can close this tab.")); });
  document.addEventListener("keydown", (event) => { if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) { event.preventDefault(); $("#searchInput").focus(); } });
}

async function start() {
  bind();
  try { const bootstrap = await api.bootstrap(); api.configureM12(bootstrap.routes?.m12); state.settings = { ...state.settings, ...(bootstrap.settings || {}) }; document.documentElement.dataset.theme = state.settings.theme; $("#technicalToggle").checked = state.settings.include_technical; $("#unresolvedToggle").checked = state.settings.include_unresolved; renderRecent(bootstrap.recent_projects || []); showPrimary("welcome"); } catch (error) { renderRecent([]); toast(error.message); }
}

start();
export { api, graph, state, element, normalizedPage };
