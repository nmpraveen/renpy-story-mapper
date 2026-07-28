import {
  presentFreshness,
  presentNew,
  staleRevisionFromResponse,
  validateReaderContract,
} from "/static/story-map-v2-diff.js";

const $ = (selector) => document.querySelector(selector);
const state = {
  ready: false,
  contract: null,
  manifest: null,
  mapRevision: null,
  sectionId: null,
  selectionId: null,
  focusId: null,
  hideNew: false,
  currentItems: [],
  currentPage: null,
  branchCursor: null,
  branchItems: 0,
  staleCount: 0,
  invalidCursorCount: 0,
  reopenCount: 0,
  searchCount: 0,
  branchLocateCount: 0,
  pathCount: 0,
  detailCount: 0,
  backCount: 0,
  refreshCount: 0,
  viewSaveCount: 0,
  crossSectionRejoin: null,
  apiNewFactCount: 0,
  overviewColdMs: null,
  overviewWarmMs: null,
  pathProgressVisible: false,
  uncachedPathMs: null,
  cachedPathMs: null,
  distantJumpCount: 0,
  distantJumpMs: null,
  apiTimings: {},
  errors: [],
};
window.harnessState = state;

class StaleMapRevision extends Error {}

async function jsonPost(route, body) {
  const started = performance.now();
  const response = await fetch(route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  (state.apiTimings[route] ||= []).push(performance.now() - started);
  const staleRevision = staleRevisionFromResponse(response.status, payload);
  if (staleRevision !== null) {
    state.mapRevision = staleRevision;
    state.staleCount += 1;
    throw new StaleMapRevision("stale map revision");
  }
  if (!response.ok) {
    const error = new Error(payload?.error?.code || `HTTP ${response.status}`);
    error.payload = payload;
    throw error;
  }
  if (route.startsWith("/api/v1/story-map-v2/") && payload.map_revision !== undefined) {
    if (!Number.isSafeInteger(payload.map_revision)) throw new TypeError("API response lacks map_revision");
    state.mapRevision = payload.map_revision;
  }
  return payload;
}

function route(key) {
  const value = state.contract.routes[key];
  if (!value) throw new TypeError(`Missing advertised route ${key}`);
  return value;
}

function setStatus(text, progress = null) {
  const status = $("#status");
  status.textContent = text;
  if (progress === null) delete status.dataset.progress;
  else status.dataset.progress = progress;
}

function renderFreshness() {
  const presentation = presentFreshness(state.manifest);
  const badge = $("#freshness");
  badge.textContent = presentation.label;
  badge.classList.toggle("badge--stale", presentation.is_stale);
  badge.dataset.freshness = presentation.key;
}

function marker(record) {
  const presentation = presentNew(record, { hideNew: state.hideNew });
  if (presentation.is_new) state.apiNewFactCount += presentation.facts.length;
  if (!presentation.visible) return null;
  const badge = document.createElement("span");
  badge.className = "badge badge--new";
  badge.textContent = presentation.label;
  badge.dataset.factIds = presentation.facts.map((fact) => fact.fact_id).join(",");
  return badge;
}

function button(label, action) {
  const value = document.createElement("button");
  value.type = "button";
  value.textContent = label;
  value.addEventListener("click", action);
  return value;
}

function renderItems(items, { branch = false } = {}) {
  state.currentItems = items;
  state.apiNewFactCount = 0;
  const root = $("#story");
  root.replaceChildren();
  for (const item of items) {
    const article = document.createElement("article");
    article.className = "story-node";
    article.dataset.selectionId = item.selection_id || item.id;
    article.dataset.kind = item.kind;
    article.dataset.selected = String(article.dataset.selectionId === state.selectionId);
    article.tabIndex = -1;
    const heading = document.createElement("h2");
    heading.textContent = item.title;
    article.append(heading);
    const newMarker = marker(item);
    if (newMarker) article.append(newMarker);
    if (item.summary) {
      const summary = document.createElement("p");
      summary.textContent = item.summary;
      article.append(summary);
    }
    const actions = document.createElement("div");
    actions.className = "node-actions";
    actions.append(button("Select", () => selectItem(article.dataset.selectionId)));
    if (!branch && item.kind === "choice") actions.append(button("Arms", () => openBranch(item.selection_id)));
    actions.append(button("Path", () => openPath(article.dataset.selectionId)));
    article.append(actions);
    root.append(article);
  }
  if (branch && state.branchCursor) root.append(button("Next branch page", nextBranchPage));
  enforceLiveBound();
}

function enforceLiveBound() {
  const count = document.querySelectorAll(".story-node").length;
  if (count > state.contract.limits.live_story_items) throw new RangeError("live story item bound exceeded");
  return count;
}

async function saveViewState() {
  await jsonPost(route("save_view_state"), {
    map_revision: state.mapRevision,
    view_key: "route-map",
    state: {
      section_id: state.sectionId,
      selection_id: state.selectionId,
      focus_id: state.focusId,
      viewport: { scroll_top: Math.round(window.scrollY), zoom: 1.0 },
      hide_new: state.hideNew,
    },
  });
  state.viewSaveCount += 1;
}

function selectItem(selectionId) {
  state.selectionId = selectionId;
  state.focusId = selectionId;
  for (const node of document.querySelectorAll(".story-node")) {
    node.dataset.selected = String(node.dataset.selectionId === selectionId);
  }
  void saveViewState();
}

async function loadManifest() {
  state.manifest = await jsonPost(route("manifest"), {});
  state.mapRevision = state.manifest.map_revision;
  $("#title").textContent = state.manifest.overview.title;
  renderFreshness();
  const index = $("#section-index");
  index.replaceChildren();
  for (const section of state.manifest.sections) {
    index.append(button(String(section.order + 1), () => loadSection(section.id)));
  }
}

async function loadSection(sectionId, { persist = true } = {}) {
  const page = await jsonPost(route("section_page"), {
    map_revision: state.mapRevision,
    section_id: sectionId,
    limit: state.contract.limits.events_per_section_page,
  });
  state.sectionId = sectionId;
  state.currentPage = page;
  state.branchCursor = null;
  renderItems(page.items);
  setStatus(`${sectionId} · ${page.rendered_item_count} items`);
  if (persist) await saveViewState();
  return page;
}

async function openBranch(choiceId, cursor = null) {
  const body = { map_revision: state.mapRevision, branch_id: choiceId, limit: 240 };
  if (cursor) body.cursor = cursor;
  const page = await jsonPost(route("branch_page"), body);
  state.currentPage = page;
  state.branchCursor = page.next_cursor;
  state.branchItems = page.items.length;
  state.selectionId = choiceId;
  renderItems(page.items, { branch: true });
  const rejoin = page.shells.find((shell) => shell.rejoin_selection_id);
  if (choiceId === "choice:19") state.crossSectionRejoin = rejoin?.rejoin_selection_id || null;
  setStatus(`${choiceId} · ${page.items.length} arms`);
  return page;
}

async function nextBranchPage() {
  if (!state.branchCursor) return;
  await openBranch("choice:0", state.branchCursor);
}

async function tamperCursor() {
  await openBranch("choice:0");
  try {
    await jsonPost(route("branch_page"), {
      map_revision: state.mapRevision,
      branch_id: "choice:0",
      limit: 240,
      cursor: `${state.branchCursor}x`,
    });
  } catch (error) {
    if (error.payload?.error?.code !== "invalid_cursor") throw error;
    state.invalidCursorCount += 1;
  }
}

async function searchFinal() {
  const result = await jsonPost(route("search"), {
    map_revision: state.mapRevision,
    query: "final target",
    limit: 50,
  });
  const target = result.results[0];
  const located = await jsonPost(route("locate"), {
    map_revision: state.mapRevision,
    selection_id: target.selection_id,
  });
  await loadSection(located.location.section_id);
  selectItem(target.selection_id);
  state.searchCount += 1;
  return target;
}

async function locateSelection(selectionId) {
  const located = await jsonPost(route("locate"), {
    map_revision: state.mapRevision,
    selection_id: selectionId,
  });
  const location = located.location;
  if (location.branch_id !== null) {
    await openBranch(location.branch_id, location.page_cursor);
    state.branchLocateCount += 1;
  } else {
    await loadSection(location.section_id);
  }
  selectItem(selectionId);
  return located;
}

function showPanel(title, items, backAction) {
  const panel = $("#side-panel");
  panel.replaceChildren();
  const heading = document.createElement("h2");
  heading.textContent = title;
  panel.append(heading, button("Back", backAction));
  for (const item of items) {
    const record = document.createElement("div");
    record.className = "story-node";
    record.dataset.kind = item.kind;
    const label = document.createElement("strong");
    label.textContent = item.title;
    record.append(label);
    if (item.text) {
      const text = document.createElement("p");
      text.textContent = item.text;
      record.append(text);
    }
    panel.append(record);
  }
  panel.hidden = false;
  enforceLiveBound();
}

async function openPath(selectionId) {
  const started = performance.now();
  state.pathProgressVisible = true;
  setStatus("Finding path…", "path");
  let page;
  try {
    page = await jsonPost(route("path_page"), {
      map_revision: state.mapRevision,
      selection_id: selectionId,
      limit: 240,
    });
  } finally {
    state.pathProgressVisible = false;
  }
  const elapsed = performance.now() - started;
  if (page.cache_state === "hit") state.cachedPathMs = elapsed;
  else state.uncachedPathMs = elapsed;
  state.selectionId = selectionId;
  state.pathCount += 1;
  showPanel("Path to this moment", page.items, closePanel);
  $("#side-panel").append(button("Detail", () => openDetail(selectionId)));
  setStatus(page.cache_state === "hit" ? "Path ready · cached" : "Path ready");
  return page;
}

async function openDetail(selectionId) {
  const page = await jsonPost(route("detail_page"), {
    map_revision: state.mapRevision,
    selection_id: selectionId,
    limit: 240,
  });
  state.detailCount += 1;
  showPanel("Detail / Evidence", page.items, closePanel);
  return page;
}

function closePanel() {
  $("#side-panel").hidden = true;
  $("#side-panel").replaceChildren();
  state.backCount += 1;
  const selected = document.querySelector(`[data-selection-id="${CSS.escape(state.selectionId)}"]`);
  selected?.focus();
}

async function refresh() {
  await jsonPost("/harness/refresh", {});
  state.refreshCount += 1;
  try {
    await loadSection(state.sectionId);
  } catch (error) {
    if (!(error instanceof StaleMapRevision)) throw error;
    await loadManifest();
    await loadSection(state.sectionId);
  }
}

async function reopen() {
  const started = performance.now();
  await loadManifest();
  const restored = await jsonPost(route("view_state"), {
    map_revision: state.mapRevision,
    view_key: "route-map",
  });
  state.hideNew = restored.state.hide_new;
  $("#hide-new").checked = state.hideNew;
  state.sectionId = restored.state.section_id;
  state.selectionId = restored.state.selection_id;
  state.focusId = restored.state.focus_id;
  await loadSection(state.sectionId);
  state.selectionId = restored.state.selection_id;
  selectItem(state.selectionId);
  state.overviewWarmMs = performance.now() - started;
  state.reopenCount += 1;
}

async function jumpDistantSections(count = 100) {
  const started = performance.now();
  for (let index = 0; index < count; index += 1) {
    const sectionIndex = (index * 97) % state.manifest.sections.length;
    await loadSection(`section:${sectionIndex}`, { persist: false });
  }
  await saveViewState();
  state.distantJumpCount += count;
  state.distantJumpMs = performance.now() - started;
  return state.distantJumpMs;
}

async function initialize() {
  state.contract = validateReaderContract(await (await fetch("/contract")).json());
  await loadManifest();
  const restored = await jsonPost(route("view_state"), { map_revision: state.mapRevision, view_key: "route-map" });
  state.hideNew = restored.state.hide_new;
  $("#hide-new").checked = state.hideNew;
  state.sectionId = restored.state.section_id;
  state.selectionId = restored.state.selection_id;
  state.focusId = restored.state.focus_id;
  await loadSection(state.sectionId);
  state.overviewColdMs = performance.now();
  state.ready = true;
}

$("#search-final").addEventListener("click", () => void searchFinal());
$("#oversized-branch").addEventListener("click", () => void openBranch("choice:0"));
$("#cross-rejoin").addEventListener("click", () => void openBranch("choice:19"));
$("#refresh").addEventListener("click", () => void refresh());
$("#reopen").addEventListener("click", () => void reopen());
$("#hide-new").addEventListener("change", async (event) => {
  state.hideNew = event.target.checked;
  renderItems(state.currentItems, { branch: state.currentPage?.resource_id?.startsWith("choice:") });
  await saveViewState();
});

window.phase04Harness = Object.freeze({
  loadSection,
  openBranch,
  nextBranchPage,
  tamperCursor,
  searchFinal,
  locateSelection,
  openPath,
  openDetail,
  closePanel,
  refresh,
  reopen,
  jumpDistantSections,
  liveStoryNodes: enforceLiveBound,
});

initialize().catch((error) => {
  state.errors.push(String(error?.stack || error));
  setStatus("Harness failed");
});
