import { DEFAULT_NARRATIVE_BATCH_LIMITS, DEFAULT_NARRATIVE_LIMITS, LocalApi, stableRouteJson } from "./api.js";
import { ROUTE_EDGE_PAGE_SIZE, ROUTE_PAGE_SIZE } from "./contract.js";
import { RouteGraph } from "./graph.js";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const api = new LocalApi();
const CURSOR_HISTORY_LIMIT = 12;

const state = {
  project: null, page: null, scenePage: null, aiPage: null, technicalPage: null, inspectionPage: null, canonicalPage: null, sceneReason: null, aiReason: null, mode: "scenes",
  analysisStatus: null,
  offset: 0, edgeOffset: 0, edgeCursor: null, cursorHistory: [], selectedId: null, detail: null, detailRunToken: 0,
  narrativeEnabled: false, narrativeSnapshot: null, narrativeJobs: [], narrativeByOwner: new Map(),
  narrativeRun: null, narrativePreparation: null, narrativeLastRequest: null, narrativePollToken: 0,
  organization: null, prepared: null, assemblyId: null, windowResolution: null,
  route: { sourceItem: null, sourceId: null, activeSourceId: null, destination: null, requestIdentity: null, result: null, phase: "idle", cached: false, stale: false, error: null, runToken: 0 },
  settings: { theme: "system", include_technical: true, include_unresolved: true },
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}

function narrativeForOwner(ownerId) {
  return state.narrativeByOwner.get(ownerId)?.artifact || null;
}

