import { LocalApi } from "./api.js";
import { STORY_WORKFLOW_CONTRACT } from "./contract.js";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const api = new LocalApi();
const STORY_WORKFLOW_STORAGE_KEY = "rsm.story-map-v2.workflow.v2";
const STORY_TIMELINE_MIN_GROUPS = 12;
const STORY_TIMELINE_MAX_GROUPS = 30;
const STORY_STACK_THRESHOLD = 4;

const state = {
  project: null,
  analysisStatus: null,
  detail: null,
  storyPage: null, storyItems: new Map(), storyRoutes: new Map(), storyRouteSelectionId: null, storyRouteInteractionUntil: 0, storySelectionId: null, storySelectionItem: null, storySelectionControl: null, storySelectionScrollY: 0, storySelectionWindowY: 0, storySelectionViewportTop: 0, storyPath: null, storyPathToken: 0, storyDetailToken: 0, storyDetailDomIndex: 0,
  storyReader: {
    contract: null, manifest: null, status: null, mapRevision: null, generationId: null,
    currentSectionId: null, currentPage: null, sectionCache: new Map(), branchCache: new Map(),
    requestToken: 0, locateToken: 0, searchToken: 0, statusToken: 0, viewToken: 0, saveTimer: null,
    hideNew: false, restored: false, prefetchedSectionId: null,
  },
  storyWorkflow: { response: null, pollToken: 0, busy: false },
  storyNav: { chapters: [], eventNodes: [], readingNodes: [], activeChapterId: null, frame: 0, query: "" },
  settings: { theme: "system", include_technical: true, include_unresolved: true },
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
}



function toast(message) {
  const host = $("#toast"); host.textContent = message; host.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { host.hidden = true; }, 2800);
}


function showPrimary(name) {
  invalidateStoryDetail();
  $("#welcomeView").hidden = name !== "welcome";
  $("#progressView").hidden = name !== "progress";
  $("#workspaceView").hidden = name !== "workspace";
  $("#storyPrepareAction").hidden = name !== "workspace";
  $("#projectIdentity").hidden = name === "welcome";
  $("#refreshProject").hidden = name !== "workspace";
}

function setStoryWorkflowChrome({ prepare = false, progress = false, cancel = false, resume = false, retry = false } = {}) {
  const prepareAction = $("#storyPrepareAction");
  prepareAction.hidden = !prepare;
  prepareAction.disabled = !prepare || !api.storyWorkflowRoutes || state.storyWorkflow.busy;
  $("#storyRunBar").hidden = !progress;
  $("#storyCancelRun").hidden = !progress || !cancel;
  $("#storyResumeRun").hidden = !progress || !resume;
  $("#storyRetryRun").hidden = !progress || !retry;
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
    const opened = new Date(project.last_opened || "");
    const lastOpened = Number.isNaN(opened.valueOf())
      ? "Opened time unavailable"
      : `Opened ${opened.toLocaleString([], { dateStyle: "medium", timeStyle: "medium" })}`;
    button.append(
      element("span", "recent-type", project.source_type || "Project"),
      element("strong", "", project.name || "Saved project"),
      element("span", "recent-meta", `Source · ${project.source_basename || "Unavailable"}`),
      element("span", "recent-meta", lastOpened),
    );
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
    state.storyWorkflow.pollToken += 1; state.storyWorkflow.response = null; state.storyWorkflow.busy = false;
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


function showStorySurface(visible) {
  if (!visible) invalidateStoryDetail();
  const prepare = $("#storyPrepareAction");
  // With no readable story yet, the first generation has to stay reachable from the masthead.
  if (visible) {
    $(".story-hero-meta").append(prepare);
    setStoryWorkflowChrome();
  }
  else if (api.storyWorkflowRoutes) {
    $(".masthead-actions").insertBefore(prepare, $("#refreshProject"));
    prepare.textContent = "Generate";
    setStoryWorkflowChrome({ prepare: true });
  }
  $("#storyBrowser").hidden = !visible;
  $("#storyUnavailablePanel").hidden = visible;
}

function showStoryUnavailable(reason) {
  showStorySurface(false);
  if (reason) $("#storyUnavailableReason").textContent = reason;
}

function storyItemTitle(item) {
  return item.title || item.caption || "Story moment";
}

function storyOutlineSummary(item) {
  if (item.outline_summary) return item.outline_summary;
  const value = String(item.summary || item.outcome_summary || item.text || "").replace(/\s+/gu, " ").trim();
  if (value.length <= 180) return value;
  const firstSentence = value.match(/^.{1,180}?[.!?](?=\s|$)/u)?.[0];
  if (firstSentence) return firstSentence;
  const compact = value.slice(0, 180).replace(/\s+\S*$/u, "").trim();
  return `${compact || value.slice(0, 180)}…`;
}

function storyDetailSummary(item) {
  return item.detail_summary || item.summary || item.outcome_summary || item.text || storyOutlineSummary(item);
}

function progressiveStoryActive() {
  return $("#storyBrowser").classList.contains("is-progressive-story");
}

const STORY_CHOICE_KINDS = new Map([
  ["decision", "decision"],
  ["condition", "condition"],
]);

const STORY_OUTCOME_KINDS = new Map([
  ["continues", "continuation"],
  ["rejoins", "rejoin"],
  ["ends", "ending"],
  ["unresolved", "unresolved"],
]);

function storySemanticKind(value, kinds) {
  if (typeof value !== "string") return "neutral";
  return kinds.get(value.trim().toLocaleLowerCase()) || "neutral";
}

function storyControlPresentation(kind, armCount) {
  const ways = armCount ? ` · ${armCount} ways` : "";
  if (kind === "decision") return { label: `The player decides${ways}`, icon: "◆" };
  if (kind === "condition") return { label: `The game checks${ways}`, icon: "◈" };
  return { label: `The story branches${ways}`, icon: "•" };
}

function storyArmPresentation(controlKind) {
  if (controlKind === "condition") return "Condition path";
  if (controlKind === "decision") return "Player picks";
  return "Story path";
}

function storyOutcomePresentation(outcomeKind) {
  if (outcomeKind === "rejoin") return { label: "Rejoins", icon: "⤳" };
  if (outcomeKind === "ending") return { label: "Ends here", icon: "■" };
  if (outcomeKind === "unresolved") return { label: "Unresolved", icon: "?" };
  if (outcomeKind === "continuation") return { label: "Continues", icon: "→" };
  return null;
}

function storySemanticLegend() {
  const legend = element("div", "story-tree-key"); legend.setAttribute("aria-label", "Story colour key");
  for (const [kind, label] of [["decision", "Player decides"], ["condition", "Game checks"], ["continuation", "Continues"], ["rejoin", "Paths rejoin"], ["ending", "Ending"]]) {
    const item = element("span", "story-tree-key-item", label); item.dataset.storyKind = kind; legend.append(item);
  }
  return legend;
}

function storyBadge(text, kind) {
  return element("span", `story-badge ${kind}`, text);
}

function humanStoryTarget(value) {
  if (typeof value !== "string" || !value.startsWith("story:")) return null;
  const label = value.slice("story:".length).trim();
  return label || null;
}

function storyOutcomeSentence(item) {
  const destination = humanStoryTarget(item.destination_id) || humanStoryTarget(item.binding?.target_id);
  const boundary = humanStoryTarget(item.rejoin_node_id) || humanStoryTarget(item.rejoin_binding?.target_id);
  const outcomeKind = storySemanticKind(item.outcome_kind, STORY_OUTCOME_KINDS);
  if (boundary) {
    const kind = outcomeKind === "ending" ? "ending" : outcomeKind === "unresolved" ? "unresolved" : "rejoin";
    const prefix = kind === "ending" ? "Ends at" : kind === "unresolved" ? "Unresolved at" : "Rejoins at";
    return { kind, text: `${prefix} ${boundary}`, name: boundary };
  }
  if (destination) return { kind: "destination", text: `Goes to ${destination}`, name: destination };
  return null;
}

function storyRouteRootCode(index) {
  let value = index + 1;
  let code = "";
  while (value > 0) {
    value -= 1;
    code = String.fromCharCode(65 + (value % 26)) + code;
    value = Math.floor(value / 26);
  }
  return code;
}

function storyRouteTarget(item) {
  if (item.entry_kind) {
    const loop = item.entry_kind === "loop";
    return {
      kind: loop ? "loop" : "unresolved",
      text: loop ? `Returns to ${item.title}` : `Ownership unresolved; see ${item.title}`,
      name: item.title,
      selectionId: item.target_selection_id || null,
    };
  }
  const outcome = storyOutcomeSentence(item);
  if (outcome) {
    const selectionId = outcome.kind === "destination"
      ? item.destination_target_selection_id
      : item.rejoin_target_selection_id;
    return { ...outcome, selectionId: selectionId || null };
  }
  const outcomeKind = storySemanticKind(item.outcome_kind, STORY_OUTCOME_KINDS);
  if (outcomeKind === "ending") return { kind: "ending", text: "Ends here", name: null, selectionId: null };
  if (outcomeKind === "unresolved") return { kind: "unresolved", text: "Destination unresolved", name: null, selectionId: null };
  if (outcomeKind === "rejoin") return { kind: "rejoin", text: "Returns to the shared story", name: null, selectionId: null };
  if (outcomeKind === "continuation") return { kind: "continuation", text: "Continues on this route", name: null, selectionId: null };
  return null;
}

function storyRouteSynopsis(arm) {
  const own = storySummaryWithoutOutcome(arm);
  if (own && !/^(?:Rejoins at|Goes to|Ends here|Destination unresolved)\b/iu.test(own)) return own;
  const firstOwnedEvent = (arm.route_flow || []).find((item) => item.kind === "event")?.event;
  if (firstOwnedEvent) return storyOutlineSummary(firstOwnedEvent);
  const target = storyRouteTarget(arm);
  if (target?.kind === "rejoin") return "This path returns directly to the shared story.";
  if (target?.kind === "ending") return "This path reaches an ending.";
  if (target?.kind === "unresolved") return "The destination of this path is unresolved.";
  return "The story continues on this route.";
}

function createStoryRouteContext(arm, armIndex, parent, forkTitle, controlKind) {
  const code = parent ? `${parent.code}.${armIndex + 1}` : storyRouteRootCode(armIndex);
  const context = {
    selectionId: arm.selection_id,
    code,
    parentSelectionId: parent?.selectionId || null,
    parentCode: parent?.code || null,
    forkTitle,
    caption: storyItemTitle(arm),
    synopsis: storyRouteSynopsis(arm),
    controlKind,
    outcomeKind: storySemanticKind(arm.outcome_kind, STORY_OUTCOME_KINDS),
    depth: parent ? parent.depth + 1 : 0,
    paletteSlot: parent ? ((parent.paletteSlot + armIndex) % 8) + 1 : (armIndex % 8) + 1,
    target: storyRouteTarget(arm),
    provenance: arm.state_provenance || [],
  };
  state.storyRoutes.set(context.selectionId, context);
  return context;
}

function applyStoryRouteContext(node, context, { reading = false } = {}) {
  if (context) {
    node.dataset.storyRouteSelectionId = context.selectionId;
    node.dataset.storyRouteCode = context.code;
    node.dataset.storyRouteSlot = String(context.paletteSlot);
    node.style.setProperty("--story-route-color", `var(--story-route-${context.paletteSlot})`);
    node.style.setProperty("--story-route-soft", `var(--story-route-${context.paletteSlot}-soft)`);
  } else {
    node.dataset.storyStream = "main";
  }
  if (reading) node.dataset.storyReadingNode = "true";
  return node;
}

function storyRouteContextForNode(node) {
  const owner = node?.closest?.("[data-story-route-selection-id],[data-story-stream='main']");
  if (!owner || owner.dataset.storyStream === "main") return null;
  return state.storyRoutes.get(owner.dataset.storyRouteSelectionId) || null;
}

function storyRouteOwnerLabel(kind) {
  if (kind === "decision") return "Player choice";
  if (kind === "condition") return "Game condition";
  return "Story branch";
}

function renderStoryRoutePanelProvenance(context) {
  const group = $("#storyRouteProvenanceGroup");
  const host = $("#storyRouteProvenance");
  host.replaceChildren();
  const seen = new Set();
  const facts = (context?.provenance || []).filter((fact) => {
    if (fact.relationship_strength === "unresolved" || !fact.target_selection_id || seen.has(fact.target_selection_id)) return false;
    seen.add(fact.target_selection_id);
    return true;
  }).slice(0, 3);
  for (const fact of facts) {
    const link = element("button", "quiet-button story-route-provenance-link", fact.target_title);
    link.type = "button";
    link.addEventListener("click", () => navigateProgressiveStorySelection(fact.target_selection_id));
    host.append(link);
  }
  group.hidden = !facts.length;
}

function updateStoryRoutePanel(context, item = null) {
  const panel = $("#storyRoutePanel");
  if (!progressiveStoryActive()) { panel.hidden = true; return; }
  panel.hidden = false;
  state.storyRouteSelectionId = context?.selectionId || null;
  panel.dataset.storyRouteMode = context ? "route" : "main";
  panel.toggleAttribute("data-story-route-selection-id", Boolean(context));
  if (context) {
    panel.dataset.storyRouteSelectionId = context.selectionId;
    panel.dataset.storyRouteCode = context.code;
    panel.dataset.storyRouteSlot = String(context.paletteSlot);
    panel.style.setProperty("--story-route-color", `var(--story-route-${context.paletteSlot})`);
    panel.style.setProperty("--story-route-soft", `var(--story-route-${context.paletteSlot}-soft)`);
  } else {
    delete panel.dataset.storyRouteSelectionId;
    delete panel.dataset.storyRouteCode;
    delete panel.dataset.storyRouteSlot;
    panel.style.removeProperty("--story-route-color");
    panel.style.removeProperty("--story-route-soft");
  }
  $("#storyRouteCode").textContent = context ? `Route ${context.code}` : "Main story";
  $("#storyRouteTitle").textContent = context ? context.caption : storyItemTitle(item || { title: "Shared story" });
  $("#storyRouteSynopsis").textContent = context
    ? context.synopsis || "This path continues from the selected fork."
    : storySummaryWithoutOutcome(item || {}) || "The routes are together on the shared chronology.";
  $("#storyRouteOrigin").textContent = context ? context.forkTitle : "Shared chronology";
  $("#storyRouteOwner").textContent = context ? storyRouteOwnerLabel(context.controlKind) : "Story";
  const status = $("#storyRouteStatus"); status.replaceChildren();
  const statusLabel = $("#storyRouteStatusLabel");
  const statusLabels = { rejoin: "Returns to shared story", destination: "Continues at", ending: "Route ending", unresolved: "Unresolved route", loop: "Returns earlier", continuation: "Route continues" };
  const target = context ? context.target : null;
  statusLabel.textContent = context ? (target && statusLabels[target.kind]) || "Route outcome" : "Shared story";
  if (target) {
    if (target.selectionId) {
      const link = element("button", "quiet-button story-route-target-link", target.text);
      link.type = "button";
      link.addEventListener("click", () => navigateProgressiveStorySelection(target.selectionId));
      status.append(link);
    } else status.textContent = target.text;
  } else status.textContent = context ? "Continues on this route" : "Routes are together";
  renderStoryRoutePanelProvenance(context);
}

function syncStoryRoutePanelForNode(node, item = null, { hold = false } = {}) {
  if (!progressiveStoryActive()) return;
  if (hold) state.storyRouteInteractionUntil = Date.now() + 600;
  const context = storyRouteContextForNode(node);
  const reference = node?.closest?.(".story-route-reference");
  const panelContext = context && reference?.storyRouteTarget ? { ...context, target: reference.storyRouteTarget } : context;
  const selectionId = node?.closest?.("[data-story-selection-id]")?.dataset.storySelectionId;
  const panel = $("#storyRoutePanel");
  const routeKey = panelContext?.selectionId || "main";
  const itemKey = selectionId || item?.selection_id || item?.title || reference?.storyRouteTarget?.text || "story";
  if (panel.dataset.storyReadingRoute === routeKey && panel.dataset.storyReadingItem === itemKey) return;
  panel.dataset.storyReadingRoute = routeKey;
  panel.dataset.storyReadingItem = itemKey;
  updateStoryRoutePanel(panelContext, item || state.storyItems.get(selectionId) || null);
}

function appendStoryTargets(host, item, { suppressRejoin = false } = {}) {
  const outcome = storyOutcomeSentence(item);
  if (!outcome) return;
  if (suppressRejoin && outcome.kind === "rejoin") return;
  const targets = element("div", "story-targets");
  const presentation = storyOutcomePresentation(outcome.kind === "destination" ? "continuation" : outcome.kind);
  const target = element("p", `story-target ${outcome.kind}`);
  if (presentation) {
    const icon = element("span", "story-target-icon", presentation.icon);
    icon.setAttribute("aria-hidden", "true");
    target.append(icon);
  }
  const selectionId = outcome.kind === "destination"
    ? item.destination_target_selection_id
    : item.rejoin_target_selection_id;
  if (selectionId) {
    const link = element("button", "quiet-button story-target-text story-navigation-link", outcome.text);
    link.type = "button";
    link.addEventListener("click", () => navigateProgressiveStorySelection(selectionId, link));
    target.append(link);
  } else target.append(element("span", "story-target-text", outcome.text));
  target.dataset.targetKind = outcome.kind;
  targets.append(target);
  host.append(targets);
}

function appendStateProvenance(host, item) {
  const facts = item.state_provenance || [];
  if (!facts.length) return;
  const rows = element("div", "story-provenance");
  const seen = new Set();
  const unique = [];
  for (const fact of facts) {
    const key = `${fact.relationship_strength}:${fact.target_selection_id || "unresolved"}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(fact);
  }
  const resolved = unique
    .filter((fact) => fact.relationship_strength !== "unresolved")
    .sort((left, right) => (left.relationship_strength === "exact" ? -1 : 1) - (right.relationship_strength === "exact" ? -1 : 1));
  for (const fact of resolved.slice(0, 3)) {
    const row = element("p", `story-provenance-row ${fact.relationship_strength}`);
    const label = fact.relationship_strength === "exact" ? "Set earlier by" : "Can be set earlier by";
    row.append(element("span", "story-provenance-label", label));
    const link = element("button", "quiet-button story-provenance-target story-navigation-link", fact.target_title);
    link.type = "button";
    link.addEventListener("click", () => navigateProgressiveStorySelection(fact.target_selection_id));
    row.append(link);
    rows.append(row);
  }
  if (resolved.length > 3) rows.append(element("p", "story-provenance-row story-provenance-more", `${resolved.length - 3} more earlier sources in Python detail`));
  if (unique.some((fact) => fact.relationship_strength === "unresolved")) {
    const unresolved = element("p", "story-provenance-row unresolved");
    unresolved.append(element("span", "story-provenance-label", "Unresolved earlier state"));
    rows.append(unresolved);
  }
  host.append(rows);
}

function appendStateProvenanceDetail(host, facts) {
  if (!facts?.length) return;
  const list = element("ul", "story-provenance-detail");
  for (const fact of facts) {
    const source = fact.source ? `${fact.source.relative_path}:${fact.source.start_line}` : "source unavailable";
    list.append(element("li", "", `${fact.variable} — ${fact.relationship_strength} — ${source}`));
  }
  host.append(list);
}

function appendStoryBadges(host, item) {
  const badges = element("div", "story-badges");
  if (item.route_id) badges.append(storyBadge(item.route_id, "route"));
  if (item.condition) badges.append(storyBadge(item.condition, "condition"));
  for (const effect of item.effects || []) badges.append(storyBadge(effect, "effect"));
  if (item.reachability && item.reachability !== "reachable") {
    const labels = { unreachable: "Unreachable", unresolved: "Unresolved" };
    const status = storyBadge(labels[item.reachability], "reachability story-reachability");
    status.dataset.reachability = item.reachability; badges.append(status);
  }
  if (badges.children.length) host.append(badges);
}

function appendStoryWarnings(host, warnings) {
  if (!warnings?.length) return;
  const details = element("details", "story-warnings");
  const noun = warnings.length === 1 ? "Python detail" : `${warnings.length} Python details`;
  details.append(element("summary", "", noun));
  const list = element("ul");
  for (const warning of warnings) list.append(element("li", "", warning));
  details.append(list); host.append(details);
}

function storySummaryWithoutOutcome(item) {
  return storyTextWithoutOutcome(storyOutlineSummary(item), item);
}

function storyTextWithoutOutcome(summary, item) {
  const outcome = storyOutcomeSentence(item);
  if (!summary || !outcome) return summary;
  const trimmed = summary.replace(/\s+/gu, " ").trim();
  const spoken = `${outcome.text}.`;
  if (trimmed === spoken || trimmed === outcome.text) return "";
  if (trimmed.endsWith(spoken)) return trimmed.slice(0, -spoken.length).trim();
  return trimmed;
}

const STORY_EXPRESSION_PREFIXES = ["Requires: ", "Check whether ", "Routes: Check whether "];

/** Typeset a Python expression carried in a title so the prose and the code read apart. */
function storyTitleNode(title) {
  const strong = element("strong", "");
  const prefix = STORY_EXPRESSION_PREFIXES.find((candidate) => title.startsWith(candidate));
  if (!prefix) { strong.textContent = title; return strong; }
  const expression = title.slice(prefix.length).trim();
  if (!expression) { strong.textContent = title; return strong; }
  strong.append(element("span", "story-title-lead", prefix.replace(/:\s$/u, "").trim()), element("code", "story-title-expression", expression));
  return strong;
}

function storySelectionControl(item, kind, routeContext = null) {
  const control = element("button", `${kind}-select`); control.type = "button";
  control.dataset.storySelectionId = item.selection_id;
  const title = storyItemTitle(item); const summary = storySummaryWithoutOutcome(item);
  control.append(storyTitleNode(title));
  if (summary && summary.trim() !== title.trim()) control.append(element("span", "", summary));
  if (routeContext) {
    control.setAttribute("aria-label", `Route ${routeContext.code}. ${title}. Started by ${storyRouteOwnerLabel(routeContext.controlKind).toLocaleLowerCase()}`);
  }
  control.addEventListener("focus", () => syncStoryRoutePanelForNode(control, item, { hold: true }));
  control.addEventListener("click", () => {
    if (!progressiveStoryActive()) { selectStoryItem(item, control); return; }
    activateStoryItem(item, control); closeStoryPathForOutline();
    if (kind === "story-arm") focusStoryDescendantRoute(item.selection_id);
    else toggleStorySelectionDetail(control);
  });
  return control;
}

function toggleStorySelectionDetail(control) {
  toggleProgressiveStoryDetail(control);
}

function storyDetailControl(item, control) {
  const button = element("button", "story-detail-button", "Detail / Evidence"); button.type = "button";
  button.addEventListener("click", async () => {
    if (state.storySelectionId !== item.selection_id || state.storySelectionControl !== control) activateStoryItem(item, control);
    await openStoryDetail(item.selection_id);
  });
  return button;
}

function closeStoryPathForOutline() {
  state.storyPathToken += 1; clearStoryPathWitness(); $("#storyPathPanel").hidden = true;
}

function renderStoryProse(host, text, title) {
  const blocks = String(text || "").split(/\n{2,}/u).map((block) => block.trim()).filter(Boolean);
  const heading = String(title || "").trim();
  let first = true;
  for (const block of blocks) {
    const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
    let body = lines.join(" ");
    let beat = null;
    if (first && lines.length > 1 && lines[0] === heading) { body = lines.slice(1).join(" "); }
    else if (first && lines.length > 1) { beat = lines[0]; body = lines.slice(1).join(" "); }
    else if (!first) {
      const split = block.match(/^(.{3,90}?)\s+—\s+([\s\S]+)$/u);
      if (split) { beat = split[1].trim(); body = split[2].replace(/\s+/gu, " ").trim(); }
    }
    if (beat) host.append(element("h4", "story-prose-beat", beat));
    if (body) host.append(element("p", "story-prose", body));
    first = false;
  }
}

function preserveStoryControlPosition(control, update) {
  const browser = $("#storyBrowser");
  const before = control.getBoundingClientRect().top;
  update();
  const delta = control.getBoundingClientRect().top - before;
  if (Math.abs(delta) < 0.5) return;
  if (browser.contains(control) && browser.scrollHeight > browser.clientHeight + 1) browser.scrollTop += delta;
  else window.scrollBy(0, delta);
}

function toggleProgressiveStoryDetail(control) {
  const detail = document.getElementById(control.getAttribute("aria-controls") || "");
  if (!detail) return;
  const expand = detail.hidden;
  const slot = detail.closest(".story-route-detail-slot");
  preserveStoryControlPosition(control, () => {
    if (slot) {
      for (const candidate of slot.querySelectorAll(":scope > .story-inline-detail")) candidate.hidden = true;
      for (const candidate of slot.closest(".story-choice").querySelectorAll("button[aria-controls]")) {
        const owned = document.getElementById(candidate.getAttribute("aria-controls") || "");
        if (owned?.parentElement === slot) candidate.setAttribute("aria-expanded", "false");
      }
    }
    detail.hidden = !expand;
    control.setAttribute("aria-expanded", String(expand));
    if (slot) slot.hidden = !expand;
  });
}

function appendProgressiveStoryDetail(host, item, control, { suppressOutcome = false } = {}) {
  const detail = element("div", "story-inline-detail"); detail.hidden = true;
  detail.id = `story-inline-detail-${++state.storyDetailDomIndex}`;
  detail.dataset.ownerSelectionId = item.selection_id;
  const title = storyItemTitle(item);
  const prose = suppressOutcome ? storyTextWithoutOutcome(storyDetailSummary(item), item) : storyDetailSummary(item);
  // A merge row carries no prose of its own; echoing its own title back reads as a duplicate.
  if (prose && prose.replace(/\s+/gu, " ").trim() !== title.replace(/\s+/gu, " ").trim()) {
    const host = element("div", "story-inline-summary");
    renderStoryProse(host, prose, title);
    if (host.children.length) detail.append(host);
  }
  const technical = element("details", "story-technical-disclosure");
  technical.append(element("summary", "", "Python detail"));
  const body = element("div", "story-technical-body");
  appendStoryBadges(body, item); appendStoryWarnings(body, item.warnings || item.unresolved_warnings);
  appendStateProvenanceDetail(body, item.state_provenance);
  if (item.selection_id) {
    const source = element("button", "quiet-button story-detail-button", "Source / Evidence"); source.type = "button";
    source.addEventListener("click", async () => { if (state.storySelectionId !== item.selection_id || state.storySelectionControl !== control) activateStoryItem(item, control); await openStoryDetail(item.selection_id); });
    body.append(source);
  }
  technical.append(body); detail.append(technical); host.append(detail);
  return detail;
}

function bindProgressiveStoryDetail(control, detail) {
  control.setAttribute("aria-controls", detail.id);
  control.setAttribute("aria-expanded", "false");
}

function storyProgressiveDetailTrigger(item, primaryControl, detail) {
  const trigger = element("button", "quiet-button story-inline-detail-trigger", "⋯");
  trigger.type = "button";
  trigger.setAttribute("aria-label", `Show story and Python detail for ${storyItemTitle(item)}`);
  trigger.setAttribute("aria-controls", detail.id);
  trigger.setAttribute("aria-expanded", "false");
  trigger.addEventListener("click", (event) => {
    event.stopPropagation();
    if (state.storySelectionId !== item.selection_id || state.storySelectionControl !== primaryControl) activateStoryItem(item, primaryControl);
    toggleProgressiveStoryDetail(trigger);
  });
  return trigger;
}

function planStoryContinuations(rootChoice) {
  const occurrences = new Map();
  function visit(choice, choicePath) {
    for (const arm of choice.arms) {
      const armPath = [...choicePath, `arm:${arm.selection_id}`];
      if (arm.rejoin_binding) {
        const value = occurrences.get(arm.rejoin_binding.selection_id) || { binding: arm.rejoin_binding, paths: [] };
        value.paths.push(armPath); occurrences.set(arm.rejoin_binding.selection_id, value);
      }
      (arm.nested_choices || []).forEach((child, index) => visit(child, [...armPath, `choice:${child.key}:${index}`]));
    }
  }
  visit(rootChoice, []);
  const owners = new Map();
  for (const value of occurrences.values()) {
    const first = value.paths[0] || []; let length = first.length;
    for (const path of value.paths.slice(1)) {
      let index = 0; while (index < length && index < path.length && first[index] === path[index]) index += 1;
      length = index;
    }
    const key = JSON.stringify(first.slice(0, length)); const values = owners.get(key) || [];
    values.push(value.binding); owners.set(key, values);
  }
  return owners;
}

function appendStoryContinuations(host, bindings, armOwned = false, seen = null, returnRouteContext = null) {
  for (const binding of bindings || []) {
    const named = humanStoryTarget(binding.target_id);
    // Several arms can prove the same merge; the reader only needs to be told once per event.
    const key = binding.selection_id || named || (armOwned ? "this path rejoins" : "the paths meet again");
    if (seen) {
      if (seen.has(key)) continue;
      seen.add(key);
    }
    const continuation = {
      selection_id: binding.selection_id,
      title: armOwned ? "This route returns to the story" : "The story comes back together",
      summary: named ? `Continue with ${named}` : "",
      binding,
    };
    state.storyItems.set(continuation.selection_id, continuation);
    const row = element("div", `story-continuation${armOwned ? " is-route-return" : " is-confluence"}`);
    row.dataset.outcomeKind = "rejoin";
    row.dataset.storySelectionId = continuation.selection_id;
    if (binding.selection_id) row.dataset.storyConfluenceTargetSelectionId = binding.selection_id;
    row.dataset.storyConfluenceScope = returnRouteContext ? "route" : "main";
    applyStoryRouteContext(row, returnRouteContext, { reading: true });
    const mark = element("span", "story-continuation-mark", "⤳");
    mark.setAttribute("aria-hidden", "true");
    row.append(mark);
    const control = storySelectionControl(continuation, "story-continuation", returnRouteContext);
    row.append(control);
    if (progressiveStoryActive()) {
      const detail = appendProgressiveStoryDetail(row, continuation, control);
      bindProgressiveStoryDetail(control, detail);
      applyStoryRouteContext(detail, returnRouteContext, { reading: true });
    }
    else row.append(storyDetailControl(continuation, control));
    host.append(row);
  }
}

function storyNormalizedText(value) {
  return String(value || "").replace(/\s+/gu, " ").replace(/[.\s]+$/u, "").trim().toLocaleLowerCase();
}

function storyPromptRepeatsArms(prompt, arms) {
  const normalized = storyNormalizedText(prompt);
  if (!normalized) return true;
  const captions = (arms || []).map((arm) => storyNormalizedText(storyItemTitle(arm))).filter(Boolean);
  if (captions.length < 2) return false;
  if (captions.every((caption) => normalized.includes(caption))) return true;
  return normalized === storyNormalizedText(captions.join(" / "));
}

function countStoryForks(choices) {
  let total = 0;
  for (const choice of choices || []) {
    total += 1;
    for (const arm of choice.arms || []) total += countStoryForks(arm.nested_choices);
  }
  return total;
}

function focusStoryDescendantRoute(selectionId) {
  const control = $(`button.story-arm-select[data-story-selection-id="${CSS.escape(selectionId)}"]`);
  const host = control?.closest(".story-choice")?.querySelector(":scope > .story-descendants");
  if (!host) return;
  for (const route of $$(".story-descendant-route")) {
    if (route.parentElement !== host) continue;
    route.open = route.dataset.ownerSelectionId === selectionId;
  }
}

function revealProgressiveStoryNode(node) {
  if (!node) return false;
  for (let ancestor = node.parentElement?.closest("details"); ancestor; ancestor = ancestor.parentElement?.closest("details")) ancestor.open = true;
  for (let ancestor = node.parentElement?.closest(".story-event"); ancestor; ancestor = ancestor.parentElement?.closest(".story-event")) ancestor.hidden = false;
  return true;
}

function focusProgressiveStorySelection(selectionId, { clearSearch = true, highlight = true } = {}) {
  if (clearSearch && state.storyNav.query) { $("#storySearchInput").value = ""; applyStorySearch(""); }
  const control = $(`button[data-story-selection-id="${CSS.escape(selectionId)}"]`);
  if (!control || !revealProgressiveStoryNode(control)) return false;
  const target = control.closest(".story-event,.story-arm,.story-continuation") || control;
  scrollStoryTo(target);
  control.focus({ preventScroll: true });
  syncStoryRoutePanelForNode(control, state.storyItems.get(selectionId) || null, { hold: true });
  if (highlight) {
    const previous = $("[data-story-navigation-highlight='true']");
    if (previous) delete previous.dataset.storyNavigationHighlight;
    target.dataset.storyNavigationHighlight = "true";
    clearTimeout(state.storyNavigationHighlightTimer);
    state.storyNavigationHighlightTimer = setTimeout(() => { delete target.dataset.storyNavigationHighlight; }, 1800);
  }
  return true;
}

function navigateProgressiveStorySelection(selectionId) {
  return focusProgressiveStorySelection(selectionId);
}

function renderStoryRouteFlow(items, ordinalState, routeContext) {
  const host = element("div", "story-route-flow");
  applyStoryRouteContext(host, routeContext);
  const events = element("ol", "story-events story-route-events");
  for (const item of items || []) {
    if (item.kind === "event") events.append(renderStoryEvent(item.event, ordinalState, routeContext));
    else {
      const reference = element("div", "story-route-reference");
      reference.dataset.entryKind = item.entry_kind;
      reference.storyRouteTarget = storyRouteTarget(item);
      applyStoryRouteContext(reference, routeContext, { reading: true });
      const label = item.entry_kind === "loop" ? "Returns to" : "Ownership unresolved; see";
      reference.append(element("span", "story-route-reference-kind", label));
      const target = element("button", "quiet-button story-route-reference-target", item.title); target.type = "button";
      target.addEventListener("focus", () => syncStoryRoutePanelForNode(reference, { title: item.title }, { hold: true }));
      target.addEventListener("click", () => navigateProgressiveStorySelection(item.target_selection_id, target));
      reference.append(target); host.append(reference);
    }
  }
  if (events.children.length) host.prepend(events);
  return host;
}

function renderStoryChoice(choice, nested = false, continuationPlan = null, choicePath = [], seen = null, ordinalState = { value: 0 }, parentRouteContext = null, ownerTitle = "") {
  const plan = continuationPlan || planStoryContinuations(choice);
  const merges = seen || new Set();
  const article = element("section", `story-choice${nested ? " nested" : ""}`);
  applyStoryRouteContext(article, parentRouteContext);
  const controlKind = storySemanticKind(choice.control_kind, STORY_CHOICE_KINDS);
  article.dataset.choiceKind = controlKind;
  const prompt = humanStoryTarget(choice.key) || (nested ? "Choice within this path" : "Choice");
  const forkTitle = humanStoryTarget(choice.key) || ownerTitle || (nested ? "Choice within this path" : "Story choice");
  const choiceControl = element("div", "story-choice-control");
  const presentation = storyControlPresentation(controlKind, choice.arms.length);
  const icon = element("span", "story-control-icon", presentation.icon); icon.setAttribute("aria-hidden", "true");
  const copy = element("div", "story-choice-copy");
  copy.append(element("span", "story-control-type", presentation.label));
  // The prompt is often just the arm captions joined; the arms below already say that.
  if (!storyPromptRepeatsArms(prompt, choice.arms)) {
    const promptCopy = element("p", "story-choice-label");
    promptCopy.append(...storyTitleNode(prompt).childNodes);
    copy.append(promptCopy);
  }
  choiceControl.append(icon, copy);
  article.append(choiceControl);
  const stacked = choice.arms.length > STORY_STACK_THRESHOLD;
  article.dataset.forkLayout = stacked ? "stack" : "fan";
  const arms = element("div", `story-arms${stacked ? " is-stacked" : ""}`);
  arms.dataset.armCount = String(choice.arms.length);
  arms.style.setProperty("--story-arm-count", String(choice.arms.length));
  const detailSlot = element("div", "story-route-detail-slot"); detailSlot.hidden = true;
  const descendants = element("div", "story-descendants");
  choice.arms.forEach((arm, armIndex) => {
    const armPath = [...choicePath, `arm:${arm.selection_id}`];
    state.storyItems.set(arm.selection_id, arm);
    const routeContext = createStoryRouteContext(arm, armIndex, parentRouteContext, forkTitle, controlKind);
    const armArticle = element("article", "story-arm"); armArticle.dataset.storySelectionId = arm.selection_id;
    applyStoryRouteContext(armArticle, routeContext);
    const outcomeKind = storySemanticKind(arm.outcome_kind, STORY_OUTCOME_KINDS);
    armArticle.dataset.outcomeKind = outcomeKind;
    armArticle.dataset.controlKind = controlKind;
    armArticle.dataset.armIndex = String(armIndex);
    const hasRouteFlow = Boolean(arm.route_flow?.length);
    armArticle.dataset.hasDescendants = String(Boolean(arm.nested_choices?.length || hasRouteFlow));
    const head = element("div", "story-arm-head");
    const control = storySelectionControl(arm, "story-arm", routeContext);
    control.prepend(element("span", "story-route-code", `Route ${routeContext.code}`));
    control.prepend(element("span", "story-arm-kind", storyArmPresentation(controlKind)));
    head.append(control);
    if (!progressiveStoryActive()) head.append(storyDetailControl(arm, control));
    armArticle.append(head); appendStoryTargets(armArticle, arm, { suppressRejoin: Boolean(arm.rejoin_binding) }); appendStateProvenance(armArticle, arm);
    if (progressiveStoryActive()) {
      const detail = appendProgressiveStoryDetail(detailSlot, arm, control, { suppressOutcome: Boolean(arm.rejoin_binding) });
      applyStoryRouteContext(detail, routeContext, { reading: true });
      head.append(storyProgressiveDetailTrigger(arm, control, detail));
    }
    else { appendStoryBadges(armArticle, arm); appendStoryWarnings(armArticle, arm.warnings); }
    const armContinuations = plan.get(JSON.stringify(armPath));
    if (!arm.nested_choices?.length && !hasRouteFlow) appendStoryContinuations(armArticle, armContinuations, true, merges, parentRouteContext);
    arms.append(armArticle);
    if (arm.nested_choices?.length || hasRouteFlow) {
      const route = element("details", "story-descendant-route");
      route.dataset.ownerSelectionId = arm.selection_id;
      route.dataset.ownerOutcomeKind = outcomeKind;
      applyStoryRouteContext(route, routeContext, { reading: true });
      const ownerPosition = ((armIndex + 0.5) / choice.arms.length) * 100;
      route.style.setProperty("--story-owner-x", `${ownerPosition}%`);
      route.style.setProperty("--story-owner-left", `${Math.min(ownerPosition, 50)}%`);
      route.style.setProperty("--story-owner-width", `${Math.abs(ownerPosition - 50)}%`);
      const connector = element("div", "story-owner-connector"); connector.setAttribute("aria-hidden", "true"); connector.append(element("span"));
      const forkCount = countStoryForks(arm.nested_choices);
      const routeEventCount = (arm.route_flow || []).filter((item) => item.kind === "event").length;
      const routeReferenceCount = (arm.route_flow || []).filter((item) => item.kind === "reference").length;
      // The river starts compact. Selecting an arm reveals only that arm's owned continuation.
      route.open = false;
      route.dataset.storyRouteFocus = "available";
      const owner = element("summary", "story-descendant-owner");
      owner.addEventListener("focus", () => { state.storyRouteInteractionUntil = Date.now() + 600; updateStoryRoutePanel(routeContext, arm); });
      owner.addEventListener("keydown", (event) => {
        if (!["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        route.open = !route.open;
      });
      const descendantLabel = routeEventCount
        ? `${routeEventCount} story event${routeEventCount === 1 ? "" : "s"}`
        : routeReferenceCount
          ? `${routeReferenceCount} route reference${routeReferenceCount === 1 ? "" : "s"}`
          : `${forkCount} branch point${forkCount === 1 ? "" : "s"}`;
      owner.append(
        element("span", "story-descendant-route-code", `Route ${routeContext.code}`),
        element("span", "story-descendant-owner-label", `Inside ${storyItemTitle(arm)}`),
        element("span", "story-descendant-owner-count", descendantLabel),
      );
      route.append(connector, owner);
      const sequence = element("div", "story-choice-sequence");
      applyStoryRouteContext(sequence, routeContext);
      sequence.dataset.sequenceLength = String(arm.nested_choices.length + (arm.route_flow?.length || 0));
      arm.nested_choices.forEach((child, index) => sequence.append(renderStoryChoice(child, true, plan, [...armPath, `choice:${child.key}:${index}`], merges, ordinalState, routeContext, storyItemTitle(arm))));
      if (hasRouteFlow) sequence.append(renderStoryRouteFlow(arm.route_flow, ordinalState, routeContext));
      route.append(sequence); appendStoryContinuations(route, armContinuations, true, merges, parentRouteContext); descendants.append(route);
    }
  });
  article.append(arms);
  if (detailSlot.children.length) article.append(detailSlot);
  if (descendants.children.length) { descendants.dataset.routeCount = String(descendants.children.length); article.append(descendants); }
  appendStoryContinuations(article, plan.get(JSON.stringify(choicePath)), false, merges, parentRouteContext);
  return article;
}

function renderStoryEvent(event, ordinalState = { value: 0 }, routeContext = null) {
  const ordinal = ++ordinalState.value;
  state.storyItems.set(event.selection_id, event);
  const article = element("li", "story-event"); article.dataset.storySelectionId = event.selection_id; article.dataset.storyOrdinal = String(ordinal);
  applyStoryRouteContext(article, routeContext, { reading: true });
  article.id = `story-event-${ordinal}`;
  const number = element("span", "story-event-number", String(ordinal).padStart(2, "0")); number.setAttribute("aria-label", `Event ${ordinal}`); article.append(number);
  const head = element("div", "story-event-head");
  const heading = element("h3", "story-event-heading");
  const control = storySelectionControl(event, "story-event", routeContext);
  heading.append(control);
  head.append(heading);
  if (!progressiveStoryActive()) head.append(storyDetailControl(event, control));
  article.append(head);
  if (progressiveStoryActive()) {
    const detail = appendProgressiveStoryDetail(article, event, control);
    bindProgressiveStoryDetail(control, detail);
    applyStoryRouteContext(detail, routeContext, { reading: true });
  }
  else { appendStoryBadges(article, event); appendStoryWarnings(article, event.warnings); }
  if (event.characters?.length) {
    const characters = element("div", "story-characters");
    for (const character of event.characters) characters.append(element("span", "", character));
    article.append(characters);
  }
  const choices = element("div", "story-choices");
  const merges = new Set();
  for (const choice of event.choices || []) choices.append(renderStoryChoice(choice, false, null, [], merges, ordinalState, routeContext, storyItemTitle(event)));
  if (choices.children.length) article.append(choices);
  return article;
}

function storyReaderContractFromBootstrap(bootstrap) {
  const candidates = [
    bootstrap?.story_reader,
    bootstrap?.story_map_v2_reader,
    ...Object.values(bootstrap?.contracts || {}),
    ...Object.values(bootstrap?.routes || {}),
  ];
  return candidates.find((candidate) => candidate?.schema === "story-map-v2-reader-contract-v2" && candidate.routes && candidate.limits) || null;
}

function storyReaderActive() {
  return Boolean(state.storyReader.manifest && api.storyReaderRoutes);
}

function storyReaderGroupedTimeline() {
  const sections = state.storyReader.manifest?.sections || [];
  return sections.length >= STORY_TIMELINE_MIN_GROUPS && sections.length <= STORY_TIMELINE_MAX_GROUPS && sections.every((section) => section.id.startsWith("story-group:"));
}

function orderedStoryReaderSections() {
  return [...(state.storyReader.manifest?.sections || [])].sort((a, b) => a.order - b.order);
}

function storyReaderSectionDomId(sectionId) {
  const index = orderedStoryReaderSections().findIndex((section) => section.id === sectionId);
  return index < 0 ? null : `story-group-${index + 1}`;
}

function appendStoryReaderNew(host, item) {
  if (!item?.is_new) return;
  $("#storyHideNewControl").hidden = false;
  if (state.storyReader.hideNew) return;
  const mark = element("span", "story-new", "NEW");
  const facts = (item.new_facts || []).map((fact) => `${fact.kind}: ${fact.fact_id}`);
  if (facts.length) mark.title = facts.join("\n");
  host.append(mark);
}

function readerItemControl(item, ordinal) {
  const control = element("button", "story-event-select"); control.type = "button";
  control.dataset.storySelectionId = item.selection_id;
  const title = element("strong", "", storyItemTitle(item)); appendStoryReaderNew(title, item);
  control.append(title, element("span", "", storyOutlineSummary(item)));
  control.setAttribute("aria-label", `${ordinal ? `Story moment ${ordinal}: ` : ""}${storyItemTitle(item)}`);
  control.addEventListener("click", () => selectStoryReaderItem(item, control));
  return control;
}

function renderStoryReaderItem(item, ordinal) {
  const article = element("li", `story-event story-reader-item story-kind-${item.kind}`);
  article.dataset.readerItemId = item.id;
  if (item.selection_id) article.dataset.storySelectionId = item.selection_id;
  const number = element("span", "story-event-number", String(ordinal).padStart(2, "0"));
  number.setAttribute("aria-label", `Story moment ${ordinal}`); article.append(number);
  const head = element("div", "story-event-head");
  if (item.selection_id) {
    state.storyItems.set(item.selection_id, item);
    const control = readerItemControl(item, ordinal);
    const detail = element("button", "story-detail-button", "Detail / Evidence"); detail.type = "button";
    detail.addEventListener("click", async () => { if (state.storySelectionId !== item.selection_id) activateStoryItem(item, control); await openStoryReaderDetail(item.selection_id); });
    head.append(control, detail);
  } else {
    const copy = element("div", "story-event-select");
    const title = element("strong", "", storyItemTitle(item)); appendStoryReaderNew(title, item);
    copy.append(title, element("span", "", storyOutlineSummary(item))); head.append(copy);
  }
  const marker = { choice: "Choice", arm: "Outcome", ending: "Ending" }[item.kind];
  if (marker) article.append(element("span", "story-item-marker", marker));
  article.append(head); appendStoryBadges(article, item); appendStoryWarnings(article, item.warnings || item.unresolved_warnings);
  if (item.kind === "choice") {
    const button = element("button", "quiet-button story-branch-action", "Show outcomes"); button.type = "button";
    button.setAttribute("aria-expanded", "false");
    const branchHost = element("div", "story-branch-page"); branchHost.dataset.branchFor = item.id; branchHost.hidden = true;
    button.addEventListener("click", () => {
      if (button.getAttribute("aria-expanded") === "true") { branchHost.hidden = true; button.setAttribute("aria-expanded", "false"); button.textContent = "Show outcomes"; return; }
      loadStoryReaderBranch(item.id, branchHost, null, false, button);
    });
    article.append(button, branchHost);
  }
  return article;
}

function storyReaderShell(page, shell, ordinalStart) {
  const byId = new Map(page.items.map((item) => [item.id, item]));
  const host = element("section", "story-shell"); host.dataset.shellId = shell.id; host.dataset.shellKind = shell.kind;
  if (shell.route_id) host.append(element("p", "story-shell-route", shell.route_id));
  const list = element("ol", "story-events"); let ordinal = ordinalStart;
  for (const id of shell.item_ids) { const item = byId.get(id); if (item) list.append(renderStoryReaderItem(item, ++ordinal)); }
  host.append(list);
  if (shell.rejoin_selection_id) {
    const rejoin = element("div", "story-rejoin");
    const button = element("button", "quiet-button", "Rejoin"); button.type = "button";
    button.addEventListener("click", () => locateStoryReaderSelection(shell.rejoin_selection_id));
    rejoin.append(button); host.append(rejoin);
  }
  return { host, ordinal };
}

function combinedReaderPage(left, right) {
  if (!left) return right;
  return {
    ...right,
    items: [...left.items, ...right.items],
    shells: [...left.shells, ...right.shells],
    rendered_item_count: left.rendered_item_count + right.rendered_item_count,
  };
}

function storyProjectionCounts() {
  return {
    section: $$("#storySections [data-reader-item-id]").length,
    search: Number($("#storySearchResults").dataset.storyRecords || 0),
    path: Number($("#storyPathPanel").dataset.storyRecords || 0),
    detail: Number($("#detailView").dataset.storyRecords || 0),
  };
}

function storyProjectionTotal(counts, detailSurface) {
  return detailSurface ? counts.detail : counts.section + counts.search + counts.path;
}

function reserveStoryProjection(kind, incoming) {
  const counts = { ...storyProjectionCounts(), [kind]: incoming };
  const total = storyProjectionTotal(counts, kind === "detail");
  if (total > state.storyReader.contract.limits.live_story_items) throw new RangeError("This view would exceed the live story-record limit");
  return total;
}

function recordStoryProjection(kind, count) {
  const hosts = { search: $("#storySearchResults"), path: $("#storyPathPanel"), detail: $("#detailView") };
  if (hosts[kind]) hosts[kind].dataset.storyRecords = String(count);
  const total = storyProjectionTotal(storyProjectionCounts(), !$("#detailView").hidden);
  $("#storyBrowser").dataset.liveStoryItems = String(total);
}

function renderStoryReaderSection(page, section, { append = false, ordinalStart = 0 } = {}) {
  const sections = $("#storySections");
  const incoming = append ? sections.querySelectorAll("[data-reader-item-id]").length + page.rendered_item_count : page.rendered_item_count;
  reserveStoryProjection("section", incoming);
  if (!append) { state.storyItems = new Map(); sections.replaceChildren(); }
  const card = element("section", "story-section"); card.dataset.status = "ready"; card.dataset.freshness = state.storyReader.manifest.freshness;
  card.dataset.sectionId = section.id;
  card.id = storyReaderSectionDomId(section.id) || "";
  const header = element("header", "story-section-header");
  const title = element("h2", "", section.title); appendStoryReaderNew(title, section);
  header.append(title, element("p", "story-section-summary", storyOutlineSummary(section))); card.append(header);
  const grouped = storyReaderGroupedTimeline();
  const content = grouped ? element("details", "story-group-details") : card;
  if (grouped) {
    const count = page.items.length;
    content.append(element("summary", "story-group-toggle", `${count} story moment${count === 1 ? "" : "s"}`));
    card.append(content);
  }
  let ordinal = ordinalStart; const rendered = new Set();
  for (const shell of page.shells) {
    const result = storyReaderShell(page, shell, ordinal); ordinal = result.ordinal;
    shell.item_ids.forEach((id) => rendered.add(id)); content.append(result.host);
  }
  const missing = page.items.filter((item) => !rendered.has(item.id));
  if (missing.length) content.append(element("p", "story-empty", `${missing.length} item${missing.length === 1 ? "" : "s"} withheld because no server-authored shell was supplied.`));
  sections.append(card);
  const live = sections.querySelectorAll("[data-reader-item-id]").length;
  recordStoryProjection("section", live);
  $("#storyLoadMore").hidden = storyReaderGroupedTimeline() || !page.next_cursor || page.rendered_item_count >= state.storyReader.contract.limits.live_story_items;
  $("#storyLoadMore").disabled = false;
  $("#storyLoadMore").dataset.cursor = page.next_cursor || "";
  for (const button of $$("#storySectionIndex button")) button.setAttribute("aria-current", String(button.dataset.sectionId === section.id));
  return ordinal;
}

async function loadStoryReaderTimeline() {
  const token = ++state.storyReader.requestToken;
  state.storyItems = new Map(); state.storyReader.currentPage = null;
  const host = $("#storySections"); host.replaceChildren();
  let ordinal = 0;
  for (const section of orderedStoryReaderSections()) {
    try {
      let page = await storyReaderPage("section_page", section.id, null);
      while (page.next_cursor) {
        const next = await storyReaderPage("section_page", section.id, page.next_cursor);
        if (token !== state.storyReader.requestToken) return;
        page = combinedReaderPage(page, next);
      }
      if (token !== state.storyReader.requestToken) return;
      ordinal = renderStoryReaderSection(page, section, { append: true, ordinalStart: ordinal });
    } catch (error) {
      if (await handleStoryReaderError(error)) return;
      if (token === state.storyReader.requestToken) host.append(element("p", "story-empty", `${section.title}: ${error.message}`));
    }
  }
  state.storyReader.currentSectionId = orderedStoryReaderSections()[0]?.id || null;
  for (const button of $$("#storySectionIndex button")) button.setAttribute("aria-current", String(button.dataset.sectionId === state.storyReader.currentSectionId));
  $("#storyLoadMore").hidden = true;
  recordStoryProjection("section", host.querySelectorAll("[data-reader-item-id]").length);
}

function storyReaderCacheKey(kind, resourceId, cursor) { return `${kind}:${resourceId}:${cursor || "first"}`; }

async function storyReaderPage(kind, resourceId, cursor = null) {
  const key = storyReaderCacheKey(kind, resourceId, cursor);
  const cache = kind === "section_page" ? state.storyReader.sectionCache : state.storyReader.branchCache;
  if (cache.has(key)) return cache.get(key);
  const options = { cursor };
  if (kind === "section_page") options.limit = state.storyReader.contract.limits.events_per_section_page;
  else options.limit = state.storyReader.contract.limits.rendered_items_per_page;
  const page = await api.storyReaderPage(kind, state.storyReader.mapRevision, resourceId, options);
  cache.set(key, page); return page;
}

async function prefetchStoryReaderNeighbor(sectionId) {
  const sections = state.storyReader.manifest?.sections || [];
  const index = sections.findIndex((section) => section.id === sectionId);
  const neighbor = sections[index + 1];
  if (!neighbor || state.storyReader.prefetchedSectionId === neighbor.id) return;
  state.storyReader.prefetchedSectionId = neighbor.id;
  try { await storyReaderPage("section_page", neighbor.id, null); } catch (error) { if (error.code === "stale_map_revision") refreshStoryReaderForRevision(error.mapRevision); }
}

async function loadStoryReaderSection(sectionId, { cursor = null, append = false, focusId = null, locateToken = null } = {}) {
  if (locateToken === null) state.storyReader.locateToken += 1;
  const section = state.storyReader.manifest?.sections.find((candidate) => candidate.id === sectionId);
  if (!section) throw new Error("The requested story section is unavailable");
  const token = ++state.storyReader.requestToken;
  if (!append) {
    state.storyReader.currentSectionId = sectionId; state.storyReader.currentPage = null;
    $("#storySections").replaceChildren();
    const loading = element("section", "story-section"); loading.dataset.status = "loading"; loading.append(element("p", "eyebrow", "Loading section"), element("h2", "", section.title)); $("#storySections").append(loading);
  }
  try {
    const page = await storyReaderPage("section_page", sectionId, cursor);
    if (token !== state.storyReader.requestToken || state.storyReader.currentSectionId !== sectionId || (locateToken !== null && locateToken !== state.storyReader.locateToken)) return;
    const combined = append ? combinedReaderPage(state.storyReader.currentPage, page) : page;
    if (combined.rendered_item_count > state.storyReader.contract.limits.live_story_items) throw new RangeError("Continue would exceed the live story-item limit");
    state.storyReader.currentPage = combined; renderStoryReaderSection(combined, section); scheduleStoryReaderViewSave();
    if (focusId) focusStoryReaderItem(focusId);
    prefetchStoryReaderNeighbor(sectionId);
  } catch (error) { if (await handleStoryReaderError(error)) return; if (token === state.storyReader.requestToken) $("#storySections").replaceChildren(element("p", "story-empty", error.message)); }
}

function renderStoryReaderBranchPage(page, host) {
  host.replaceChildren(); let ordinal = 0;
  for (const shell of page.shells) { const result = storyReaderShell(page, shell, ordinal); ordinal = result.ordinal; host.append(result.host); }
  if (page.next_cursor) {
    const more = element("button", "quiet-button story-branch-action", "More choices"); more.type = "button";
    more.addEventListener("click", () => loadStoryReaderBranch(page.resource_id, host, page.next_cursor, true, more)); host.append(more);
  }
  host.hidden = false;
  if ($$("#storySections [data-reader-item-id]").length > state.storyReader.contract.limits.live_story_items) throw new RangeError("Branch hydration exceeds the live story-item limit");
}

async function loadStoryReaderBranch(branchId, host, cursor = null, append = false, button = null, locateToken = null) {
  const label = button?.textContent; const restoreFocus = button && document.activeElement === button;
  if (button) { button.disabled = true; button.textContent = "Loading…"; }
  const token = state.storyReader.requestToken;
  try {
    const page = await storyReaderPage("branch_page", branchId, cursor);
    if (token !== state.storyReader.requestToken || (locateToken !== null && locateToken !== state.storyReader.locateToken) || !host.isConnected) return;
    const currentSection = $$("#storySections [data-reader-item-id]").length;
    const replacedLive = append ? 0 : host.querySelectorAll("[data-reader-item-id]").length;
    reserveStoryProjection("section", currentSection - replacedLive + page.rendered_item_count);
    if (append) {
      const wrapper = element("div", "story-branch-page"); renderStoryReaderBranchPage(page, wrapper);
      host.querySelector(".story-branch-action:last-child")?.remove(); while (wrapper.firstChild) host.append(wrapper.firstChild);
    } else {
      for (const current of $$(".story-branch-page:not([hidden])")) if (current !== host) { const trigger = current.previousElementSibling; current.replaceChildren(); current.hidden = true; if (trigger?.classList.contains("story-branch-action")) { trigger.hidden = false; trigger.disabled = false; trigger.textContent = "Show outcomes"; trigger.setAttribute("aria-expanded", "false"); } }
      renderStoryReaderBranchPage(page, host);
    }
    recordStoryProjection("section", $$("#storySections [data-reader-item-id]").length);
    if (button) {
      button.disabled = false;
      if (append) { button.hidden = true; if (restoreFocus) host.querySelector("[data-story-selection-id]")?.focus(); }
      else { button.hidden = false; button.textContent = "Hide outcomes"; button.setAttribute("aria-expanded", "true"); if (restoreFocus) button.focus(); }
    }
  } catch (error) { if (!(await handleStoryReaderError(error))) toast(error.message); if (button) { button.disabled = false; button.textContent = label; if (restoreFocus) button.focus(); } }
}

function renderStoryReaderManifest(manifest) {
  const previousRevision = state.storyReader.mapRevision;
  state.storyReader.manifest = manifest; state.storyReader.mapRevision = manifest.map_revision; state.storyReader.generationId = manifest.generation_id;
  $("#storyBrowser").dataset.mapRevision = String(manifest.map_revision); $("#storyBrowser").dataset.generationId = manifest.generation_id;
  state.storyPage = { reader: true, map_revision: manifest.map_revision };
  if (previousRevision !== manifest.map_revision) { state.storyReader.sectionCache = new Map(); state.storyReader.branchCache = new Map(); state.storyReader.currentPage = null; }
  $("#storyTitle").textContent = manifest.overview.title; $("#storyOverview").textContent = manifest.overview.summary;
  $("#storyMapStatus").textContent = manifest.freshness === "stale" ? "Stale map" : manifest.freshness === "building" ? "Building" : manifest.freshness === "phase03_compatible" ? "Compatible map" : "Current map";
  $("#storyPrepareAction").textContent = manifest.freshness === "phase03_compatible" || !manifest.generation_id ? "Generate" : "Update";
  const index = $("#storySectionIndex"); index.replaceChildren();
  const grouped = storyReaderGroupedTimeline();
  $("#storyBrowser").classList.remove("is-progressive-story", "is-story-river");
  $("#storyBrowser").classList.toggle("is-grouped-timeline", grouped);
  index.setAttribute("aria-label", grouped ? "Major story events" : "Story sections");
  for (const section of orderedStoryReaderSections()) {
    const button = element("button", "", section.title); button.type = "button"; button.dataset.sectionId = section.id;
    if (section.is_new && !state.storyReader.hideNew) appendStoryReaderNew(button, section);
    button.addEventListener("click", () => {
      if (!grouped) { loadStoryReaderSection(section.id); return; }
      state.storyReader.currentSectionId = section.id;
      for (const current of $$("#storySectionIndex button")) current.setAttribute("aria-current", String(current === button));
      document.getElementById(storyReaderSectionDomId(section.id))?.scrollIntoView({ block: "start" });
      scheduleStoryReaderViewSave();
    }); index.append(button);
  }
  index.hidden = !manifest.sections.length;
  $("#storyAnalysisNotes").hidden = true; $("#storyPathPanel").hidden = true; $("#storyRoutePanel").hidden = true; $("#storyRunDetails").open = false; clearStoryPathWitness();
  $("#storyBrowser").classList.toggle("hide-new", state.storyReader.hideNew); showStorySurface(true);
  setStoryWorkflowChrome({ prepare: Boolean(api.storyWorkflowRoutes) });
}

function renderStoryReaderStatus(status) {
  state.storyReader.status = status;
  if (state.storyWorkflow.response) { renderStoryWorkflow(state.storyWorkflow.response); return; }
  const progress = status.progress; const percent = progress.total_jobs ? Math.round((progress.completed_jobs / progress.total_jobs) * 100) : Math.round(status.coverage.event_fraction * 100);
  $("#storyRunDetails").hidden = !(api.storyWorkflowRoutes && status.run_id && progress.total_jobs);
  $("#storyRunState").textContent = String(status.state).replaceAll("_", " ");
  $("#storyRunProgress").textContent = `${progress.completed_jobs}/${progress.total_jobs} jobs · ${progress.failed_jobs} failed · ${progress.indeterminate_jobs} indeterminate`;
  $("#storyRunProgressBar").style.width = `${Math.max(0, Math.min(100, percent))}%`;
  $(".story-run-track").setAttribute("aria-valuenow", String(percent));
  const active = Boolean(status.active_build_generation) || ["running", "starting", "cancelling", "queued", "building"].includes(status.state);
  const actionableRun = active || status.actions.can_cancel || status.actions.can_resume || status.actions.retry_approval_required;
  setStoryWorkflowChrome({ prepare: !actionableRun && Boolean(api.storyWorkflowRoutes), progress: actionableRun });
}

function storyWorkflowTotal(status) {
  return status.pending_jobs + status.active_jobs + status.accepted_jobs + status.structural_fallback_jobs + status.resumable_jobs + status.indeterminate_jobs;
}

function storyWorkflowMaximumCalls(preview) {
  const ceilings = preview.ceilings;
  return ceilings.mapping_calls + ceilings.review_calls + ceilings.fallback_calls + ceilings.section_synthesis_calls + ceilings.rollup_synthesis_calls + ceilings.indeterminate_retry_calls;
}

function clearStoredStoryWorkflow() {
  try { localStorage.removeItem(STORY_WORKFLOW_STORAGE_KEY); } catch (_error) { /* Storage is optional. */ }
}

function storedStoryWorkflow() {
  try {
    const value = JSON.parse(localStorage.getItem(STORY_WORKFLOW_STORAGE_KEY) || "null");
    const keys = value && typeof value === "object" && !Array.isArray(value) ? Object.keys(value) : [];
    if (keys.length !== 3 || !["contract", "run_id", "preview_identity"].every((key) => keys.includes(key))) throw new TypeError("Stored story workflow binding is invalid");
    if (value.contract !== STORY_WORKFLOW_CONTRACT || typeof value.run_id !== "string" || !value.run_id || value.run_id.length > 1024 || typeof value.preview_identity !== "string" || !value.preview_identity || value.preview_identity.length > 1024) throw new TypeError("Stored story workflow binding is invalid");
    return value;
  } catch (_error) { clearStoredStoryWorkflow(); return null; }
}

function persistStoryWorkflow(response) {
  const status = response.status;
  const unfinished = status.pending_jobs + status.active_jobs + status.resumable_jobs + status.indeterminate_jobs;
  if (status.cancelled || unfinished === 0) { clearStoredStoryWorkflow(); return; }
  const binding = { contract: STORY_WORKFLOW_CONTRACT, run_id: response.preview.run_id, preview_identity: response.preview.preview_identity };
  try { localStorage.setItem(STORY_WORKFLOW_STORAGE_KEY, JSON.stringify(binding)); } catch (_error) { /* The current page still works without persistence. */ }
}

function renderStoryWorkflowDetails(response) {
  const details = $("#storyRunDetails"); const body = $("#storyRunRows");
  const jobs = response.preview.jobs || []; const status = response.status;
  body.replaceChildren(); details.hidden = !jobs.length;
  if (!jobs.length) return;
  const completed = Math.min(jobs.length, status.accepted_jobs + status.structural_fallback_jobs);
  const activeEnd = Math.min(jobs.length, completed + status.active_jobs);
  const allAccepted = completed > 0 && status.accepted_jobs === completed;
  const allStructural = completed > 0 && status.structural_fallback_jobs === completed;
  const cacheHits = new Set([...(response.preview.cache_hits?.cloud_job_ids || []), ...(response.preview.cache_hits?.loopback_job_ids || [])]);
  const scopes = new Map(); const parts = new Map();
  for (const [index, job] of jobs.entries()) {
    if (!scopes.has(job.scope_id)) scopes.set(job.scope_id, scopes.size + 1);
    const part = (parts.get(job.scope_id) || 0) + 1; parts.set(job.scope_id, part);
    let ai = "Waiting"; let summary = "Pending"; let comment = "Queued for the local model.";
    if (index < completed) {
      if (allAccepted) {
        ai = cacheHits.has(job.job_id) ? "Cached" : "Passed"; summary = "Added";
        comment = cacheHits.has(job.job_id) ? "Accepted summary reused." : "AI summary accepted.";
      } else if (allStructural) {
        ai = "Rejected"; summary = "Placeholder"; comment = "See the private local transcript for the validator comment.";
      } else {
        ai = "Finished"; summary = "See totals"; comment = `${status.accepted_jobs} accepted, ${status.structural_fallback_jobs} placeholders; exact results are in the transcript.`;
      }
    } else if (index < activeEnd) {
      ai = "Running"; summary = "Pending"; comment = "Waiting for the local model response.";
    }
    const row = element("tr"); row.dataset.workflowJobId = job.job_id;
    row.append(
      element("td", "", `Query ${index + 1}: story section ${scopes.get(job.scope_id)}, part ${part}`),
      element("td", "", ai), element("td", "", summary), element("td", "", comment),
    );
    body.append(row);
  }
}

function renderStoryWorkflow(response) {
  state.storyWorkflow.response = response;
  persistStoryWorkflow(response);
  const status = response.status; const total = storyWorkflowTotal(status);
  const completed = Math.min(total, status.accepted_jobs + status.structural_fallback_jobs);
  const percent = total ? Math.round((completed / total) * 100) : 100;
  $("#storyRunState").textContent = status.cancelled ? "Cancelled" : status.active_jobs ? "Generating" : status.resumable_jobs ? "Paused" : completed >= total ? "Complete" : status.approved ? "Waiting" : "Ready";
  $("#storyRunProgress").textContent = `${completed} of ${total} jobs completed`;
  $("#storyRunProgressBar").style.width = `${percent}%`;
  $(".story-run-track").setAttribute("aria-valuenow", String(percent));
  const actionableRun = status.can_cancel || status.can_resume;
  setStoryWorkflowChrome({
    prepare: !actionableRun && Boolean(api.storyWorkflowRoutes),
    progress: actionableRun,
    cancel: status.can_cancel,
    resume: status.can_resume,
  });
  renderStoryWorkflowDetails(response);
}

async function restoreStoryWorkflow() {
  if (!api.storyWorkflowRoutes) return false;
  const binding = storedStoryWorkflow(); if (!binding) return false;
  try {
    const response = await api.storyWorkflowStatus(binding);
    if (response.preview.run_id !== binding.run_id || response.preview.preview_identity !== binding.preview_identity) throw new TypeError("Stored story workflow binding is stale");
    renderStoryWorkflow(response); await refreshReaderIfPublished();
    if (response.status.pending_jobs || response.status.active_jobs) pollStoryWorkflow();
    return true;
  } catch (error) {
    if (error instanceof TypeError || ["invalid_workflow_request", "workflow_run_not_found", "stale_workflow_preview", "stale_workflow_approval"].includes(error?.code)) clearStoredStoryWorkflow();
    return false;
  }
}

async function loadPublishedStoryWorkflowDetails() {
  const details = $("#storyRunDetails"); const runId = state.storyReader.status?.run_id;
  if (!details.open || state.storyWorkflow.response || state.storyWorkflow.busy || !api.storyWorkflowRoutes || typeof runId !== "string" || !runId) return;
  state.storyWorkflow.busy = true;
  try {
    const response = await api.storyWorkflowStatus({ run_id: runId });
    if (response.preview.run_id !== runId) throw new TypeError("Published story workflow binding is stale");
    renderStoryWorkflow(response);
  } catch (error) { details.open = false; toast(error.message); }
  finally { state.storyWorkflow.busy = false; }
}

function storyWorkflowFacts(preview) {
  const primary = preview.policy.cloud ?? preview.policy.loopback; const cacheHits = preview.cache_hits.cloud_job_ids.length + preview.cache_hits.loopback_job_ids.length;
  const privacy = preview.privacy; const chunks = preview.jobs.length;
  const disclosure = [
    privacy.cloud_story_content ? "Private story text may be sent to the cloud provider." : "No private story text is sent to the cloud provider.",
    privacy.loopback_story_content ? "Private story text may be sent to the configured local provider." : "No private story text is sent to a local provider.",
  ].join(" ");
  return [
    ["Provider", primary.provider], ["Model", primary.model], ["Reasoning", primary.reasoning ?? "Not specified"], ["Fast mode", primary.fast_mode === null ? "Not specified" : `${primary.fast_mode} (${primary.fast_mode ? "on" : "off"})`],
    ["Private content", disclosure], ["Work", `${chunks} ${chunks === 1 ? "chunk" : "chunks"} · ${chunks} ${chunks === 1 ? "job" : "jobs"}`],
    ["Maximum calls", String(storyWorkflowMaximumCalls(preview))], ["Cache hits", String(cacheHits)],
  ];
}

function showStoryWorkflowApproval(response) {
  renderStoryWorkflow(response); const facts = $("#storyApprovalFacts"); facts.replaceChildren();
  for (const [label, value] of storyWorkflowFacts(response.preview)) facts.append(element("dt", "", label), element("dd", "", value));
  $("#storyApprovalState").textContent = "Starting requires explicit approval for this preview.";
  $("#approveStoryGeneration").disabled = !response.status.can_start;
  $("#storyApprovalDialog").showModal();
}

async function prepareStoryWorkflow() {
  if (!api.storyWorkflowRoutes || state.storyWorkflow.busy) return;
  state.storyWorkflow.busy = true; $("#storyPrepareAction").disabled = true;
  try { showStoryWorkflowApproval(await api.prepareStoryWorkflow()); }
  catch (error) { toast(error.message); }
  finally { state.storyWorkflow.busy = false; $("#storyPrepareAction").disabled = !api.storyWorkflowRoutes; }
}

async function refreshReaderIfPublished() {
  if (!api.storyReaderRoutes || !state.storyReader.manifest) return;
  const status = await api.storyReaderStatus();
  if (status.map_revision !== state.storyReader.mapRevision || status.current_complete_generation !== state.storyReader.generationId) await refreshStoryReaderForRevision();
}

async function pollStoryWorkflow() {
  const initial = state.storyWorkflow.response; if (!initial) return;
  const token = ++state.storyWorkflow.pollToken;
  const poll = async () => {
    try {
      const response = await api.storyWorkflowStatus(state.storyWorkflow.response.preview);
      if (token !== state.storyWorkflow.pollToken) return;
      renderStoryWorkflow(response); await refreshReaderIfPublished();
      if (response.status.pending_jobs || response.status.active_jobs) setTimeout(poll, 900);
    } catch (error) { if (token === state.storyWorkflow.pollToken) $("#storyRunProgress").textContent = error.message; }
  };
  await poll();
}

async function runStoryWorkflow(command) {
  const binding = state.storyWorkflow.response?.preview; if (!binding || state.storyWorkflow.busy) return;
  state.storyWorkflow.busy = true;
  try {
    const response = await (command === "start" ? api.startStoryWorkflow(binding) : command === "cancel" ? api.cancelStoryWorkflow(binding) : api.resumeStoryWorkflow(binding));
    renderStoryWorkflow(response); $("#storyApprovalDialog").close(); await refreshReaderIfPublished();
    if (command !== "cancel") pollStoryWorkflow();
  } catch (error) { toast(error.message); }
  finally { state.storyWorkflow.busy = false; $("#storyPrepareAction").disabled = !api.storyWorkflowRoutes; }
}

async function pollStoryReaderStatus() {
  const token = ++state.storyReader.statusToken;
  const poll = async () => {
    try {
      const status = await api.storyReaderStatus(); if (token !== state.storyReader.statusToken) return;
      if (status.map_revision !== state.storyReader.mapRevision) { await refreshStoryReaderForRevision(status.map_revision); return; }
      renderStoryReaderStatus(status);
      if (status.active_build_generation || ["running", "starting", "cancelling", "queued", "building"].includes(status.state)) setTimeout(poll, 900);
    } catch (error) { if (!(await handleStoryReaderError(error)) && token === state.storyReader.statusToken) $("#storyRunProgress").textContent = error.message; }
  };
  await poll();
}

async function refreshStoryReaderForRevision() {
  state.storyReader.requestToken += 1; state.storyReader.locateToken += 1; state.storyReader.searchToken += 1; state.storyPathToken += 1; invalidateStoryDetail();
  state.storyReader.restored = false; const manifest = await api.storyReaderManifest(); renderStoryReaderManifest(manifest); await restoreStoryReaderView();
  toast("The story map changed. The current revision is shown."); pollStoryReaderStatus();
}

async function handleStoryReaderError(error) {
  if (error?.code !== "stale_map_revision") return false;
  try { await refreshStoryReaderForRevision(error.mapRevision); } catch (refreshError) { toast(refreshError.message); }
  return true;
}

function focusStoryReaderItem(itemId) {
  const node = $(`[data-reader-item-id="${CSS.escape(itemId)}"]`); const control = node?.querySelector("[data-story-selection-id]");
  if (!control) return false;
  const group = control.closest(".story-group-details"); if (group) group.open = true;
  control.scrollIntoView({ block: "center", inline: "nearest" }); control.focus({ preventScroll: true }); return true;
}

async function locateStoryReaderSelection(selectionId, { activate = true } = {}) {
  const token = ++state.storyReader.locateToken;
  try {
    const located = await api.storyReaderLocate(state.storyReader.mapRevision, selectionId); if (token !== state.storyReader.locateToken) return;
    const location = located.location;
    let sectionHost = null;
    if (storyReaderGroupedTimeline()) {
      state.storyReader.currentSectionId = location.section_id;
      sectionHost = document.getElementById(storyReaderSectionDomId(location.section_id));
      if (!sectionHost) throw new Error("The server-located story group is not present in the timeline");
      for (const button of $$("#storySectionIndex button")) button.setAttribute("aria-current", String(button.dataset.sectionId === location.section_id));
    } else {
      await loadStoryReaderSection(location.section_id, { cursor: location.branch_id === null ? location.page_cursor : null, locateToken: token });
    }
    if (token !== state.storyReader.locateToken) return;
    if (location.branch_id !== null) {
      const host = (sectionHost || document).querySelector(`[data-branch-for="${CSS.escape(location.branch_id)}"]`);
      if (!host) throw new Error("The server-located branch parent is not present in its section page");
      if (host.hidden || !host.children.length) {
        const trigger = host.previousElementSibling?.classList.contains("story-branch-action") ? host.previousElementSibling : null;
        await loadStoryReaderBranch(location.branch_id, host, location.page_cursor, false, trigger, token);
      }
    }
    if (token !== state.storyReader.locateToken) return;
    if (!focusStoryReaderItem(location.item_id)) throw new Error("The located story item is not available in the returned page");
    const control = $(`[data-reader-item-id="${CSS.escape(location.item_id)}"] [data-story-selection-id]`);
    const item = state.storyItems.get(selectionId); if (activate && control && item) activateStoryItem(item, control);
  } catch (error) { if (!(await handleStoryReaderError(error))) toast(error.message); }
}

async function searchStoryReader(query, { cursor = null, append = false } = {}) {
  const token = ++state.storyReader.searchToken; const host = $("#storySearchResults");
  if (!query) { host.hidden = true; host.replaceChildren(); recordStoryProjection("search", 0); return; }
  try {
    const response = await api.storyReaderSearch(state.storyReader.mapRevision, query, { cursor, limit: state.storyReader.contract.limits.search_results_per_page });
    if (token !== state.storyReader.searchToken || $("#storySearchInput").value !== query) return;
    const currentResults = append ? host.querySelectorAll(".story-search-result").length : 0;
    reserveStoryProjection("search", currentResults + response.results.length);
    if (!append) host.replaceChildren(); else host.querySelector(".story-search-more")?.remove();
    for (const result of response.results) {
      const button = element("button", "story-search-result"); button.type = "button";
      button.append(element("strong", "", result.title), element("span", "", result.snippet));
      button.addEventListener("click", () => { host.hidden = true; host.replaceChildren(); recordStoryProjection("search", 0); locateStoryReaderSelection(result.selection_id); }); host.append(button);
    }
    if (response.next_cursor) {
      const more = element("button", "quiet-button story-search-more", "More results"); more.type = "button";
      more.addEventListener("click", () => { more.disabled = true; searchStoryReader(query, { cursor: response.next_cursor, append: true }); }); host.append(more);
    }
    if (!host.children.length) host.append(element("p", "story-empty", "No matching story moments.")); host.hidden = false; recordStoryProjection("search", host.querySelectorAll(".story-search-result").length);
  } catch (error) { if (!(await handleStoryReaderError(error)) && token === state.storyReader.searchToken) toast(error.message); }
}

function storyReaderPathValue(item) {
  const value = item && typeof item === "object" ? item.text ?? item.summary ?? item.value ?? item : item;
  if (value === null || value === undefined) return "";
  if (typeof value !== "object") return String(value);
  if (typeof value.expression === "string") return value.expression;
  if (typeof value.text === "string") return value.text;
  if (typeof value.title === "string") return value.title;
  return Object.entries(value).map(([key, entry]) => `${key.replaceAll("_", " ")}: ${String(entry)}`).join(" · ");
}

function storyChoiceText(value) {
  const text = storyReaderPathValue(value).trim();
  const instruction = /^Choose\s+["“](.+)["”]\.?$/iu.exec(text);
  return (instruction?.[1] || text).trim();
}

function storyChoiceKey(value) { return storyChoiceText(value).replace(/\s+/gu, " ").toLocaleLowerCase(); }

function selectedStoryChoices(visibleChoices, instructions) {
  const result = []; const seen = new Set();
  for (const value of [...(visibleChoices || []), ...(instructions || []).filter((instruction) => instruction?.kind === "choice")]) {
    const text = storyChoiceText(value); const key = storyChoiceKey(text);
    if (!text || seen.has(key)) continue;
    seen.add(key); result.push(text);
  }
  return result;
}

function renderStoryReaderPath(page) {
  reserveStoryProjection("path", page.rendered_item_count);
  state.storyPath = page; const item = state.storySelectionItem || {};
  $("#storyPathTitle").textContent = storyItemTitle(item);
  clearStoryPathWitness(); const steps = $("#storyPathSteps");
  const summary = page.items.find((value) => value.kind === "summary");
  $("#storyPathSummary").textContent = storyReaderPathValue(summary || {}) || "Known path to this moment.";
  const requirements = page.items.filter((value) => value.kind === "requirement").map(storyReaderPathValue);
  const effects = page.items.filter((value) => value.kind === "effect").map(storyReaderPathValue);
  const instructions = page.items.filter((value) => value.kind === "instruction").map((value) => value.value).filter((value) => value && typeof value === "object");
  const instructionChoiceKeys = new Set(instructions.filter((value) => value.kind === "choice").map(storyChoiceKey));
  const visibleChoices = page.items.filter((value) => value.kind === "path_step" && instructionChoiceKeys.has(storyChoiceKey(value))).map(storyReaderPathValue);
  renderStoryWitnessList("#storyPathChoicesGroup", "#storyPathChoices", selectedStoryChoices(visibleChoices, instructions));
  renderStoryWitnessList("#storyPathRequirementsGroup", "#storyPathRequirements", requirements);
  renderStoryWitnessList("#storyPathEffectsGroup", "#storyPathEffects", effects);
  const ordered = [...page.items].filter((value) => !["summary", "requirement", "effect", "warning"].includes(value.kind) && !(value.kind === "path_step" && instructionChoiceKeys.has(storyChoiceKey(value)))).sort((left, right) => Number(left.kind === "instruction") - Number(right.kind === "instruction") || left.order - right.order);
  for (const value of ordered) {
    const title = value.title || String(value.kind).replaceAll("_", " "); const copy = storyReaderPathValue(value);
    const step = element("li", `story-path-step story-path-kind-${value.kind}`); step.append(element("strong", "", title));
    if (copy && copy !== title) step.append(element("span", "", copy)); steps.append(step);
  }
  $("#storyPathAnalysisNotes").hidden = !steps.children.length && $("#storyPathScenesGroup").hidden;
  const warnings = $("#storyPathWarnings");
  for (const value of page.items.filter((candidate) => candidate.kind === "warning")) warnings.append(element("p", "", storyReaderPathValue(value)));
  $("#storyPathUncertaintyGroup").hidden = !warnings.children.length;
  if (page.next_cursor) { const more = element("button", "quiet-button story-path-more", "Continue path"); more.type = "button"; more.addEventListener("click", async () => { more.disabled = true; const token = state.storyPathToken; try { const next = await api.storyReaderPathPage(state.storyReader.mapRevision, page.resource_id, { cursor: page.next_cursor, limit: state.storyReader.contract.limits.rendered_items_per_page }); const combined = combinedReaderPage(page, next); if (combined.rendered_item_count > state.storyReader.contract.limits.live_story_items) throw new RangeError("Path would exceed the live story-item limit"); if (token === state.storyPathToken && state.storySelectionId === page.resource_id) renderStoryReaderPath(combined); } catch (error) { if (!(await handleStoryReaderError(error))) toast(error.message); } }); steps.after(more); }
  recordStoryProjection("path", page.rendered_item_count); $("#storyDetailAction").disabled = false; $("#storyPathPanel").hidden = false;
}

async function selectStoryReaderItem(item, control) {
  activateStoryItem(item, control); clearStoryPathWitness(); $("#storyDetailAction").disabled = true; $("#storyPathPanel").hidden = false;
  $("#storyPathTitle").textContent = storyItemTitle(item); $("#storyPathSummary").textContent = "Finding the path…"; scheduleStoryReaderViewSave();
  const token = ++state.storyPathToken;
  try { const page = await api.storyReaderPathPage(state.storyReader.mapRevision, item.selection_id, { limit: state.storyReader.contract.limits.rendered_items_per_page }); if (token === state.storyPathToken && state.storySelectionId === item.selection_id) renderStoryReaderPath(page); }
  catch (error) { if (!(await handleStoryReaderError(error)) && token === state.storyPathToken) $("#storyPathSummary").textContent = error.message; }
}

function renderStoryReaderDetail(page) {
  reserveStoryProjection("detail", page.rendered_item_count);
  const summary = page.items.find((item) => ["summary", "event", "arm", "choice"].includes(item.kind)) || page.items[0] || {};
  $("#detailTitle").textContent = summary.title || storyItemTitle(state.storySelectionItem || {}); $("#detailKind").textContent = String(summary.kind || "story moment").replaceAll("_", " ");
  $("#detailSummary").textContent = storyDetailSummary(summary) || "Exact local story evidence.";
  const evidence = $("#evidenceList"); evidence.replaceChildren();
  for (const record of page.items.filter((item) => item.kind === "evidence" || item.relative_path)) {
    const article = element("article", "story-source-record"); article.dataset.evidenceId = record.id;
    article.append(element("strong", "", record.title || "Evidence")); if (record.text) article.append(element("pre", "", record.text));
    if (record.relative_path) article.append(element("code", "", `${record.relative_path}:${record.start_line}${record.end_line !== record.start_line ? `–${record.end_line}` : ""} · ${record.line_basis || "source"}`)); evidence.append(article);
  }
  if (!evidence.children.length) evidence.append(element("p", "story-empty", "No source record is available on this page."));
  if (page.next_cursor) {
    const more = element("button", "quiet-button story-detail-more", "Continue detail"); more.type = "button";
    more.addEventListener("click", async () => { more.disabled = true; const token = state.storyDetailToken; try { const next = await api.storyReaderDetailPage(state.storyReader.mapRevision, page.resource_id, { cursor: page.next_cursor, limit: state.storyReader.contract.limits.rendered_items_per_page }); const combined = combinedReaderPage(page, next); if (combined.rendered_item_count > state.storyReader.contract.limits.live_story_items) throw new RangeError("Detail would exceed the live story-item limit"); if (token === state.storyDetailToken && page.resource_id === state.storySelectionId) renderStoryReaderDetail(combined); } catch (error) { if (!(await handleStoryReaderError(error))) toast(error.message); } }); evidence.append(more);
  }
  state.detail = page; showLevel("detail_evidence"); recordStoryProjection("detail", page.rendered_item_count); $("#backToRouteMap").focus();
}

async function openStoryReaderDetail(selectionId) {
  if (selectionId !== state.storySelectionId) return;
  state.storySelectionScrollY = $("#storyBrowser").scrollTop; state.storySelectionWindowY = window.scrollY;
  const control = currentStorySelectionControl(selectionId); state.storySelectionViewportTop = control?.getBoundingClientRect().top || state.storySelectionViewportTop;
  const token = ++state.storyDetailToken;
  try { const page = await api.storyReaderDetailPage(state.storyReader.mapRevision, selectionId, { limit: state.storyReader.contract.limits.rendered_items_per_page }); if (token === state.storyDetailToken && selectionId === state.storySelectionId) renderStoryReaderDetail(page); }
  catch (error) { if (!(await handleStoryReaderError(error)) && token === state.storyDetailToken) toast(error.message); }
}

function storyReaderViewPayload() {
  return {
    section_id: state.storyReader.currentSectionId,
    selection_id: state.storySelectionId,
    focus_id: document.activeElement?.dataset?.storySelectionId || state.storySelectionId,
    viewport: { scroll_top: $("#storyBrowser").scrollTop, zoom: 1.0 },
    hide_new: state.storyReader.hideNew,
  };
}

function scheduleStoryReaderViewSave() {
  if (!storyReaderActive() || !state.storyReader.restored) return; clearTimeout(state.storyReader.saveTimer);
  state.storyReader.saveTimer = setTimeout(async () => { try { const saved = await api.saveStoryReaderViewState(state.storyReader.mapRevision, storyReaderViewPayload()); $("#storyBrowser").dataset.viewStateSaved = `${saved.map_revision}:${Date.now()}`; } catch (error) { if (error.code === "stale_map_revision") handleStoryReaderError(error); } }, 180);
}

async function restoreStoryReaderView() {
  try {
    const response = await api.storyReaderViewState(state.storyReader.mapRevision); const saved = response.state;
    state.storyReader.hideNew = saved.hide_new; $("#storyHideNew").checked = saved.hide_new; $("#storyBrowser").classList.toggle("hide-new", saved.hide_new);
    const sectionId = state.storyReader.manifest.sections.some((section) => section.id === saved.section_id) ? saved.section_id : state.storyReader.manifest.sections[0]?.id;
    if (storyReaderGroupedTimeline()) {
      await loadStoryReaderTimeline(); state.storyReader.currentSectionId = sectionId || state.storyReader.currentSectionId;
      for (const button of $$("#storySectionIndex button")) button.setAttribute("aria-current", String(button.dataset.sectionId === state.storyReader.currentSectionId));
    } else if (sectionId) await loadStoryReaderSection(sectionId);
    if (saved.selection_id) await locateStoryReaderSelection(saved.selection_id);
    if (saved.focus_id && saved.focus_id !== saved.selection_id) await locateStoryReaderSelection(saved.focus_id, { activate: false });
    $("#storyBrowser").scrollTop = saved.viewport.scroll_top; state.storyReader.restored = true;
  } catch (error) {
    if (await handleStoryReaderError(error)) return;
    const first = state.storyReader.manifest.sections[0];
    if (storyReaderGroupedTimeline()) await loadStoryReaderTimeline(); else if (first) await loadStoryReaderSection(first.id);
    state.storyReader.restored = true;
  }
}

async function loadStoryReader() {
  if (!api.storyReaderRoutes) return false;
  try {
    state.storyReader.restored = false; const manifest = await api.storyReaderManifest(); renderStoryReaderManifest(manifest); await restoreStoryReaderView(); pollStoryReaderStatus(); return true;
  } catch (error) { if (!(await handleStoryReaderError(error))) toast(error.message); return false; }
}

function renderStoryMapV2(page) {
  invalidateStoryDetail();
  state.storyPage = page; state.storyItems = new Map(); state.storyRoutes = new Map(); state.storyRouteSelectionId = null; state.storyRouteInteractionUntil = 0; state.storySelectionId = null; state.storySelectionItem = null; state.storySelectionControl = null; state.storyPath = null; state.storyDetailDomIndex = 0;
  const storyBrowser = $("#storyBrowser"); const fallback = page.status === "fallback"; storyBrowser.classList.toggle("is-fallback", fallback);
  const progressive = (page.analysis_notes || []).some((note) => note.startsWith("Phase 05 progressive story walk"));
  const wholeGame = (page.analysis_notes || []).some((note) => note.startsWith("Phase 05 progressive story walk: whole-game reader"));
  storyBrowser.classList.remove("is-grouped-timeline");
  storyBrowser.classList.toggle("is-progressive-story", progressive);
  storyBrowser.classList.toggle("is-story-river", progressive);
  storyBrowser.classList.toggle("is-whole-game-story", wholeGame);
  $("#storyTitle").textContent = page.title;
  $("#storyOverview").textContent = page.overview;
  $("#storyMapStatus").textContent = wholeGame ? "Whole story" : progressive ? "Progressive proof" : page.status === "synthesized" ? "Whole-story guide" : "Deterministic story";
  const sections = $("#storySections"); sections.replaceChildren(); const eventOrdinal = { value: 0 };
  page.sections.forEach((section, sectionIndex) => {
    const id = `story-section-${sectionIndex + 1}`;
    const duplicateFallbackWrapper = (fallback || progressive) && page.sections.length === 1 && section.title.trim() === page.title.trim() && section.summary.trim() === page.overview.trim();
    const card = element("section", "story-section"); card.id = id;
    card.classList.toggle("story-section--duplicate-wrapper", duplicateFallbackWrapper);
    if (!duplicateFallbackWrapper) { const header = element("header", "story-section-header"); header.append(element("h2", "", section.title), element("p", "story-section-summary", section.summary)); card.append(header); }
    if (progressive && sectionIndex === 0) card.append(storySemanticLegend());
    const events = element("ol", "story-events");
    for (const event of section.events) events.append(renderStoryEvent(event, eventOrdinal));
    card.append(events); sections.append(card);
  });
  const notes = $("#storyAnalysisNotesList"); notes.replaceChildren();
  for (const note of page.analysis_notes || []) notes.append(element("p", "", note));
  $("#storyAnalysisNotes > summary").textContent = "Analysis notes";
  $("#storyAnalysisNotes").hidden = !notes.children.length;
  $("#storyPathPanel").hidden = true; clearStoryPathWitness();
  $("#storyRoutePanel").hidden = !progressive;
  showStorySurface(true);
  if (!progressive) setStoryWorkflowChrome({ prepare: Boolean(api.storyWorkflowRoutes) });
  buildStoryNavigation(page);
  resetStorySearch();
  if (progressive) {
    updateStoryRoutePanel(null, page.sections[0]?.events[0] || null);
    updateStoryReadingPosition();
  }
}

const STORY_CHAPTER_SPAN = 6;
const STORY_CHAPTER_MIN = 8;
const STORY_CHAPTER_MAX = 24;

function storyChapterTarget(count) {
  return Math.max(1, Math.min(STORY_CHAPTER_MAX, Math.max(STORY_CHAPTER_MIN, Math.round(count / STORY_CHAPTER_SPAN))));
}

function storyChapterCandidates(nodes) {
  const target = storyChapterTarget(nodes.length);
  if (nodes.length <= target) return nodes.map((node, index) => ({ node, index }));
  const stride = nodes.length / target;
  const picked = [];
  for (let slot = 0; slot < target; slot += 1) {
    // The first chapter is the story's own opening, not the tidiest title near it.
    if (slot === 0) { picked.push({ node: nodes[0], index: 0 }); continue; }
    const from = Math.round(slot * stride);
    const to = Math.min(nodes.length, Math.max(from + 1, Math.round((slot + 1) * stride)));
    let best = from;
    let bestScore = -1;
    for (let index = from; index < to; index += 1) {
      const title = storyNodeTitle(nodes[index]);
      const machine = /_|\d\s\d|^Routes:/u.test(title) ? 0 : 1;
      const score = machine * 100 + Math.min(60, title.length);
      if (score > bestScore) { bestScore = score; best = index; }
    }
    picked.push({ node: nodes[best], index: best });
  }
  return picked;
}

function storyNodeTitle(node) {
  return (node.querySelector(".story-event-select strong")?.textContent || "").replace(/\s+/gu, " ").trim();
}

const STORY_SMOOTH_SCROLL_LIMIT = 4000;

/** Jump instantly for long hops; a smooth animation over 40,000px reads as a hang. */
function scrollStoryTo(node) {
  const browser = $("#storyBrowser");
  const top = Math.max(0, browser.scrollTop + node.getBoundingClientRect().top - browser.getBoundingClientRect().top - 24);
  const far = Math.abs(top - browser.scrollTop) > STORY_SMOOTH_SCROLL_LIMIT;
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  browser.scrollTo({ top, behavior: far || reduced ? "auto" : "smooth" });
}

function buildStoryNavigation(page) {
  const nav = state.storyNav;
  const nodes = $$("#storySections .story-event");
  nav.eventNodes = nodes;
  nav.readingNodes = $$("#storySections [data-story-reading-node='true']");
  nav.activeChapterId = null;
  const index = $("#storySectionIndex"); index.replaceChildren();
  const chapters = storyChapterCandidates(nodes).map(({ node, index: position }) => ({
    id: node.id,
    ordinal: Number(node.dataset.storyOrdinal || position + 1),
    title: storyNodeTitle(node) || `Event ${position + 1}`,
    node,
  }));
  nav.chapters = chapters;
  for (const chapter of chapters) {
    const link = element("a", "story-chapter-link");
    link.href = `#${chapter.id}`;
    link.dataset.chapterId = chapter.id;
    link.append(element("span", "story-chapter-ordinal", String(chapter.ordinal).padStart(2, "0")), element("span", "story-chapter-title", chapter.title));
    link.addEventListener("click", (event) => {
      event.preventDefault();
      revealProgressiveStoryNode(chapter.node);
      scrollStoryTo(chapter.node);
      chapter.node.querySelector("button[data-story-selection-id]")?.focus({ preventScroll: true });
      markActiveChapter(chapter.id);
      updateStoryReadingPosition();
    });
    index.append(link);
  }
  $("#storyRail").hidden = !chapters.length;
  renderStoryRailStats(page, nodes.length);
  updateStoryReadingPosition();
}

function renderStoryRailStats(page, eventCount) {
  const host = $("#storyRailStats"); host.replaceChildren();
  const controls = $$("#storySections .story-choice").length;
  const endings = $$('#storySections .story-arm[data-outcome-kind="ending"]').length;
  const unresolved = $$('#storySections .story-arm[data-outcome-kind="unresolved"]').length;
  const rows = [["Events", eventCount], ["Branch points", controls], ["Endings", endings]];
  if (unresolved) rows.push(["Unresolved", unresolved]);
  for (const [label, value] of rows) {
    host.append(element("dt", "", label), element("dd", "", String(value)));
  }
}

function markActiveChapter(id) {
  const nav = state.storyNav;
  if (!id || nav.activeChapterId === id) return;
  if (!nav.chapters.some((entry) => entry.id === id)) return;
  nav.activeChapterId = id;
  for (const link of $$("#storySectionIndex .story-chapter-link")) {
    const active = link.dataset.chapterId === id;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "true");
    else link.removeAttribute("aria-current");
  }
}