function narrativeForElement(elementId, detail = null) {
  const pageNode = state.page?.nodes.find((node) => node.id === elementId);
  const ownerId = pageNode?.scene_id || detail?.scene?.id || elementId;
  return narrativeForOwner(ownerId) || narrativeForOwner(elementId);
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

async function revealNarrativeCitations(claim, host, button) {
  button.disabled = true; button.textContent = "Loading citations…";
  try {
    const response = await api.narrativeCitations(claim.claim_id);
    const citations = element("div", "narrative-citations");
    for (const citation of response.citations) {
      const record = citation.record || {}; const source = record.source || {};
      const item = element("article", "narrative-citation");
      item.append(element("strong", "", `${citation.authority.toUpperCase()} · ${citation.record_kind} · ${citation.record_id}`));
      const sourceText = record.source_text || record.text || record.excerpt;
      if (sourceText) item.append(element("pre", "", sourceText));
      else item.append(element("pre", "", stableRouteJson(record)));
      if (source.path || source.relative_path || source.start_line) item.append(element("span", "", `${source.path || source.relative_path || "source"}:${source.start_line || source.start?.line || "?"}`));
      citations.append(item);
    }
    if (!citations.children.length) citations.append(element("span", "muted", "No direct citation leaves were resolved."));
    host.append(citations); button.remove();
  } catch (error) { button.disabled = false; button.textContent = "Retry citations"; toast(error.message); }
}

function renderNarrativeClaims(host, artifact) {
  for (const claim of artifact.claims || []) {
    const article = element("article", "narrative-claim"); article.dataset.claimClass = claim.claim_class;
    const label = claim.claim_class === "factual" ? "Factual claim" : claim.claim_class === "interpretive" ? "AI interpretation" : "Review suggestion";
    const scope = claim.context_scope === "comparison" ? " · route comparison" : claim.context_scope === "ordered_summary" ? " · ordered summary" : "";
    article.append(element("strong", "", `${label}${scope}`), element("p", "", claim.text));
    const button = element("button", "quiet-button", "Show citations"); button.type = "button";
    button.addEventListener("click", () => revealNarrativeCitations(claim, article, button));
    article.append(button); host.append(article);
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
  const active = NARRATIVE_ACTIVE_STATES.has(run?.state);
  $("#prepareNarrative").disabled = active;
  $("#cancelNarrative").hidden = !active;
  $("#retryNarrative").hidden = !NARRATIVE_RETRY_STATES.has(run?.state) || !state.narrativeLastRequest;
  if (!run || run.state === "disabled") status.textContent = "Cloud AI is off. Preparing a manifest sends no story material.";
  else if (run.state === "prepared") status.textContent = "Prepared locally. No story material has been sent; confirmation is still required.";
  else if (run.state === "running") status.textContent = "Narrative jobs are running. Valid results are committed independently.";
  else if (run.state === "cancelling") status.textContent = "Cancelling provider work. Validated completed artifacts are being preserved.";
  else {
    const latest = run.latest_run || {}; const usage = latest.usage || {};
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
  state.narrativeLastRequest = request;
  state.narrativePreparation = await api.prepareNarrative(request);
  state.narrativeRun = await api.narrativeStatus();
  renderNarrativeRun(); showNarrativeConsent(state.narrativePreparation);
}

async function prepareNarrativeRun(event) {
  event?.preventDefault();
  try { await prepareNarrativeRequest(narrativeRunRequest()); }
  catch (error) { toast(error.message); }
}

async function confirmNarrativeRun(event) {
  event.preventDefault();
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
  try { state.narrativeRun = await api.cancelNarrative(); renderNarrativeRun(); toast("Cancellation requested; validated work is preserved"); }
  catch (error) { toast(error.message); }
}

async function retryNarrativeRun() {
  if (!state.narrativeLastRequest) { toast("No prior Narrative scope is available"); return; }
  try { await prepareNarrativeRequest(state.narrativeLastRequest); }
  catch (error) { toast(error.message); }
}

async function loadNarrativeRunStatus() {
  try {
    state.narrativeRun = await api.narrativeStatus(); renderNarrativeRun();
    if (NARRATIVE_ACTIVE_STATES.has(state.narrativeRun.state)) pollNarrativeRun();
  } catch (_error) { state.narrativeRun = null; renderNarrativeRun(); }
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
  $("#narrativeToggle").disabled = !state.narrativeSnapshot || state.narrativeSnapshot.status !== "available";
  renderNarrativeDrawer();
}

const graph = new RouteGraph({
  viewport: $("#mapViewport"), world: $("#mapWorld"), canvas: $("#edgeCanvas"),
  onSelect: (item) => selectItem(item), onOpen: (item) => openDetail(item.id),
});

function toast(message) {
  const host = $("#toast"); host.textContent = message; host.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { host.hidden = true; }, 2800);
}

function routeText(value) {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (!value || typeof value !== "object") return "Unknown";
  const primary = value.instruction || value.text || value.label || value.title || value.caption || value.expression || value.variable_name || value.id || "Route item";
  const condition = value.condition || value.requirement;
  return condition && !String(primary).includes(String(condition)) ? `${primary} · ${condition}` : String(primary);
}

function routeArray(value) { return Array.isArray(value) ? value : []; }

function routeScenes(candidate) {
  const ids = routeArray(candidate.scene_ids);
  const titles = Array.isArray(candidate.scene_titles) ? candidate.scene_titles : (Array.isArray(candidate.titles) ? candidate.titles : []);
  return ids.map((id, index) => ({ text: titles[index] || candidate.titles?.[id] || id, scene_id: id }));
}

function routeStartingAssumptions(candidate) {
  const direct = candidate.starting_assumptions || candidate.entry_preconditions || candidate.external_preconditions;
  if (Array.isArray(direct)) return direct;
  return routeArray(candidate.requirements)
    .filter((item) => ["entry_precondition", "external_precondition", "starting_assumption"].includes(item?.source || item?.resolution || item?.status || item?.kind))
    .map((item) => {
      const entry = item?.entry_precondition; const variable = entry?.variable;
      if (!entry || !variable?.name) return item;
      const identity = `${variable.scope || "store"}.${variable.name}`;
      return { ...item, text: `Start with ${identity} = ${JSON.stringify(entry.value)}.` };
    });
}

function routeSatisfyingEffects(candidate) {
  const direct = candidate.satisfying_effect_claims || candidate.earlier_satisfying_effects || candidate.satisfying_effects || candidate.earlier_effects;
  if (Array.isArray(direct)) return direct;
  return routeArray(candidate.requirements).map((item) => {
    if (item?.satisfying_effect) return item.satisfying_effect;
    if (item?.satisfying_effect_id) return { text: `${item.expression} - effect ${item.satisfying_effect_id}`, fact_id: item.fact_id, satisfying_effect_id: item.satisfying_effect_id, evidence_ids: item.evidence_ids, variable: item.variable };
    if (item?.repeated_count) return { text: `${item.expression} - repeated ${item.repeated_count} time(s)`, fact_id: item.fact_id, repeated_count: item.repeated_count, evidence_ids: item.evidence_ids, variable: item.variable };
    return null;
  }).filter(Boolean);
}

function appendRouteSection(host, title, values, ordered = false) {
  const items = routeArray(values);
  if (!items.length) return;
  const section = element("section", "route-section"); section.append(element("h4", "", title));
  const list = element(ordered ? "ol" : "ul", "route-list");
  for (const value of items) {
    const item = element("li");
    if (value && typeof value === "object") {
      const claim = element("details", "route-claim");
      claim.append(element("summary", "", routeText(value)), element("pre", "", stableRouteJson(value)));
      item.append(claim);
    } else item.textContent = routeText(value);
    list.append(item);
  }
  section.append(list); host.append(section);
}

function renderRouteCandidate(host, candidate) {
  appendRouteSection(host, "Instructions", candidate.instructions, true);
  appendRouteSection(host, "Starting assumptions", routeStartingAssumptions(candidate));
  appendRouteSection(host, "Ordered human scenes", candidate.scene_claims || routeScenes(candidate), true);
  appendRouteSection(host, "Visible choices", candidate.visible_choice_claims || candidate.visible_choices, true);
  const repeats = candidate.repeated_action_claims || candidate.repeated_actions || candidate.repeats || (candidate.loop_count ? [`Repeat the supported action ${candidate.loop_count} additional time(s).`] : []);
  appendRouteSection(host, "Repeated actions", repeats, true);
  appendRouteSection(host, "Requirements", candidate.requirements);
  appendRouteSection(host, "Earlier satisfying effects", routeSatisfyingEffects(candidate));
  appendRouteSection(host, "Persistent commitments", candidate.persistent_commitment_claims || candidate.persistent_commitments || candidate.persistent_lane_ids);
  appendRouteSection(host, "Uncertainty warnings", candidate.uncertainty_claims || candidate.uncertainty_warnings || candidate.warnings);
}

function renderRouteTechnical(result) {
  const host = $("#routeTechnicalBody"); host.replaceChildren();
  const rows = [
    ["Semantic status", result.status], ["Request", result.request_identity],
    ["Completion", result.complete ? "Complete" : "Incomplete"], ["Termination", result.termination_reason || "none"],
    ["Exhaustive", result.exhaustive ? "Yes" : "No"], ["Closed world", result.closed_world ? "Yes" : "No"],
    ["Selected occurrence", result.recommended?.selected_occurrence_id || "not applicable"],
  ];
  const description = element("dl", "route-technical-grid");
  for (const [term, value] of rows) description.append(element("dt", "", term), element("dd", "", value ?? "unknown"));
  host.append(description);
  const provenance = result.recommended?.provenance || result.negative_provenance || result.provenance;
  if (provenance && typeof provenance === "object") {
    const exact = element("details", "route-provenance"); exact.append(element("summary", "", "Provenance and evidence"), element("pre", "", stableRouteJson(provenance))); host.append(exact);
  }
  const accounting = element("details", "route-accounting"); accounting.append(element("summary", "", "Budgets and diagnostics"), element("pre", "", stableRouteJson({ budget_usage: result.budget_usage, diagnostics: result.diagnostics })));
  host.append(accounting);
}

function renderRoutePanel() {
  const route = state.route; const source = route.sourceItem;
  $("#routeDestination").textContent = source ? source.title || source.label || source.id : "Select a scene or M10 record.";
  $("#solveRoute").disabled = !source || ["resolving", "running", "cancelling"].includes(route.phase) || !api.m12Routes;
  const statuses = {
    idle: "Select a supported destination.", ready: "Ready to solve locally.", resolving: "Checking the exact destination…",
    running: route.progressLabel || "Solving locally…", cancelling: "Cancelling safely…", cancelled: "Solve cancelled. No result was replaced.",
    complete: route.cached ? "Cached route ready." : "Route ready.", stale: "Result is stale for this selection. Solve again.",
    failure: route.error || "Route solve failed. Retry is safe.",
  };
  $("#routeStatus").textContent = statuses[route.phase] || statuses.idle;
  const busy = ["resolving", "running", "cancelling"].includes(route.phase);
  $("#routePanel").setAttribute("aria-busy", String(busy));
  $("#cancelRoute").hidden = !busy; $("#retryRoute").hidden = !["cancelled", "failure", "stale"].includes(route.phase);
  $("#exportRouteJson").hidden = !route.result;
  const badge = $("#routeBadge"); badge.hidden = !route.result; badge.textContent = route.result?.badge || "";
  const resultHost = $("#routeResult"); resultHost.hidden = !route.result;
  const recommended = $("#recommendedRouteBody"); recommended.replaceChildren();
  if (route.result?.recommended) renderRouteCandidate(recommended, route.result.recommended);
  else if (route.result) {
    const message = route.result.complete === false
      ? "Search incomplete. No reachability or infeasibility conclusion was published."
      : route.result.status === "dynamic_or_unknown_possibility"
        ? "No route is proven; unresolved dynamic or unknown behavior could change the result."
        : route.result.status === "state_infeasible"
          ? "The resolved static paths are state-infeasible under exact contradiction evidence."
          : "No route exists in the exhaustively resolved static graph.";
    recommended.append(element("p", "muted", message));
  }
  const alternatives = $("#routeAlternatives"); alternatives.replaceChildren();
  for (const [index, candidate] of routeArray(route.result?.alternatives).entries()) {
    const record = element("details", "route-alternative"); record.append(element("summary", "", candidate.title || `Alternative ${index + 1}`));
    const body = element("div", "route-alternative-body"); renderRouteCandidate(body, candidate); record.append(body); alternatives.append(record);
  }
  $("#routeAlternativesSection").hidden = !alternatives.children.length;
  if (route.result) renderRouteTechnical(route.result); else $("#routeTechnicalBody").replaceChildren();
}

function selectRouteSource(item) {
  const changed = state.route.sourceId && state.route.sourceId !== item.id;
  state.route.sourceItem = item; state.route.sourceId = item.id; state.route.error = null;
  if (changed && (state.route.result || state.route.requestIdentity)) { state.route.stale = true; if (state.route.phase !== "running") state.route.phase = "stale"; }
  else if (!["resolving", "running", "cancelling"].includes(state.route.phase) && !state.route.result) state.route.phase = "ready";
  renderRoutePanel();
}

async function resolveRouteDestination(source) {
  const direct = source.route_destination || (source.destination_kind && source.target_id ? { kind: source.destination_kind, target_id: source.target_id, title: source.title, subtitle: source.summary } : null);
  if (direct?.kind && direct?.target_id) return direct;
  const page = await api.routeDestinations(source.id, 0, ROUTE_PAGE_SIZE);
  const candidates = routeArray(page.nodes || page.destinations);
  const targetIds = new Set([source.id, source.occurrence_id, source.route_target_id].filter(Boolean));
  const exact = candidates.filter((item) => targetIds.has(item.target_id) && typeof item.kind === "string");
  exact.sort((left, right) => String(left.kind).localeCompare(String(right.kind)) || String(left.target_id).localeCompare(String(right.target_id)));
  if (!exact.length) throw new Error("This selection is not a supported M12 destination");
  return exact[0];
}

function routeTask(value) { return value?.task || value || {}; }

async function waitForRouteTask(initial, token) {
  let task = routeTask(initial);
  while (["pending", "running", "cancelling"].includes(task.state)) {
    state.route.progressLabel = String(task.stage || "Solving route").replaceAll("_", " "); renderRoutePanel();
    await new Promise((resolve) => setTimeout(resolve, 350));
    if (token !== state.route.runToken) return null;
    task = routeTask(await api.progress());
  }
  return task;
}

async function runRouteSolve() {
  const source = state.route.sourceItem; if (!source) return;
  const token = state.route.runToken + 1; state.route.runToken = token; state.route.activeSourceId = source.id;
  state.route.phase = "resolving"; state.route.error = null; state.route.progressLabel = null; state.route.stale = Boolean(state.route.result); renderRoutePanel();
  try {
    const destination = await resolveRouteDestination(source); if (token !== state.route.runToken) return;
    state.route.destination = destination; state.route.phase = "running"; renderRoutePanel();
    const response = await api.solveRoute(destination.kind, destination.target_id); if (token !== state.route.runToken) return;
    state.route.requestIdentity = response.request_identity; state.route.cached = response.cached;
    let result = response.result;
    if (!response.cached) {
      const terminal = await waitForRouteTask(response.analysis, token); if (!terminal || token !== state.route.runToken) return;
      if (terminal.state === "cancelled") { state.route.phase = "cancelled"; state.route.stale = Boolean(state.route.result); renderRoutePanel(); return; }
      if (!["complete", "completed"].includes(terminal.state)) throw new Error(terminal.error?.message || terminal.message || "Route solve failed");
      result = await api.routeResult(response.request_identity); if (token !== state.route.runToken) return;
    }
    state.route.result = result; state.route.stale = state.route.sourceId !== state.route.activeSourceId; state.route.phase = state.route.stale ? "stale" : "complete"; renderRoutePanel();
  } catch (error) {
    if (token !== state.route.runToken) return;
    const stale = String(error.code || "").toLocaleLowerCase().includes("stale");
    state.route.phase = stale ? "stale" : "failure"; state.route.stale = stale || Boolean(state.route.result); state.route.error = error.message; renderRoutePanel();
  }
}

async function cancelRouteSolve() {
  if (!["resolving", "running"].includes(state.route.phase)) return;
  const serverTaskStarted = state.route.phase === "running";
  state.route.runToken += 1; const cancelToken = state.route.runToken;
  state.route.phase = "cancelling"; renderRoutePanel();
  if (serverTaskStarted) {
    try {
      const cancelling = await api.cancelAnalysis();
      await waitForRouteTask(cancelling, cancelToken);
    } catch (error) {
      if (cancelToken !== state.route.runToken) return;
      state.route.phase = "failure"; state.route.error = error.message; renderRoutePanel(); return;
    }
  }
  if (cancelToken !== state.route.runToken) return;
  state.route.phase = "cancelled"; state.route.stale = Boolean(state.route.result); renderRoutePanel();
}

function exportRouteJson() {
  const result = state.route.result; if (!result) return;
  const blob = new Blob([stableRouteJson(result)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob); const link = element("a"); const identity = String(result.request_identity || "route").replace(/[^a-z0-9._-]+/gi, "-").slice(0, 80);
  link.href = url; link.download = `route-${identity || "result"}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
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

function sceneNodeOrder(node) {
  const pageOrder = Number(node.page_order);
  if (node.page_order !== null && node.page_order !== undefined && node.page_order !== "" && Number.isFinite(pageOrder)) return pageOrder;
  const ordinal = Number(node.ordinal);
  return Number.isFinite(ordinal) ? ordinal : 0;
}

function normalizedPage(page, mode = state.mode) {
  if (mode === "scenes") {
    const laneLabels = { spine: "Story spine", persistent_route: "Persistent route", terminal_route: "Terminal route" };
    const lanes = page.lanes.map((lane) => ({ ...lane, label: laneLabels[lane.kind] || String(lane.kind || "story route").replaceAll("_", " ") }));
    const laneById = new Map(lanes.map((lane) => [lane.id, lane]));
    const nodes = page.nodes.map((node) => {
      const lane = laneById.get(node.lane_id) || { kind: "spine", label: "Story spine" };
      const presentationKind = node.kind;
      const kind = presentationKind === "temporary_branch" ? "choice" : node.repeatable ? "loop" : "event";
      const summary = presentationKind === "temporary_branch"
        ? `${node.arms?.length || 0} temporary arms · rejoins in scene`
        : node.occurrence_id
          ? `Call-site occurrence · ${node.referenced_atom_ids?.length || 0} referenced atoms`
          : `${node.atom_ids?.length || 0} story atoms · ${String(node.boundary_strength || "continuation").replaceAll("_", " ")} boundary`;
      return { ...node, order: sceneNodeOrder(node), presentation_kind: presentationKind, kind, role: presentationKind, lane_kind: lane.kind === "spine" ? "spine" : "persistent", lane_label: lane.label, summary };
    });
    return {
      ...page,
      nodes,
      edges: page.relationships.map((relationship) => ({ ...relationship, role: relationship.kind, source_id: relationship.source_id, target_id: relationship.target_id, interactive: false })),
      lanes,
      edge_offset: page.relationship_offset,
      edge_next_offset: page.relationship_next_offset,
      page_edge_total: page.page_relationship_total,
      edge_limit: page.relationship_limit,
      generation_status: { freshness: "current", analysis_status: "current_complete" },
      navigation: { next: page.navigation?.next ? { offset: page.navigation.next.offset, edge_offset: page.navigation.next.relationship_offset || 0 } : null },
    };
  }
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
  let scenes = null; let simplified = null; let canonical = null; let comparison = null;
  try { scenes = await api.sceneMap(0, ROUTE_PAGE_SIZE, 0, ROUTE_EDGE_PAGE_SIZE); } catch (_error) { scenes = null; }
  state.scenePage = scenes?.status === "available" ? normalizedPage(scenes, "scenes") : null;
  state.sceneReason = scenes?.reason || "scene presentation not yet available";
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
  if (state.scenePage) { state.mode = "scenes"; state.page = state.scenePage; }
  else if (inspectionCurrent) { state.mode = "inspection"; state.page = state.inspectionPage; }
  else if (canonicalCurrent) { state.mode = "canonical"; state.page = state.canonicalPage; }
  else if (state.inspectionPage) { state.mode = "inspection"; state.page = state.inspectionPage; }
  else if (state.technicalPage) { state.mode = "technical"; state.page = state.technicalPage; }
  else { state.mode = "inspection"; state.page = null; }
  const status = state.page?.generation_status || simplified?.generation_status || canonical?.generation_status || null;
  const hasMap = Boolean(state.page);
  renderAnalysisAvailability(status, hasMap);
  $("#fallbackNotice").hidden = !hasMap || Boolean(state.scenePage);
  $("#fallbackTitle").textContent = "Scene presentation unavailable.";
  $("#fallbackReason").textContent = `${String(state.sceneReason).replaceAll("_", " ")}. ${state.mode === "inspection" ? "M10 Inspection" : state.mode === "canonical" ? "M10 Canonical" : "Technical Structure"} is shown.`;
  updateModeHeader();
  if (hasMap) renderMap();
  else graph.setData([], [], null, []);
  return hasMap;
}

async function loadRoutePage(cursor = { offset: state.offset, edgeOffset: state.edgeOffset, edgeCursor: state.edgeCursor }) {
  try {
    const raw = state.mode === "scenes"
      ? await api.sceneMap(cursor.offset, ROUTE_PAGE_SIZE, cursor.edgeOffset, ROUTE_EDGE_PAGE_SIZE)
      : state.mode === "ai"
      ? await api.aiStoryMap(cursor.offset, ROUTE_PAGE_SIZE, cursor.edgeOffset, ROUTE_EDGE_PAGE_SIZE, cursor.edgeCursor ?? null)
      : ["inspection", "canonical"].includes(state.mode)
        ? await api.inspectionMap(state.mode === "canonical" ? "canonical" : "simplified", cursor.offset, ROUTE_PAGE_SIZE, cursor.edgeOffset, ROUTE_EDGE_PAGE_SIZE)
        : await api.routeMap(cursor.offset, ROUTE_PAGE_SIZE, cursor.edgeOffset, ROUTE_EDGE_PAGE_SIZE);
    if (raw.status === "unavailable") { renderAnalysisAvailability(raw.generation_status, false); return false; }
    const page = normalizedPage(raw, state.mode);
    state.page = page;
    if (state.mode === "scenes") state.scenePage = page;
    else if (state.mode === "ai") state.aiPage = page;
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
  const nextRouteToken = state.route.runToken + 1;
  state.route = { sourceItem: null, sourceId: null, destination: null, requestIdentity: null, result: null, phase: "idle", cached: false, stale: false, error: null, runToken: nextRouteToken };
  renderRoutePanel();
  state.cursorHistory = [];
  state.offset = 0; state.edgeOffset = 0; state.edgeCursor = null; state.windowResolution = null; state.prepared = null;
  $("#scopePreview").textContent = "No story text is sent until an exact preview is confirmed.";
  return loadComparison();
}

async function enterAvailableWorkspace() {
  showPrimary("workspace"); showLevel("route_map");
  const available = await resetRoutePaging();
  await loadNarrative();
  await loadNarrativeRunStatus();
  if (available) renderMap();
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
  if (state.mode === "scenes") {
    const firstRaw = await api.sceneMap(0, ROUTE_PAGE_SIZE, 0, ROUTE_EDGE_PAGE_SIZE, query ? { query } : {});
    if (requestId !== searchM10WholeGraph.requestId || $("#searchInput").value.trim() !== query) return;
    if (firstRaw.status === "unavailable") { renderAnalysisAvailability(firstRaw.generation_status, Boolean(state.page)); return; }
    const firstMatch = firstRaw.search?.matches?.[0];
    let raw = firstRaw;
    if (firstMatch && Number(firstMatch.offset || 0) !== Number(firstRaw.offset || 0)) {
      raw = await api.sceneMap(Number(firstMatch.offset), ROUTE_PAGE_SIZE, 0, ROUTE_EDGE_PAGE_SIZE, { focus: firstMatch.id });
      raw.search = firstRaw.search;
    }
    const page = normalizedPage(raw, "scenes"); state.page = page; state.scenePage = page;
    state.offset = Number(page.offset || 0); state.edgeOffset = 0; state.cursorHistory = []; state.selectedId = firstMatch?.id || null;
    renderMap();
    if (query && !firstRaw.search?.total) $("#selectionStatus").textContent = "No whole-scene matches";
    else if (state.selectedId) graph.world.querySelector(`[data-element-id="${CSS.escape(state.selectedId)}"]`)?.focus();
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
    const row = element(state.mode === "scenes" ? "button" : "div", "line-key"); const swatch = element("i", `swatch ${lane.kind === "detour" ? "detour" : ""}`);
    if (state.mode === "scenes") { row.type = "button"; row.addEventListener("click", () => openDetail(lane.id)); }
    row.append(swatch, element("span", "", lane.label || String(lane.kind || "route").replaceAll("_", " "))); host.append(row);
  }
}

function renderChapters() {
  const host = $("#chapterList"); host.replaceChildren();
  const chapters = state.mode === "scenes" ? [...(state.page?.chapter_bands || [])].sort((left, right) => Number(left.ordinal || 0) - Number(right.ordinal || 0) || String(left.id).localeCompare(String(right.id))) : [];
  $("#chapterIndex").hidden = !chapters.length;
  for (const chapter of chapters) {
    const record = element("button", "chapter-record"); record.type = "button"; record.addEventListener("click", () => openDetail(chapter.id));
    record.append(element("strong", "", chapter.label || "Story"), element("span", "", `${chapter.scene_total ?? chapter.scene_ids?.length ?? 0} scenes`));
    host.append(record);
  }
}

function renderMap() {
  if (!state.page) { renderAnalysisAvailability(state.analysisStatus, false); return; }
  const visible = visiblePage();
  const nodes = state.mode === "scenes" && state.narrativeEnabled
    ? visible.nodes.map((node) => {
      const artifact = narrativeForOwner(node.scene_id || node.id);
      return artifact ? { ...node, deterministic_title: node.title, deterministic_summary: node.summary, title: artifact.title, summary: artifact.summary, narrative_artifact_id: artifact.artifact_id, narrative_publication: artifact.publication } : node;
    })
    : visible.nodes;
  const edges = visible.edges;
  graph.setData(nodes, edges, state.selectedId, state.page?.lanes || []);
  renderLanes(nodes); renderChapters(); state.selectedId = graph.selectedId;
  const first = state.offset + 1; const last = state.offset + (state.page?.nodes.length || 0); const total = Number(state.page?.total_nodes || last);
  const edgeFirst = state.edgeOffset + 1; const edgeLast = state.edgeOffset + (state.page?.edges.length || 0); const edgeTotal = Number(state.page?.page_edge_total ?? edgeLast);
  const dense = Boolean(state.page?.overflow) || edgeTotal > state.page?.edges.length;
  $("#pageStatus").textContent = `${state.mode === "scenes" ? "Scenes" : state.mode === "ai" ? "Events" : "Nodes"} ${first}–${last} of ${total} · routes ${edgeTotal ? `${edgeFirst}–${edgeLast} of ${edgeTotal}` : "none"}${dense ? " · bounded" : ""}`;
  $("#previousPage").disabled = state.cursorHistory.length === 0; $("#nextPage").disabled = nextCursor() === null;
  const nodeIds = new Set(nodes.map((node) => node.id)); const continuations = edges.filter((edge) => !nodeIds.has(edge.source_id) || !nodeIds.has(edge.target_id)).length;
  $("#visibleStatus").textContent = `${nodes.length} ${state.mode === "scenes" ? "scene elements" : state.mode === "ai" ? "events" : "nodes"} · ${edges.length} routes${continuations ? ` · ${continuations} continuations` : ""}`;
  const generation = state.page?.generation_status;
  renderAnalysisAvailability(generation, true);
  $("#generationStatus").hidden = !generation;
  if (generation) $("#generationStatus").textContent = `${generation.freshness} · ${String(generation.analysis_status || "unknown").replaceAll("_", " ")}`;
  const coverage = state.page?.coverage || {}; const summary = $("#coverageSummary"); summary.replaceChildren();
  if (state.mode === "scenes") {
    summary.append(element("strong", "", "Scene hierarchy"), element("span", "", `${state.page.chapter_bands?.length || 0} chapters · ${state.page.lanes?.length || 0} lanes`), element("span", "", `${nodes.filter((node) => node.presentation_kind === "temporary_branch").length} temporary choices on this page`));
    if (state.narrativeEnabled && state.narrativeSnapshot?.coverage) {
      const narrative = state.narrativeSnapshot.coverage;
      summary.append(element("span", "", `Narrative ${Number(narrative.scene_coverage_basis_points || 0) / 100}% · ${narrative.published_scene_jobs || 0}/${narrative.expected_scene_jobs || 0} scenes`));
    }
  }
  else if (state.mode === "ai") summary.append(element("strong", "", "Story coverage"), element("span", "", `${coverage.ai_owned_route_nodes || 0} AI-organized nodes`), element("span", "", `${coverage.technical_fallback_route_nodes || 0} technical fallback nodes`));
  else if (["inspection", "canonical"].includes(state.mode)) summary.append(element("strong", "", state.mode === "canonical" ? "Canonical authority" : "Inspection coverage"), element("span", "", `${coverage.control_nodes ?? "—"} canonical records`), element("span", "", `${coverage.suppressed_records ?? 0} presentation suppressions`));
  else summary.append(element("strong", "", "Technical authority"), element("span", "", `${coverage.control_nodes ?? "—"} control points`), element("span", "", `${coverage.technical_nodes ?? 0} collapsed steps`));
  const selected = graph.elements().find((item) => item.id === state.selectedId); if (selected) selectItem(selected);
}

function updateModeHeader() {
  const scenes = state.mode === "scenes"; const ai = state.mode === "ai";
  const inspection = state.mode === "inspection"; const canonical = state.mode === "canonical"; const technical = state.mode === "technical";
  $("#sceneMapButton").setAttribute("aria-pressed", String(scenes)); $("#aiMapButton").setAttribute("aria-pressed", String(ai)); $("#inspectionMapButton").setAttribute("aria-pressed", String(inspection)); $("#canonicalMapButton").setAttribute("aria-pressed", String(canonical)); $("#technicalMapButton").setAttribute("aria-pressed", String(technical));
  $("#sceneMapButton").disabled = !state.scenePage;
  $("#aiMapButton").disabled = !state.aiPage;
  $("#inspectionMapButton").disabled = !state.inspectionPage;
  $("#canonicalMapButton").disabled = !state.canonicalPage;
  $("#technicalMapButton").disabled = !state.technicalPage;
  $("#mapEyebrow").textContent = scenes ? "Deterministic scene presentation" : ai ? "AI Story Map" : inspection ? "Deterministic inspection" : canonical ? "Canonical technical graph" : "Technical Structure";
  $("#mapTitle").textContent = scenes ? "Scenes and chapters" : ai ? "The story at a glance" : inspection ? "Choices, routes, and rejoins" : canonical ? "Every canonical record" : "Authoritative control flow";
  $("#projectBadge").textContent = scenes ? "M11 Scenes" : ai ? "AI Story Map · applied" : inspection ? "M10 Inspection" : canonical ? "M10 Canonical" : "Technical Structure";
  const deterministicPresentation = scenes || inspection || canonical; $("#organizationPanel").hidden = deterministicPresentation; $("#organizeButton").hidden = deterministicPresentation;
  if (!state.scenePage) $("#fallbackReason").textContent = `${String(state.sceneReason || "scene presentation not yet available").replaceAll("_", " ")}. ${inspection ? "M10 Inspection" : canonical ? "M10 Canonical" : "Technical Structure"} is shown.`;
}

async function switchMode(mode) {
  if (mode === "ai" && !state.aiPage) { toast("Apply a validated organization before using the AI Story Map"); return; }
  const page = mode === "scenes" ? state.scenePage : mode === "ai" ? state.aiPage : mode === "inspection" ? state.inspectionPage : mode === "canonical" ? state.canonicalPage : state.technicalPage;
  if (!page) { toast("That map is unavailable for this analysis result"); return; }
  state.mode = mode; state.page = page; state.cursorHistory = []; state.offset = Number(state.page?.offset || 0); state.edgeOffset = Number(state.page?.edge_offset || 0); state.edgeCursor = mode === "ai" ? state.page?.edge_cursor ?? null : null; state.selectedId = null;
  updateModeHeader(); if (state.page) renderMap(); else await loadRoutePage({ offset: 0, edgeOffset: 0 });
}

function selectItem(item) { state.selectedId = item.id; $("#selectionStatus").textContent = `${item.title || String(item.role || item.kind || "route").replaceAll("_", " ")} · Enter for Detail / Evidence`; selectRouteSource(item); }

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
    member_route_edges: [],
    predecessor_ids: [],
    successor_ids: [],
    choices,
    requirements,
    effects: [],
    dialogue: atoms.filter((atom) => atom.kind === "dialogue"),
    narration: atoms.filter((atom) => atom.kind === "narration"),
    facts: [],
    linked_records: linkedRecords,
    canonical_focus_id: canonicalFocus,
    canonical_focus_offset: 0,
  };
}

async function openDetail(elementId) {
  const token = state.detailRunToken + 1; state.detailRunToken = token;
  try {
    const sceneMode = state.mode === "scenes";
    let detail = sceneMode ? await api.sceneDetail(elementId) : state.mode === "ai" ? await api.aiStoryDetail(elementId) : ["inspection", "canonical"].includes(state.mode) ? await api.inspectionDetail(state.mode === "canonical" ? "canonical" : "simplified", elementId) : await api.detail(elementId);
    if (token !== state.detailRunToken) return;
    if (detail.status === "unavailable") {
      if (sceneMode && state.inspectionPage) { await switchMode("inspection"); toast("Scene presentation became unavailable; M10 Inspection is shown"); }
      else if (state.mode === "ai") { await switchMode("technical"); toast("AI Story Map became unavailable; Technical Structure is shown"); }
      else { renderAnalysisAvailability(detail.generation_status, Boolean(state.page)); toast("This inspection result is unavailable for the retained generation"); }
      return;
    }
    if (sceneMode) detail = normalizedSceneDetail(detail, elementId);
    let narrativeArtifact = null;
    const narrativeSummary = sceneMode && state.narrativeEnabled ? narrativeForElement(elementId, detail) : null;
    if (narrativeSummary) {
      narrativeArtifact = await api.narrativeArtifact(narrativeSummary.artifact_id);
      if (token !== state.detailRunToken) return;
      detail = { ...detail, narrative_artifact: narrativeArtifact, element: { ...detail.element, deterministic_title: detail.element.title, deterministic_summary: detail.element.summary, title: narrativeArtifact.title, summary: narrativeArtifact.summary } };
    }
    state.detail = detail; state.selectedId = elementId;
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
    $("#interpretationPanel").hidden = sceneMode;
    if (narrativeArtifact) $("#interpretationPanel").hidden = false;
    const candidates = detail.ai_candidates || detail.candidates || selected.ai_candidates || [];
    const claims = detail.claims || candidates.flatMap((candidate) => candidate.claims || []);
    for (const candidate of candidates) { const article = element("article", "interpretation candidate"); article.append(element("strong", "", candidate.title || candidate.label || "Candidate"), element("p", "", candidate.summary || candidate.text || "")); if (candidate.correction) article.append(element("span", "correction", `Correction: ${candidate.correction.title || candidate.correction.text || "provided"}`)); if (candidate.pinned) article.append(element("span", "pin", "Pinned by reviewer")); interpretations.append(article); }
    for (const claim of claims) { const article = element("article", "interpretation claim"); article.append(element("strong", "", claim.label || "Evidence-backed claim"), element("p", "", claim.text || claim.claim || ""), element("span", "evidence-links", `Evidence: ${(claim.evidence_ids || []).join(", ") || "not supplied"}`)); interpretations.append(article); }
    if (narrativeArtifact) {
      const summary = element("article", "interpretation candidate");
      summary.append(element("strong", "", `${narrativeArtifact.publication === "partial" ? "Partial narrative" : "Narrative summary"} · AI interpretation; deterministic authority unchanged`), element("p", "", narrativeArtifact.summary));
      for (const warning of narrativeArtifact.warnings || []) summary.append(element("span", "correction", warning));
      interpretations.append(summary); renderNarrativeClaims(interpretations, narrativeArtifact);
    }
    if (!interpretations.children.length) interpretations.append(element("p", "muted", "No AI interpretation is attached; the technical map is authoritative."));
    const evidence = $("#evidenceList"); evidence.replaceChildren();
    for (const record of detail.evidence || []) {
      const article = element("article", "evidence-record"); article.dataset.evidenceId = record.id;
      const source = record.source || record.location || {}; const start = source.start?.line ?? source.start_line ?? record.start_line ?? "?"; const endLine = source.end?.line ?? source.end_line ?? record.end_line; const end = endLine && endLine !== start ? `–${endLine}` : "";
      article.append(element("span", "evidence-id", `${record.id} · ${record.kind || "source"}`), element("pre", "", evidenceExcerpt(record)), element("span", "source-line", `${source.path || record.source_path || record.path || "source unavailable"}:${start}${end} · ${evidenceLineBasis(record, source)}`)); evidence.append(article);
    }
    if (!evidence.children.length) evidence.append(element("p", "muted", "No exact evidence was returned."));
    showLevel("detail_evidence"); $("#backToRouteMap").focus();
  } catch (error) { if (token === state.detailRunToken) toast(error.message); }
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
  $("#narrativeToggle").addEventListener("change", (event) => {
    state.narrativeEnabled = event.target.checked;
    if (state.mode !== "scenes" && state.narrativeEnabled) toast("Narrative overlays appear on the deterministic Scenes view");
    renderMap();
  });
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
  $("#sceneMapButton").addEventListener("click", () => switchMode("scenes")); $("#aiMapButton").addEventListener("click", () => switchMode("ai")); $("#inspectionMapButton").addEventListener("click", () => switchMode("inspection")); $("#canonicalMapButton").addEventListener("click", () => switchMode("canonical")); $("#technicalMapButton").addEventListener("click", () => switchMode("technical"));
  $("#previousPage").addEventListener("click", previousRoutePage); $("#nextPage").addEventListener("click", nextRoutePage);
  $("#solveRoute").addEventListener("click", runRouteSolve); $("#retryRoute").addEventListener("click", runRouteSolve); $("#cancelRoute").addEventListener("click", cancelRouteSolve); $("#exportRouteJson").addEventListener("click", exportRouteJson);
  $("#openRouteEvidence").addEventListener("click", () => {
    const candidate = state.route.result?.recommended;
    const target = candidate?.selected_occurrence_id || state.route.activeSourceId || state.route.destination?.target_id || routeArray(candidate?.scene_ids).at(-1);
    if (target) openDetail(target);
  });
  $("#zoomIn").addEventListener("click", () => { $("#zoomValue").textContent = `${Math.round(graph.zoomBy(.1) * 100)}%`; }); $("#zoomOut").addEventListener("click", () => { $("#zoomValue").textContent = `${Math.round(graph.zoomBy(-.1) * 100)}%`; }); $("#fitMap").addEventListener("click", () => { graph.fit(); $("#zoomValue").textContent = `${Math.round(graph.scale * 100)}%`; });
  $("#backToRouteMap").addEventListener("click", () => { showLevel("route_map"); graph.world.querySelector(`[data-element-id="${CSS.escape(state.selectedId || "")}"]`)?.focus(); }); $("#detailView").addEventListener("keydown", (event) => { if (event.key === "Escape") $("#backToRouteMap").click(); });
  $("#canonicalEscapeButton").addEventListener("click", openCanonicalRecord);
  $("#selectVisibleNodes").addEventListener("click", async () => { try { await selectVisibleForAI(); toast("Exact provider-free preview ready"); } catch (error) { toast(error.message); } });
  $("#organizeButton").addEventListener("click", prepareOrganization); $("#resumeOrganization").addEventListener("click", async () => { state.prepared = null; await prepareOrganization(); });
  $("#confirmOrganization").addEventListener("click", async (event) => { event.preventDefault(); $("#consentDialog").close(); await startOrganization(); });
  $("#cancelOrganization").addEventListener("click", async () => { state.organization = await api.cancelOrganization(); renderOrganization(); toast("Run cancelling; validated scopes are preserved"); });
  $("#reviewPartial").addEventListener("click", showReview); $("#closeReview").addEventListener("click", () => $("#reviewDialog").close());
  $("#discardAssembly").addEventListener("click", async () => { if (!state.assemblyId) { toast("Candidate assembly is unavailable"); return; } try { await api.discardAssembly(state.assemblyId); state.organization = await api.organization(); renderOrganization(); $("#reviewDialog").close(); toast("Candidate discarded from the project"); } catch (error) { toast(error.message); } });
  $("#applyAssembly").addEventListener("click", async () => { state.organization = await api.applyAssembly(state.assemblyId); $("#reviewDialog").close(); await resetRoutePaging(); renderOrganization(); toast("Candidate applied; AI Story Map is ready to review"); });
  $("#diagnosticsButton").addEventListener("click", showDiagnostics); $("#closeDiagnostics").addEventListener("click", () => $("#diagnosticsDialog").close());
  $("#settingsButton").addEventListener("click", () => { const choices = ["system", "light", "dark"]; state.settings.theme = choices[(choices.indexOf(state.settings.theme) + 1) % choices.length]; document.documentElement.dataset.theme = state.settings.theme; graph.draw(); api.saveSettings(state.settings).catch(() => {}); });
  $("#quitButton").addEventListener("click", async () => { await api.shutdown(); document.body.replaceChildren(element("main", "shutdown-message", "Story Mapper has closed. You can close this tab.")); });
  document.addEventListener("keydown", (event) => { if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) { event.preventDefault(); $("#searchInput").focus(); } });
}

async function start() {
  bind();
  try { const bootstrap = await api.bootstrap(); api.configureM12(bootstrap.routes?.m12); state.settings = { ...state.settings, ...(bootstrap.settings || {}) }; document.documentElement.dataset.theme = state.settings.theme; $("#technicalToggle").checked = state.settings.include_technical; $("#unresolvedToggle").checked = state.settings.include_unresolved; renderRecent(bootstrap.recent_projects || []); renderRoutePanel(); showPrimary("welcome"); } catch (error) { renderRecent([]); renderRoutePanel(); toast(error.message); }
}

start();
export { api, graph, state, element, normalizedPage, loadOrganization };