function nearestChapterId(scrollTop) {
  const nav = state.storyNav;
  let current = nav.chapters[0]?.id || null;
  for (const chapter of nav.chapters) {
    if (chapter.node.hidden) continue;
    if (chapter.node.offsetTop - 120 <= scrollTop) current = chapter.id;
    else break;
  }
  return current;
}

function updateStoryReadingPosition() {
  const browser = $("#storyBrowser");
  const nav = state.storyNav;
  if (!nav.eventNodes.length) { $("#storyRailPosition").textContent = ""; return; }
  const span = Math.max(1, browser.scrollHeight - browser.clientHeight);
  const ratio = Math.max(0, Math.min(1, browser.scrollTop / span));
  $("#storyRailProgressBar").style.height = `${(ratio * 100).toFixed(2)}%`;
  const viewportTop = browser.scrollTop + browser.clientHeight * 0.3;
  let reached = 1;
  for (const node of nav.eventNodes) {
    if (node.hidden) continue;
    if (node.offsetTop <= viewportTop) reached = Number(node.dataset.storyOrdinal || reached);
    else break;
  }
  $("#storyRailPosition").textContent = `${reached} of ${nav.eventNodes.length}`;
  markActiveChapter(nearestChapterId(browser.scrollTop));
  const readingPoint = browser.scrollTop + browser.clientHeight * 0.42;
  let readingNode = null;
  const browserTop = browser.getBoundingClientRect().top;
  for (const node of nav.readingNodes) {
    if (node.hidden || !node.getClientRects().length) continue;
    const top = browser.scrollTop + node.getBoundingClientRect().top - browserTop;
    if (top <= readingPoint) readingNode = node;
    else break;
  }
  if (readingNode && Date.now() >= state.storyRouteInteractionUntil) syncStoryRoutePanelForNode(readingNode);
}

/** Time-throttled rather than rAF-driven: rAF is starved while the tab is not compositing. */
function scheduleStoryReadingPosition() {
  const nav = state.storyNav;
  if (nav.frame) return;
  nav.frame = setTimeout(() => { nav.frame = 0; updateStoryReadingPosition(); }, 60);
}

function storySearchHaystack(node) {
  if (node.dataset.searchText === undefined) {
    const ownStory = node.cloneNode(true);
    for (const nested of ownStory.querySelectorAll(".story-event")) nested.remove();
    node.dataset.searchText = (ownStory.textContent || "").replace(/\s+/gu, " ").toLocaleLowerCase();
  }
  return node.dataset.searchText;
}

function resetStorySearch() {
  const input = $("#storySearchInput");
  if (input.value) input.value = "";
  state.storyNav.query = "";
  applyStorySearch("");
}

function applyStorySearch(rawQuery) {
  const query = rawQuery.trim().toLocaleLowerCase();
  state.storyNav.query = query;
  const nodes = state.storyNav.eventNodes;
  const status = $("#storySearchStatus");
  $("#storySearchClear").hidden = !query;
  $("#storyBrowser").classList.toggle("is-searching", Boolean(query));
  if (!query) {
    for (const node of nodes) node.hidden = false;
    for (const section of $$("#storySections .story-section")) section.hidden = false;
    status.textContent = "";
    scheduleStoryReadingPosition();
    return;
  }
  let matches = 0;
  let firstMatch = null;
  for (const node of nodes) {
    const hit = storySearchHaystack(node).includes(query);
    node.hidden = !hit;
    if (hit) {
      matches += 1;
      firstMatch ||= node;
      revealProgressiveStoryNode(node);
    }
  }
  for (const section of $$("#storySections .story-section")) {
    section.hidden = !section.querySelector(".story-event:not([hidden])");
  }
  status.textContent = matches ? `${matches} of ${nodes.length} events match` : "No events match that search";
  if (firstMatch) {
    scrollStoryTo(firstMatch);
    const control = firstMatch.querySelector("button[data-story-selection-id]");
    if (control) syncStoryRoutePanelForNode(control, state.storyItems.get(control.dataset.storySelectionId) || null, { hold: true });
  }
  scheduleStoryReadingPosition();
}

function renderStoryWitnessList(groupSelector, listSelector, values, renderValue = (value) => value) {
  const group = $(groupSelector); const list = $(listSelector); list.replaceChildren();
  for (const value of values || []) list.append(element("li", "", renderValue(value)));
  group.hidden = !list.children.length;
}

function clearStoryPathWitness() {
  for (const [groupSelector, listSelector] of [
    ["#storyPathScenesGroup", "#storyPathScenes"],
    ["#storyPathChoicesGroup", "#storyPathChoices"],
    ["#storyPathRequirementsGroup", "#storyPathRequirements"],
    ["#storyPathEffectsGroup", "#storyPathEffects"],
  ]) renderStoryWitnessList(groupSelector, listSelector, []);
  $("#storyPathSteps").replaceChildren(); $(".story-path-more")?.remove(); $("#storyPathPanel").dataset.storyRecords = "0"; $("#storyPathWarnings").replaceChildren(); $("#storyPathUncertaintyGroup").hidden = true; $("#storyPathAnalysisNotes").open = false; $("#storyPathAnalysisNotes").hidden = true;
}

function renderStoryPath(path) {
  state.storyPath = path; const item = state.storySelectionItem || state.storyItems.get(state.storySelectionId);
  $("#storyPathTitle").textContent = storyItemTitle(item || {});
  $("#storyPathSummary").textContent = path.explanation || path.reason || (path.status === "available" ? "Known route to this moment." : "The complete route is not proven.");
  const instructions = path.witness?.instructions || [];
  renderStoryWitnessList("#storyPathScenesGroup", "#storyPathScenes", path.witness?.scene_titles);
  renderStoryWitnessList("#storyPathChoicesGroup", "#storyPathChoices", selectedStoryChoices(path.witness?.visible_choices, instructions));
  renderStoryWitnessList("#storyPathRequirementsGroup", "#storyPathRequirements", path.witness?.requirements, (requirement) => requirement.expression);
  renderStoryWitnessList("#storyPathEffectsGroup", "#storyPathEffects", path.witness?.effects);
  const steps = $("#storyPathSteps"); steps.replaceChildren();
  instructions.forEach((value) => {
    const step = element("li", "story-path-step");
    step.append(element("strong", "", String(value.kind).replaceAll("_", " ")), element("span", "", value.text));
    steps.append(step);
  });
  const warnings = $("#storyPathWarnings"); warnings.replaceChildren();
  for (const warning of path.witness?.uncertainty || []) warnings.append(element("p", "", warning));
  $("#storyPathUncertaintyGroup").hidden = !warnings.children.length;
  $("#storyPathAnalysisNotes").open = false; $("#storyPathAnalysisNotes").hidden = $("#storyPathScenesGroup").hidden && !steps.children.length;
  $("#storyDetailAction").disabled = false;
  $("#storyPathPanel").hidden = false;
}

function activateStoryItem(item, control) {
  invalidateStoryDetail();
  const selectionId = item.selection_id; state.storySelectionId = selectionId; state.storySelectionItem = item; state.storySelectionControl = control || null;
  state.storySelectionScrollY = $("#storyBrowser").scrollTop;
  state.storySelectionWindowY = window.scrollY;
  state.storySelectionViewportTop = control?.getBoundingClientRect().top || 0;
  for (const node of $$('button[data-story-current="true"]')) { delete node.dataset.storyCurrent; node.removeAttribute("aria-current"); }
  for (const node of $$(".story-event[data-story-current],.story-arm[data-story-current],.story-continuation[data-story-current]")) delete node.dataset.storyCurrent;
  if (control) {
    control.dataset.storyCurrent = "true";
    control.setAttribute("aria-current", "location");
    const location = control.closest(".story-event,.story-arm,.story-continuation");
    if (location) location.dataset.storyCurrent = "true";
    syncStoryRoutePanelForNode(control, item, { hold: true });
  }
}

async function selectStoryItem(item, control) {
  const selectionId = item.selection_id;
  activateStoryItem(item, control);
  clearStoryPathWitness(); $("#storyDetailAction").disabled = true; $("#storyPathPanel").hidden = false; $("#storyPathTitle").textContent = storyItemTitle(item); $("#storyPathSummary").textContent = "Finding the known path…";
  const token = ++state.storyPathToken;
  try {
    const path = await api.storyMapV2Path(selectionId);
    if (token === state.storyPathToken && selectionId === state.storySelectionId) renderStoryPath(path);
  } catch (error) {
    if (token === state.storyPathToken) renderStoryPath({ status: "unavailable", selection_id: selectionId, reason: error.message });
  }
}

function renderStoryDetail(envelope) {
  const detail = envelope.detail || {};
  const unresolved = envelope.status === "unresolved";
  const item = state.storySelectionItem || state.storyItems.get(state.storySelectionId) || {};
  $("#detailTitle").textContent = detail.title || detail.element?.title || detail.scene?.title || storyItemTitle(item);
  $("#detailKind").textContent = String(unresolved ? "unresolved detail" : detail.level || "story moment").replaceAll("_", " ");
  $("#detailSummary").textContent = envelope.reason || detail.detail_summary || detail.summary || detail.element?.detail_summary || detail.element?.summary || detail.scene?.detail_summary || detail.scene?.summary || storyDetailSummary(item) || "Exact local story evidence.";
  const evidence = $("#evidenceList"); evidence.replaceChildren();
  for (const record of detail.evidence || []) {
    const article = element("article", "evidence-record"); article.dataset.evidenceId = record.id || "story-evidence";
    article.append(element("pre", "", record.excerpt || record.text || "Evidence is available in the project.")); evidence.append(article);
  }
  const source = envelope.source_navigation;
  if (source?.status === "available" && (unresolved || !evidence.children.length)) evidence.append(element("p", "source-line", `${source.path}:${source.start_line}${source.end_line !== source.start_line ? `–${source.end_line}` : ""}`));
  else if (unresolved && source?.status === "unavailable") evidence.append(element("p", "source-line", source.reason));
  state.detail = envelope; showLevel("detail_evidence"); document.documentElement.dataset.activeLevel = "detail_evidence"; $("#backToRouteMap").focus();
}

async function openStoryDetail(selectionId) {
  if (selectionId !== state.storySelectionId) return;
  state.storySelectionScrollY = $("#storyBrowser").scrollTop;
  state.storySelectionWindowY = window.scrollY;
  const control = currentStorySelectionControl(selectionId);
  state.storySelectionViewportTop = control?.getBoundingClientRect().top || state.storySelectionViewportTop;
  const token = ++state.storyDetailToken;
  try {
    const detail = await api.storyMapV2Detail(selectionId);
    if (token !== state.storyDetailToken || selectionId !== state.storySelectionId) return;
    if (detail.status === "unavailable") { toast(detail.reason || "Detail and Evidence is unavailable"); return; }
    renderStoryDetail(detail);
  } catch (error) {
    if (token === state.storyDetailToken && selectionId === state.storySelectionId) toast(error.message);
  }
}

function closeStoryPath() {
  state.storyPathToken += 1;
  invalidateStoryDetail();
  $("#storyPathPanel").hidden = true; clearStoryPathWitness(); recordStoryProjection("path", 0);
  returnToStorySelection(false);
}

function invalidateStoryDetail() {
  state.storyDetailToken += 1;
}

function currentStorySelectionControl(selectionId = state.storySelectionId) {
  const control = state.storySelectionControl;
  if (control?.isConnected && control.dataset.storySelectionId === selectionId) return control;
  if (!selectionId) return null;
  return $(`button[data-story-selection-id="${CSS.escape(selectionId)}"]`);
}

function returnToStorySelection(scroll = true) {
  invalidateStoryDetail();
  if (!state.storyPage || !state.storySelectionId) return;
  showLevel("route_map"); showStorySurface(true);
  if (storyReaderActive()) { $("#detailView").dataset.storyRecords = "0"; $("#evidenceList").replaceChildren(); recordStoryProjection("detail", 0); }
  const control = currentStorySelectionControl();
  if (!control) return;
  const group = control.closest(".story-group-details"); if (group) group.open = true;
  if (scroll) control.scrollIntoView({ block: "center", inline: "nearest" });
  else {
    const browser = $("#storyBrowser");
    if (browser.scrollHeight > browser.clientHeight + 1) browser.scrollTop = state.storySelectionScrollY;
    else {
      control.scrollIntoView({ block: "start", inline: "nearest" });
      window.scrollBy(0, control.getBoundingClientRect().top - state.storySelectionViewportTop);
    }
  }
  control.focus({ preventScroll: true });
}

async function loadStoryMapV2() {
  if (!api.storyMapV2Routes?.map) return api.storyReaderRoutes ? loadStoryReader() : false;
  invalidateStoryDetail();
  try {
    const page = await api.storyMapV2();
    const progressive = page.status !== "unavailable" && (page.analysis_notes || []).some((note) => note.startsWith("Phase 05 progressive story walk"));
    if (progressive) { renderStoryMapV2(page); return true; }
    if (api.storyReaderRoutes) return loadStoryReader();
    if (page.status === "unavailable") { state.storyPage = null; state.storySelectionId = null; state.storySelectionItem = null; state.storySelectionControl = null; showStorySurface(false); return false; }
    renderStoryMapV2(page); return true;
  } catch (error) {
    if (api.storyReaderRoutes) return loadStoryReader();
    state.storyPage = null; state.storySelectionId = null; state.storySelectionItem = null; state.storySelectionControl = null; showStorySurface(false); toast(error.message); return false;
  }
}

async function enterAvailableWorkspace() {
  showPrimary("workspace"); showLevel("route_map");
  const storyAvailable = await loadStoryMapV2();
  if (storyAvailable) {
    $("#projectBadge").textContent = "Story";
    if (!progressiveStoryActive()) await restoreStoryWorkflow();
    return true;
  }
  showStoryUnavailable();
  return false;
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

  $("#backToRouteMap").addEventListener("click", () => { if (state.storyPage && state.storySelectionId) returnToStorySelection(false); else showLevel("route_map"); });
  $("#detailView").addEventListener("keydown", (event) => { if (event.key === "Escape") $("#backToRouteMap").click(); });
  $("#closeStoryPath").addEventListener("click", closeStoryPath);
  $("#returnToStorySelection").addEventListener("click", () => returnToStorySelection(true));
  $("#storyDetailAction").addEventListener("click", () => { if (state.storySelectionId) (storyReaderActive() ? openStoryReaderDetail(state.storySelectionId) : openStoryDetail(state.storySelectionId)); });
  $("#storyLoadMore").addEventListener("click", () => {
    const cursor = $("#storyLoadMore").dataset.cursor; if (!cursor || !state.storyReader.currentSectionId) return;
    $("#storyLoadMore").disabled = true; loadStoryReaderSection(state.storyReader.currentSectionId, { cursor, append: true });
  });

  $("#storySearchInput").addEventListener("input", () => {
    clearTimeout(bind.searchTimer);
    const query = $("#storySearchInput").value;
    bind.searchTimer = setTimeout(() => {
      if (progressiveStoryActive()) applyStorySearch(query);
      else searchStoryReader(query.trim());
    }, 140);
  });
  $("#storySearchClear").addEventListener("click", () => { $("#storySearchInput").value = ""; applyStorySearch(""); $("#storySearchInput").focus(); });
  $("#storyHideNew").addEventListener("change", (event) => {
    state.storyReader.hideNew = event.target.checked;
    $("#storyBrowser").classList.toggle("hide-new", state.storyReader.hideNew);
    scheduleStoryReaderViewSave();
  });
  $("#storyBrowser").addEventListener("scroll", () => { scheduleStoryReaderViewSave(); scheduleStoryReadingPosition(); }, { passive: true });

  $("#closeStoryApproval").addEventListener("click", () => $("#storyApprovalDialog").close());
  $("#storyPrepareAction").addEventListener("click", prepareStoryWorkflow);
  $("#storyRunDetails").addEventListener("toggle", loadPublishedStoryWorkflowDetails);
  $("#approveStoryGeneration").addEventListener("click", () => runStoryWorkflow("start"));
  $("#storyCancelRun").addEventListener("click", () => runStoryWorkflow("cancel"));
  $("#storyResumeRun").addEventListener("click", () => runStoryWorkflow("resume"));

  $("#diagnosticsButton").addEventListener("click", showDiagnostics);
  $("#closeDiagnostics").addEventListener("click", () => $("#diagnosticsDialog").close());
  $("#settingsButton").addEventListener("click", () => {
    const choices = ["system", "light", "dark"];
    state.settings.theme = choices[(choices.indexOf(state.settings.theme) + 1) % choices.length];
    document.documentElement.dataset.theme = state.settings.theme;
    api.saveSettings(state.settings).catch(() => {});
  });
  $("#quitButton").addEventListener("click", async () => { await api.shutdown(); document.body.replaceChildren(element("main", "shutdown-message", "Story Mapper has closed. You can close this tab.")); });

  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) { event.preventDefault(); $("#storySearchInput").focus(); }
  });
  window.addEventListener("resize", scheduleStoryReadingPosition, { passive: true });
}

async function start() {
  bind();
  try {
    const bootstrap = await api.bootstrap();
    api.configureM12(bootstrap.routes?.m12);
    api.configureStoryMapV2(bootstrap.routes?.story_map_v2);
    api.configureStoryWorkflow(bootstrap.routes?.story_map_v2_workflow);
    const readerContract = storyReaderContractFromBootstrap(bootstrap);
    if (readerContract) state.storyReader.contract = api.configureStoryReader(readerContract);
    state.settings = { ...state.settings, ...(bootstrap.settings || {}) };
    document.documentElement.dataset.theme = state.settings.theme;
    renderRecent(bootstrap.recent_projects || []);
    showPrimary("welcome");
  } catch (error) {
    renderRecent([]);
    toast(error.message);
  }
}

start();
export { api, state, element, loadStoryMapV2, renderStoryMapV2 };
