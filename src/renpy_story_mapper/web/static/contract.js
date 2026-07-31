/** Packaged loopback API and rendering safety contract. */
export const API_VERSION = "v1";
export const ROUTE_PAGE_SIZE = 30;
export const ROUTE_EDGE_PAGE_SIZE = 180;
export const RENDER_LIMITS = Object.freeze({ nodes: 30, edges: 180, items: 240 });
export const STORY_MAP_V2_ROUTE_KEYS = Object.freeze(["map", "path", "detail"]);
export const STORY_READER_SCHEMA = "story-map-v2-reader-contract-v2";
export const STORY_READER_ROUTE_KEYS = Object.freeze([
  "manifest", "status", "section_page", "branch_page", "locate", "search",
  "path_page", "detail_page", "view_state", "save_view_state",
]);
export const STORY_READER_LIMIT_KEYS = Object.freeze([
  "events_per_section_page", "rendered_items_per_page", "serialized_bytes_per_page",
  "search_results_per_page", "live_story_items",
]);
export const STORY_WORKFLOW_CONTRACT = "story-map-v2-workflow-http-v2";
export const STORY_WORKFLOW_ROUTE_KEYS = Object.freeze([
  "prepare", "start", "cancel", "resume", "retry", "status",
]);

export const ENDPOINTS = Object.freeze({
  bootstrap: "/api/v1/bootstrap",
  nativePicker: "/api/v1/native-picker",
  projectsOpen: "/api/v1/projects/open",
  projectsCreate: "/api/v1/projects/create",
  projectsRefresh: "/api/v1/projects/refresh",
  analysisProgress: "/api/v1/analysis/progress",
  analysisCancel: "/api/v1/analysis/cancel",
  settings: "/api/v1/settings",
  diagnostics: "/api/v1/diagnostics",
  shutdown: "/api/v1/shutdown",
  routeMap: "/api/v1/m07/route-map",
  routeDetail: "/api/v1/m07/detail",
  boundedWindowResolve: "/api/v1/m07/bounded-window/resolve",
  organization: "/api/v1/m07/organization",
  organizationPrepare: "/api/v1/m07/organization/prepare",
  organizationStart: "/api/v1/m07/organization/start",
  organizationCancel: "/api/v1/m07/organization/cancel",
  assemblyApply: "/api/v1/m07/assembly/apply",
  assemblyDiscard: "/api/v1/m07/assembly/discard",
  aiStoryMap: "/api/v1/m08/ai-story-map",
  aiStoryDetail: "/api/v1/m08/ai-story-detail",
  mapComparison: "/api/v1/m08/comparison",
  inspectionMap: "/api/v1/m10/inspection-map",
  inspectionDetail: "/api/v1/m10/detail",
  sceneMap: "/api/v1/m11/scene-map",
  sceneDetail: "/api/v1/m11/detail",
  narrativeSnapshot: "/api/v1/m13/snapshot",
  narrativeArtifact: "/api/v1/m13/artifact",
  narrativeCitations: "/api/v1/m13/citations",
  narrativePrepare: "/api/v1/m13/prepare",
  narrativeStart: "/api/v1/m13/start",
  narrativeStatus: "/api/v1/m13/status",
  narrativeCancel: "/api/v1/m13/cancel",
});

const object = (value) => value && typeof value === "object" && !Array.isArray(value);
const WINDOW_KEYS = ["schema_version", "id", "selection_kind", "entry_node_id", "exit_node_id", "node_ids", "internal_edge_ids", "boundary_node_ids", "boundary_edge_ids", "evidence_ids", "fact_ids", "input_hash", "authority_hash"];
const EXPECTED_WINDOW_KEYS = ["id", "node_ids", "internal_edge_ids", "boundary_node_ids", "boundary_edge_ids", "evidence_ids", "fact_ids", "input_hash", "authority_hash"];
const PREPARED_KEYS = ["run_id", "scopes", "scope_ids", "window_ids", "windows", "selected_counts", "cached", "validated", "model", "budgets", "authority_hash", "selection_hash", "recovered_source_acknowledgement", "source_coverage", "requires_confirm_cloud"];
const SELECTED_COUNT_KEYS = ["work_units", "deterministic_scopes", "windows", "nodes", "internal_edges", "boundary_nodes", "boundary_edges", "evidence", "facts"];
export const ORGANIZATION_BUDGET_KEYS = Object.freeze(["soft_seconds", "hard_seconds", "soft_tokens", "hard_tokens", "hard_calls"]);
export const ORGANIZATION_MODEL = Object.freeze({ id: "gpt-5.6-luna", reasoning: "high", fast_mode: false });

function exactKeys(value, keys, label) {
  if (!object(value) || Object.keys(value).length !== keys.length || keys.some((key) => !Object.hasOwn(value, key))) throw new TypeError(`${label} has missing or extra fields`);
  return value;
}

function digest(value, label) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) throw new TypeError(`${label} is not an exact SHA-256 digest`);
  return value;
}

function uniqueStrings(value, label, maximum = 64) {
  if (!Array.isArray(value) || value.length > maximum || value.some((item) => typeof item !== "string" || !item || item.length > 512) || new Set(value).size !== value.length) throw new TypeError(`${label} is not a bounded unique string array`);
  return [...value];
}

function sameArray(left, right) { return left.length === right.length && left.every((item, index) => item === right[index]); }

function boundedText(value, label, maximum = 4096, { empty = false } = {}) {
  if (typeof value !== "string" || value.length > maximum || (!empty && (!value || value !== value.trim()))) throw new TypeError(`${label} is not bounded readable text`);
  return value;
}

function optionalText(value, label, maximum = 4096) {
  if (value === null) return null;
  return boundedText(value, label, maximum);
}

function readerRevision(value, label = "Story reader map revision") {
  if (!Number.isInteger(value) || value < 0) throw new TypeError(`${label} is invalid`);
  return value;
}

function readerCursor(value, label = "Story reader cursor") {
  if (value === null) return null;
  return boundedText(value, label, 4096);
}

function readerNewFacts(value, label = "Story reader NEW facts") {
  if (!Array.isArray(value) || value.length > 240) throw new TypeError(`${label} are not bounded`);
  for (const fact of value) {
    if (!object(fact)) throw new TypeError(`${label} contain an invalid fact`);
    boundedText(fact.kind, `${label} kind`, 80);
    boundedText(fact.fact_id, `${label} identity`, 512);
  }
  return value;
}

function storyReaderEnvelope(value, label) {
  if (!object(value) || value.schema !== STORY_READER_SCHEMA) throw new TypeError(`Invalid ${label}`);
  readerRevision(value.map_revision, `${label} map revision`);
  boundedText(value.generation_id, `${label} generation`, 512);
  return value;
}

export function assertStoryReaderContract(value) {
  exactKeys(value, ["schema", "routes", "limits", "examples"], "Story reader contract");
  if (value.schema !== STORY_READER_SCHEMA) throw new TypeError("Unsupported story reader contract");
  exactKeys(value.routes, STORY_READER_ROUTE_KEYS, "Story reader routes");
  exactKeys(value.limits, STORY_READER_LIMIT_KEYS, "Story reader limits");
  if (value.limits.events_per_section_page !== 30 || value.limits.rendered_items_per_page !== 240 || value.limits.serialized_bytes_per_page !== 1048576 || value.limits.live_story_items !== 600) throw new TypeError("Story reader safety limits drifted");
  if (!Number.isInteger(value.limits.search_results_per_page) || value.limits.search_results_per_page < 1 || value.limits.search_results_per_page > 100) throw new TypeError("Story reader search limit is invalid");
  return value;
}

export function assertStoryWorkflowRoutes(value) {
  if (!object(value)) throw new TypeError("Story workflow routes are invalid");
  exactKeys(value, ["contract", ...STORY_WORKFLOW_ROUTE_KEYS], "Story workflow routes");
  if (value.contract !== STORY_WORKFLOW_CONTRACT) throw new TypeError("Unsupported story workflow contract");
  for (const key of STORY_WORKFLOW_ROUTE_KEYS) boundedText(value[key], `Story workflow ${key} route`, 512);
  return value;
}

function storyWorkflowProvider(value, label, { nullable = false } = {}) {
  if (nullable && value === null) return;
  if (!object(value)) throw new TypeError(`${label} is invalid`);
  exactKeys(value, ["provider", "model", "reasoning", "fast_mode", "mode", "adapter_version"], label);
  for (const key of ["provider", "model", "mode", "adapter_version"]) boundedText(value[key], `${label} ${key}`, 512);
  if (value.reasoning !== null) boundedText(value.reasoning, `${label} reasoning`, 80);
  if (value.fast_mode !== null && typeof value.fast_mode !== "boolean") throw new TypeError(`${label} fast mode is invalid`);
}

function storyWorkflowDerivedProvider(value, label) {
  if (!object(value)) throw new TypeError(`${label} is invalid`);
  exactKeys(value, ["prompt_version", "schema_version", "provider", "model", "reasoning", "fast_mode", "mode", "adapter_version"], label);
  for (const key of ["prompt_version", "schema_version", "provider", "model", "mode", "adapter_version"]) boundedText(value[key], `${label} ${key}`, 512);
  if (value.reasoning !== null) boundedText(value.reasoning, `${label} reasoning`, 512);
  if (value.fast_mode !== null && typeof value.fast_mode !== "boolean") throw new TypeError(`${label} fast mode is invalid`);
}

export function assertStoryWorkflowResponse(value, expectedCommand = null) {
  if (!object(value)) throw new TypeError("Story workflow response is invalid");
  exactKeys(value, ["contract", "command", "preview", "approval", "status", "retry_approval"], "Story workflow response");
  if (value.contract !== STORY_WORKFLOW_CONTRACT || (expectedCommand !== null && value.command !== expectedCommand)) throw new TypeError("Story workflow response contract drifted");
  if (!STORY_WORKFLOW_ROUTE_KEYS.includes(value.command)) throw new TypeError("Story workflow command is invalid");
  const preview = value.preview;
  if (!object(preview)) throw new TypeError("Story workflow preview is invalid");
  for (const key of ["run_id", "preview_identity", "plan_id", "authority_identity"]) boundedText(preview[key], `Story workflow preview ${key}`, 1024);
  if (!Array.isArray(preview.jobs) || preview.jobs.length > 100000) throw new TypeError("Story workflow jobs are invalid");
  for (const job of preview.jobs) {
    exactKeys(job, ["job_id", "scope_id", "chunk_id", "critical"], "Story workflow job");
    for (const key of ["job_id", "scope_id", "chunk_id"]) boundedText(job[key], `Story workflow job ${key}`, 1024);
    if (typeof job.critical !== "boolean") throw new TypeError("Story workflow job critical state is invalid");
  }
  if (!object(preview.cache_hits) || !Array.isArray(preview.cache_hits.cloud_job_ids) || !Array.isArray(preview.cache_hits.loopback_job_ids)) throw new TypeError("Story workflow cache hits are invalid");
  if (!object(preview.policy)) throw new TypeError("Story workflow policy is invalid");
  storyWorkflowProvider(preview.policy.cloud, "Story workflow cloud provider", { nullable: true });
  storyWorkflowProvider(preview.policy.loopback, "Story workflow loopback provider", { nullable: true });
  if (preview.policy.cloud === null && (preview.policy.loopback === null || preview.policy.loopback.mode !== "loopback")) throw new TypeError("Story workflow local primary provider is invalid");
  storyWorkflowDerivedProvider(preview.policy.section_synthesis, "Story workflow section provider");
  storyWorkflowDerivedProvider(preview.policy.rollup_synthesis, "Story workflow rollup provider");
  const ceilingKeys = ["mapping_calls", "review_calls", "fallback_calls", "section_synthesis_calls", "route_reduction_calls", "route_summary_calls", "whole_game_reduction_calls", "final_overview_calls", "rollup_synthesis_calls", "input_tokens", "output_tokens", "elapsed_ms", "submission_slots", "indeterminate_retry_calls"];
  if (!object(preview.ceilings)) throw new TypeError("Story workflow ceilings are invalid");
  for (const key of ceilingKeys) if (!Number.isInteger(preview.ceilings[key]) || preview.ceilings[key] < 0) throw new TypeError(`Story workflow ${key} ceiling is invalid`);
  const privacyKeys = ["cloud_story_content", "loopback_story_content", "durable_raw_requests", "durable_raw_responses", "durable_provider_diagnostics", "durable_absolute_paths"];
  if (!object(preview.privacy)) throw new TypeError("Story workflow privacy disclosure is invalid");
  for (const key of privacyKeys) if (typeof preview.privacy[key] !== "boolean") throw new TypeError(`Story workflow privacy ${key} is invalid`);
  const status = value.status;
  if (!object(status) || status.run_id !== preview.run_id || status.preview_identity !== preview.preview_identity) throw new TypeError("Story workflow status identity drifted");
  for (const key of ["pending_jobs", "active_jobs", "accepted_jobs", "structural_fallback_jobs", "resumable_jobs", "indeterminate_jobs"]) if (!Number.isInteger(status[key]) || status[key] < 0) throw new TypeError(`Story workflow status ${key} is invalid`);
  for (const key of ["approved", "cancelled", "can_approve", "can_start", "can_cancel", "can_resume"]) if (typeof status[key] !== "boolean") throw new TypeError(`Story workflow status ${key} is invalid`);
  if (!Array.isArray(status.indeterminate_retries)) throw new TypeError("Story workflow retries are invalid");
  return value;
}

export function assertStoryReaderManifest(value) {
  storyReaderEnvelope(value, "Story reader manifest");
  for (const key of ["freshness", "status", "overview", "counts", "sections", "landmarks", "new_facts"]) if (!Object.hasOwn(value, key)) throw new TypeError(`Story reader manifest is missing ${key}`);
  if (!["current", "building", "stale", "phase03_compatible"].includes(value.freshness)) throw new TypeError("Story reader freshness is invalid");
  boundedText(value.status, "Story reader manifest status", 80);
  if (!object(value.overview)) throw new TypeError("Story reader overview is invalid");
  boundedText(value.overview.title, "Story reader title", 512);
  boundedText(value.overview.summary, "Story reader overview", 16384, { empty: true });
  if (!object(value.counts)) throw new TypeError("Story reader counts are invalid");
  for (const key of ["sections", "events", "choices", "arms", "endings"]) if (!Number.isInteger(value.counts[key]) || value.counts[key] < 0) throw new TypeError(`Story reader ${key} count is invalid`);
  if (!Array.isArray(value.sections) || value.sections.length > 2048) throw new TypeError("Story reader sections are not bounded");
  const sectionIds = new Set();
  for (const section of value.sections) {
    if (!object(section)) throw new TypeError("Story reader section descriptor is invalid");
    boundedText(section.id, "Story reader section ID", 512);
    if (sectionIds.has(section.id)) throw new TypeError("Story reader section IDs are duplicated");
    sectionIds.add(section.id);
    if (!Number.isInteger(section.order) || section.order < 0 || !Number.isInteger(section.event_count) || section.event_count < 0) throw new TypeError("Story reader section order/count is invalid");
    boundedText(section.title, "Story reader section title", 512);
    boundedText(section.summary, "Story reader section summary", 8192, { empty: true });
    if (section.route_id !== null) boundedText(section.route_id, "Story reader section route", 512);
    boundedText(section.status, "Story reader section status", 80);
    if (typeof section.is_new !== "boolean") throw new TypeError("Story reader section NEW state is invalid");
    readerNewFacts(section.new_facts, "Story reader section NEW facts");
  }
  if (!Array.isArray(value.landmarks) || value.landmarks.length > 4096) throw new TypeError("Story reader landmarks are not bounded");
  for (const landmark of value.landmarks) {
    if (!object(landmark)) throw new TypeError("Story reader landmark is invalid");
    for (const key of ["kind", "id", "section_id", "selection_id", "title"]) boundedText(landmark[key], `Story reader landmark ${key}`, key === "title" ? 512 : 1024);
  }
  if (!object(value.new_facts)) throw new TypeError("Story reader generation NEW state is invalid");
  if (value.new_facts.baseline_generation_id !== null) boundedText(value.new_facts.baseline_generation_id, "Story reader NEW baseline", 512);
  readerNewFacts(value.new_facts.facts, "Story reader generation NEW facts");
  return value;
}

export function assertStoryReaderStatus(value) {
  storyReaderEnvelope(value, "Story reader status");
  for (const key of ["run_id", "freshness", "state", "coverage", "progress", "actions", "current_complete_generation", "active_build_generation"]) if (!Object.hasOwn(value, key)) throw new TypeError(`Story reader status is missing ${key}`);
  boundedText(value.run_id, "Story reader run ID", 512);
  if (!["current", "building", "stale", "phase03_compatible"].includes(value.freshness)) throw new TypeError("Story reader status freshness is invalid");
  boundedText(value.state, "Story reader run state", 80);
  if (!object(value.coverage) || !object(value.progress) || !object(value.actions)) throw new TypeError("Story reader progress is invalid");
  for (const key of ["completed_chunks", "total_chunks"]) if (!Number.isInteger(value.coverage[key]) || value.coverage[key] < 0) throw new TypeError(`Story reader coverage ${key} is invalid`);
  if (typeof value.coverage.event_fraction !== "number" || value.coverage.event_fraction < 0 || value.coverage.event_fraction > 1) throw new TypeError("Story reader event coverage is invalid");
  for (const key of ["completed_jobs", "total_jobs", "failed_jobs", "indeterminate_jobs"]) if (!Number.isInteger(value.progress[key]) || value.progress[key] < 0) throw new TypeError(`Story reader progress ${key} is invalid`);
  for (const key of ["can_cancel", "can_resume", "retry_approval_required"]) if (typeof value.actions[key] !== "boolean") throw new TypeError(`Story reader action ${key} is invalid`);
  for (const key of ["current_complete_generation", "active_build_generation"]) if (value[key] !== null) boundedText(value[key], `Story reader ${key}`, 512);
  return value;
}

function assertStoryReaderItem(item) {
  if (!object(item)) throw new TypeError("Story reader item is invalid");
  boundedText(item.id, "Story reader item ID", 512);
  boundedText(item.kind, "Story reader item kind", 80);
  if (Object.hasOwn(item, "order") && (!Number.isInteger(item.order) || item.order < 0)) throw new TypeError("Story reader item order is invalid");
  for (const key of ["title", "summary", "text", "condition", "relative_path"]) if (Object.hasOwn(item, key) && item[key] !== null) boundedText(item[key], `Story reader item ${key}`, key === "summary" || key === "text" ? 16384 : 2048, { empty: key === "summary" || key === "text" });
  if (Object.hasOwn(item, "selection_id")) boundedText(item.selection_id, "Story reader selection", 512);
  if (Object.hasOwn(item, "effects")) readableStrings(item.effects, "Story reader effects", 240);
  if (Object.hasOwn(item, "is_new") && typeof item.is_new !== "boolean") throw new TypeError("Story reader item NEW state is invalid");
  if (Object.hasOwn(item, "new_facts")) readerNewFacts(item.new_facts, "Story reader item NEW facts");
  for (const key of ["start_line", "end_line"]) if (Object.hasOwn(item, key) && (!Number.isInteger(item[key]) || item[key] < 1)) throw new TypeError(`Story reader ${key} is invalid`);
  if (Object.hasOwn(item, "start_line") && Object.hasOwn(item, "end_line") && item.end_line < item.start_line) throw new TypeError("Story reader source span is reversed");
  return item;
}

export function assertStoryReaderPage(value, expectedRevision = null) {
  storyReaderEnvelope(value, "Story reader page");
  if (expectedRevision !== null && value.map_revision !== expectedRevision) throw new TypeError("Story reader page revision drifted");
  for (const key of ["resource_id", "items", "shells", "rendered_item_count", "next_cursor"]) if (!Object.hasOwn(value, key)) throw new TypeError(`Story reader page is missing ${key}`);
  boundedText(value.resource_id, "Story reader resource ID", 512);
  if (!Array.isArray(value.items) || value.items.length > 240 || !Array.isArray(value.shells) || value.shells.length > 240) throw new TypeError("Story reader page is not bounded");
  const itemIds = new Set();
  for (const item of value.items) { assertStoryReaderItem(item); if (itemIds.has(item.id)) throw new TypeError("Story reader item IDs are duplicated"); itemIds.add(item.id); }
  if (!Number.isInteger(value.rendered_item_count) || value.rendered_item_count < value.items.length || value.rendered_item_count > 240) throw new TypeError("Story reader rendered-item count is invalid");
  if (value.items.length && !value.shells.length) throw new TypeError("A nonempty story reader page needs a server-authored shell");
  const shellIds = new Set();
  for (const shell of value.shells) {
    if (!object(shell)) throw new TypeError("Story reader shell is invalid");
    for (const key of ["id", "kind"]) boundedText(shell[key], `Story reader shell ${key}`, 512);
    if (shellIds.has(shell.id)) throw new TypeError("Story reader shell IDs are duplicated");
    shellIds.add(shell.id);
    if (!Array.isArray(shell.item_ids) || !shell.item_ids.length || shell.item_ids.some((id) => !itemIds.has(id))) throw new TypeError("Story reader shell membership is invalid");
    for (const key of ["parent_shell_id", "route_id", "rejoin_selection_id"]) if (shell[key] !== null) boundedText(shell[key], `Story reader shell ${key}`, 512);
  }
  readerCursor(value.next_cursor);
  return value;
}

export function assertStoryReaderLocate(value, expectedRevision, selectionId) {
  storyReaderEnvelope(value, "Story reader locate response");
  if (value.map_revision !== expectedRevision || value.selection_id !== selectionId || !object(value.location)) throw new TypeError("Story reader locate response drifted");
  boundedText(value.selection_id, "Story reader located selection", 512);
  for (const key of ["section_id", "shell_id", "item_id"]) boundedText(value.location[key], `Story reader location ${key}`, 512);
  readerCursor(value.location.page_cursor, "Story reader location cursor");
  if (!Object.hasOwn(value.location, "branch_id")) throw new TypeError("Story reader location is missing its opaque branch resource");
  if (value.location.branch_id !== null) boundedText(value.location.branch_id, "Story reader location branch", 512);
  return value;
}

export function assertStoryReaderSearch(value, expectedRevision, query) {
  storyReaderEnvelope(value, "Story reader search response");
  if (value.map_revision !== expectedRevision || value.query !== query || !Array.isArray(value.results) || value.results.length > 100) throw new TypeError("Story reader search response drifted");
  for (const result of value.results) {
    if (!object(result)) throw new TypeError("Story reader search result is invalid");
    for (const key of ["selection_id", "kind", "title", "snippet", "section_id"]) boundedText(result[key], `Story reader search ${key}`, key === "snippet" ? 2048 : 512, { empty: key === "snippet" });
    if (typeof result.is_loaded !== "boolean") throw new TypeError("Story reader loaded-search state is invalid");
  }
  readerCursor(value.next_cursor, "Story reader search cursor");
  return value;
}

export function assertStoryReaderViewState(value, expectedRevision) {
  storyReaderEnvelope(value, "Story reader view state");
  if (value.map_revision !== expectedRevision || !object(value.state)) throw new TypeError("Story reader view state drifted");
  boundedText(value.view_key, "Story reader view key", 512);
  for (const key of ["section_id", "selection_id", "focus_id"]) if (value.state[key] !== null) boundedText(value.state[key], `Story reader state ${key}`, 512);
  if (!object(value.state.viewport) || typeof value.state.viewport.scroll_top !== "number" || value.state.viewport.scroll_top < 0 || typeof value.state.viewport.zoom !== "number" || value.state.viewport.zoom <= 0 || typeof value.state.hide_new !== "boolean") throw new TypeError("Story reader viewport state is invalid");
  return value;
}

export function assertStoryReaderStale(value) {
  exactKeys(value, ["error", "map_revision"], "Story reader stale response");
  exactKeys(value.error, ["code", "message"], "Story reader stale error");
  if (value.error.code !== "stale_map_revision") throw new TypeError("Story reader stale response code is invalid");
  boundedText(value.error.message, "Story reader stale response message", 2048);
  readerRevision(value.map_revision, "Story reader current map revision");
  return value;
}

function sourceBinding(value) {
  exactKeys(value, ["relative_path", "start_line", "end_line"], "Story Map V2 source binding");
  if (!object(value) || typeof value.relative_path !== "string" || !value.relative_path || value.relative_path.length > 1024 || !Number.isInteger(value.start_line) || !Number.isInteger(value.end_line) || value.start_line < 1 || value.end_line < value.start_line) throw new TypeError("Invalid Story Map V2 source binding");
  return value;
}

function navigationBinding(value, selectionId) {
  exactKeys(value, ["selection_id", "destination_kind", "target_id", "detail_kind", "detail_id", "source"], "Story Map V2 navigation binding");
  if (!object(value) || value.selection_id !== selectionId) throw new TypeError("Story Map V2 navigation binding drifted");
  for (const key of ["destination_kind", "target_id", "detail_kind", "detail_id"]) boundedText(value[key], `Story Map V2 ${key}`, 512);
  if (value.destination_kind !== "unresolved" && !M12_DESTINATION_KINDS.has(value.destination_kind)) throw new TypeError("Invalid Story Map V2 navigation destination");
  sourceBinding(value.source);
  return value;
}

const M12_DESTINATION_KINDS = new Set(["generic_scene", "exact_occurrence", "temporary_outcome", "persistent_lane", "terminal", "repeatable_event"]);

function rejoinBinding(value) {
  if (!object(value) || typeof value.selection_id !== "string" || !/^story-map-v2-continuation:[0-9a-f]{64}$/.test(value.selection_id)) throw new TypeError("Invalid Story Map V2 continuation selection");
  navigationBinding(value, value.selection_id);
  if (!M12_DESTINATION_KINDS.has(value.destination_kind) || value.destination_kind === "canonical_node" || value.detail_kind !== "story_map_v2_continuation" || value.detail_id !== value.selection_id) throw new TypeError("Invalid Story Map V2 continuation authority binding");
  return value;
}

function encodedNavigationBinding(value) {
  return JSON.stringify([
    value.selection_id, value.destination_kind, value.target_id, value.detail_kind, value.detail_id,
    value.source.relative_path, value.source.start_line, value.source.end_line,
  ]);
}

function readableStrings(value, label, maximum = 64) {
  if (!Array.isArray(value) || value.length > maximum) throw new TypeError(`${label} is not a bounded array`);
  value.forEach((item) => boundedText(item, label, 2048));
  return value;
}

function storyRouteFlowItem(item, seenSelections, eventDepth, budget, continuationBindings, referenceTargets) {
  if (!object(item) || !["event", "reference"].includes(item.kind)) throw new TypeError("Invalid Story Map V2 route-flow item");
  if (!["jump", "fallthrough", "call", "return", "unresolved"].includes(item.transfer_kind)) throw new TypeError("Invalid Story Map V2 route-flow transfer");
  if (item.kind === "event") {
    exactKeys(item, ["kind", "transfer_kind", "entry_kind", "event"], "Story Map V2 route-flow event");
    if (item.entry_kind !== "unique") throw new TypeError("Invalid Story Map V2 route-flow event entry");
    storyEvent(item.event, seenSelections, eventDepth + 1, budget, continuationBindings, referenceTargets);
    return item;
  }
  exactKeys(item, ["kind", "transfer_kind", "entry_kind", "target_selection_id", "title"], "Story Map V2 route-flow reference");
  if (!["loop", "unresolved"].includes(item.entry_kind)) throw new TypeError("Invalid Story Map V2 route-flow reference entry");
  boundedText(item.target_selection_id, "Story Map V2 route-flow reference target", 512);
  boundedText(item.title, "Story Map V2 route-flow reference title", 512);
  referenceTargets.add(item.target_selection_id);
  return item;
}

function storyChoice(value, seenSelections, depth = 0, rejoinSelections = new Map(), budget = { events: 0, choices: 0, arms: 0 }, continuationBindings = new Map(), referenceTargets = new Set(), eventDepth = 0) {
  const CHOICE_KEYS = ["key", "source", "arms"];
  const ARM_KEYS = ["selection_id", "caption", "outcome_summary", "condition", "effects", "destination_id", "rejoin_node_id", "rejoin_line", "reachability", "warnings", "binding", "rejoin_binding", "nested_choices"];
  const choiceKeys = [...CHOICE_KEYS];
  if (Object.hasOwn(value, "control_kind")) choiceKeys.push("control_kind");
  exactKeys(value, choiceKeys, "Story Map V2 choice");
  if (!object(value) || depth > 8) throw new TypeError("Invalid Story Map V2 choice nesting");
  budget.choices += 1;
  if (budget.choices > 512) throw new RangeError("Story Map V2 choice tree is too large");
  boundedText(value.key, "Story Map V2 choice key", 512);
  if (Object.hasOwn(value, "control_kind") && !["decision", "condition"].includes(value.control_kind)) throw new TypeError("Invalid Story Map V2 control kind");
  sourceBinding(value.source);
  if (!Array.isArray(value.arms) || !value.arms.length || value.arms.length > 32) throw new TypeError("Invalid Story Map V2 choice arms");
  budget.arms += value.arms.length;
  if (budget.arms > 4096) throw new RangeError("Story Map V2 arm tree is too large");
  value.arms.forEach((arm) => {
    const armKeys = [...ARM_KEYS];
    if (Object.hasOwn(arm, "outcome_kind")) armKeys.push("outcome_kind");
    if (Object.hasOwn(arm, "outline_summary")) armKeys.push("outline_summary");
    if (Object.hasOwn(arm, "detail_summary")) armKeys.push("detail_summary");
    if (Object.hasOwn(arm, "route_flow")) armKeys.push("route_flow");
    if (Object.hasOwn(arm, "state_provenance")) armKeys.push("state_provenance");
    if (Object.hasOwn(arm, "destination_target_selection_id")) armKeys.push("destination_target_selection_id");
    if (Object.hasOwn(arm, "rejoin_target_selection_id")) armKeys.push("rejoin_target_selection_id");
    exactKeys(arm, armKeys, "Story Map V2 arm");
    boundedText(arm.selection_id, "Story Map V2 arm selection", 512);
    if (seenSelections.has(arm.selection_id) || continuationBindings.has(arm.selection_id)) throw new TypeError("Duplicate Story Map V2 selection");
    seenSelections.add(arm.selection_id);
    boundedText(arm.caption, "Story Map V2 arm caption", 2048);
    if (Object.hasOwn(arm, "outcome_kind") && !["continues", "rejoins", "ends", "unresolved"].includes(arm.outcome_kind)) throw new TypeError("Invalid Story Map V2 outcome kind");
    boundedText(arm.outcome_summary, "Story Map V2 arm summary", 8192, { empty: true });
    if (Object.hasOwn(arm, "outline_summary")) boundedText(arm.outline_summary, "Story Map V2 arm outline", 8192, { empty: true });
    if (Object.hasOwn(arm, "detail_summary")) boundedText(arm.detail_summary, "Story Map V2 arm detail", 32768, { empty: true });
    optionalText(arm.condition, "Story Map V2 condition", 4096);
    readableStrings(arm.effects, "Story Map V2 effects");
    for (const key of ["destination_id", "rejoin_node_id"]) if (arm[key] !== null) boundedText(arm[key], `Story Map V2 ${key}`, 512);
    if (arm.rejoin_line !== null && (!Number.isInteger(arm.rejoin_line) || arm.rejoin_line < 1)) throw new TypeError("Invalid Story Map V2 rejoin line");
    if (!["reachable", "unreachable", "unresolved"].includes(arm.reachability)) throw new TypeError("Invalid Story Map V2 arm reachability");
    readableStrings(arm.warnings, "Story Map V2 arm warnings");
    navigationBinding(arm.binding, arm.selection_id);
    if (!Object.hasOwn(arm, "rejoin_binding")) throw new TypeError("Story Map V2 arm is missing rejoin_binding");
    if (arm.rejoin_binding !== null) {
      rejoinBinding(arm.rejoin_binding);
      const rejoinId = arm.rejoin_binding.selection_id;
      if (arm.rejoin_line !== null && (arm.rejoin_binding.source.start_line !== arm.rejoin_line || arm.rejoin_binding.source.end_line !== arm.rejoin_line)) throw new TypeError("Story Map V2 continuation source does not match the proven rejoin line");
      const encoded = encodedNavigationBinding(arm.rejoin_binding);
      if (seenSelections.has(rejoinId)) throw new TypeError("Duplicate Story Map V2 selection");
      if (rejoinSelections.has(rejoinId) && rejoinSelections.get(rejoinId) !== encoded) throw new TypeError("Story Map V2 rejoin binding drifted within a choice tree");
      if (continuationBindings.has(rejoinId) && continuationBindings.get(rejoinId) !== encoded) throw new TypeError("Story Map V2 rejoin binding drifted between choice trees");
      if (!rejoinSelections.has(rejoinId)) rejoinSelections.set(rejoinId, encoded);
      if (!continuationBindings.has(rejoinId)) continuationBindings.set(rejoinId, encoded);
    }
    if (!Array.isArray(arm.nested_choices) || arm.nested_choices.length > 16) throw new TypeError("Invalid nested Story Map V2 choices");
    arm.nested_choices.forEach((choice) => storyChoice(choice, seenSelections, depth + 1, rejoinSelections, budget, continuationBindings, referenceTargets, eventDepth));
    if (Object.hasOwn(arm, "route_flow")) {
      if (!Array.isArray(arm.route_flow) || arm.route_flow.length > 64) throw new TypeError("Invalid Story Map V2 arm route flow");
      arm.route_flow.forEach((item) => storyRouteFlowItem(item, seenSelections, eventDepth, budget, continuationBindings, referenceTargets));
    }
    for (const key of ["destination_target_selection_id", "rejoin_target_selection_id"]) {
      if (!Object.hasOwn(arm, key)) continue;
      boundedText(arm[key], `Story Map V2 ${key}`, 512);
      referenceTargets.add(arm[key]);
    }
    if (Object.hasOwn(arm, "state_provenance")) {
      if (!Array.isArray(arm.state_provenance) || arm.state_provenance.length > 64) throw new TypeError("Invalid Story Map V2 state provenance");
      for (const item of arm.state_provenance) {
        exactKeys(item, ["variable", "relationship_strength", "target_selection_id", "target_title", "source"], "Story Map V2 state provenance item");
        boundedText(item.variable, "Story Map V2 provenance variable", 256);
        if (!["exact", "possible", "unresolved"].includes(item.relationship_strength)) throw new TypeError("Invalid Story Map V2 provenance relationship");
        sourceBinding(item.source);
        if (item.relationship_strength === "unresolved") {
          if (item.target_selection_id !== null || item.target_title !== null) throw new TypeError("Unresolved Story Map V2 provenance has a target");
        } else {
          boundedText(item.target_selection_id, "Story Map V2 provenance target", 512);
          boundedText(item.target_title, "Story Map V2 provenance title", 512);
          referenceTargets.add(item.target_selection_id);
        }
      }
    }
  });
  return value;
}

function storyEvent(event, selections, eventDepth, budget, continuationBindings, referenceTargets) {
  if (!object(event) || eventDepth > 64) throw new TypeError("Invalid Story Map V2 event nesting");
  budget.events += 1;
  if (budget.events > 512) throw new RangeError("Story Map V2 event tree is too large");
  const eventKeys = ["selection_id", "title", "summary", "characters", "reachability", "warnings", "binding", "choices"];
  if (Object.hasOwn(event, "outline_summary")) eventKeys.push("outline_summary");
  if (Object.hasOwn(event, "detail_summary")) eventKeys.push("detail_summary");
  exactKeys(event, eventKeys, "Story Map V2 event");
  boundedText(event.selection_id, "Story Map V2 event selection", 512);
  if (selections.has(event.selection_id) || continuationBindings.has(event.selection_id)) throw new TypeError("Duplicate Story Map V2 selection");
  selections.add(event.selection_id);
  boundedText(event.title, "Story Map V2 event title", 512);
  boundedText(event.summary, "Story Map V2 event summary", 8192, { empty: true });
  if (Object.hasOwn(event, "outline_summary")) boundedText(event.outline_summary, "Story Map V2 event outline", 8192, { empty: true });
  if (Object.hasOwn(event, "detail_summary")) boundedText(event.detail_summary, "Story Map V2 event detail", 32768, { empty: true });
  readableStrings(event.characters, "Story Map V2 characters");
  readableStrings(event.warnings, "Story Map V2 event warnings");
  if (!["reachable", "unreachable", "unresolved"].includes(event.reachability)) throw new TypeError("Invalid Story Map V2 event reachability");
  navigationBinding(event.binding, event.selection_id);
  if (!Array.isArray(event.choices) || event.choices.length > 32) throw new TypeError("Invalid Story Map V2 event choices");
  event.choices.forEach((choice) => storyChoice(choice, selections, 0, new Map(), budget, continuationBindings, referenceTargets, eventDepth));
  return event;
}

export function assertStoryMapV2(value) {
  exactKeys(value, ["schema", "status", "reason", "title", "overview", "analysis_notes", "sections"], "Story Map V2 page");
  if (!object(value) || value.schema !== "story-map-v2-page-v1" || !["unavailable", "synthesized", "fallback"].includes(value.status)) throw new TypeError("Invalid Story Map V2 response");
  boundedText(value.title, "Story Map V2 title", 512);
  boundedText(value.overview, "Story Map V2 overview", 16384, { empty: true });
  if (value.reason !== null) boundedText(value.reason, "Story Map V2 reason", 2048);
  readableStrings(value.analysis_notes, "Story Map V2 analysis notes", 64);
  if (!Array.isArray(value.sections) || value.sections.length > 64) throw new TypeError("Story Map V2 sections are not bounded");
  if (value.status === "unavailable") {
    if (!value.reason || value.sections.length) throw new TypeError("Invalid unavailable Story Map V2 response");
    return value;
  }
  if (!value.sections.length) throw new TypeError("Available Story Map V2 is empty");
  const sectionIds = new Set(); const selections = new Set(); const continuationBindings = new Map(); const referenceTargets = new Set(); const treeBudget = { events: 0, choices: 0, arms: 0 };
  for (const section of value.sections) {
    exactKeys(section, ["id", "title", "summary", "events"], "Story Map V2 section");
    boundedText(section.id, "Story Map V2 section ID", 512);
    if (sectionIds.has(section.id)) throw new TypeError("Duplicate Story Map V2 section");
    sectionIds.add(section.id);
    boundedText(section.title, "Story Map V2 section title", 512);
    boundedText(section.summary, "Story Map V2 section summary", 8192, { empty: true });
    if (!Array.isArray(section.events) || !section.events.length || section.events.length > 512) throw new TypeError("Invalid Story Map V2 section events");
    for (const event of section.events) {
      storyEvent(event, selections, 0, treeBudget, continuationBindings, referenceTargets);
    }
  }
  for (const target of referenceTargets) if (!selections.has(target) && !continuationBindings.has(target)) throw new TypeError("Story Map V2 navigation target is missing");
  return value;
}

export function assertStoryMapV2Path(value, selectionId) {
  if (!object(value) || value.schema !== "story-map-v2-path-v1" || value.semantic_level !== "route_map" || value.selection_id !== selectionId) throw new TypeError("Invalid Story Map V2 path response");
  if (value.status === "unavailable") {
    exactKeys(value, ["schema", "semantic_level", "status", "selection_id", "reason"], "Unavailable Story Map V2 path");
    sizedString(value.reason, "Story Map V2 path reason", 1000, true);
    return value;
  }
  exactKeys(value, ["schema", "semantic_level", "status", "selection_id", "binding", "cached", "route_status", "complete", "explanation", "witness"], "Story Map V2 path");
  if (!["available", "unresolved"].includes(value.status) || typeof value.cached !== "boolean" || typeof value.complete !== "boolean" || (value.status === "unresolved" && value.complete)) throw new TypeError("Invalid Story Map V2 path state");
  if (value.route_status !== null) sizedString(value.route_status, "Story Map V2 route status", 80);
  sizedString(value.explanation, "Story Map V2 path explanation", 1000, value.status === "unresolved");
  navigationBinding(value.binding, selectionId);
  if (value.status === "available" && value.binding.destination_kind === "unresolved") throw new TypeError("Available Story Map V2 path has an unresolved binding");
  storyWitness(value.witness);
  return value;
}

export function assertStoryMapV2Detail(value, selectionId) {
  if (!object(value) || value.schema !== "story-map-v2-detail-v1" || value.semantic_level !== "detail_evidence" || value.selection_id !== selectionId) throw new TypeError("Invalid Story Map V2 detail response");
  if (value.status === "unavailable" && Object.hasOwn(value, "reason")) {
    exactKeys(value, ["schema", "semantic_level", "status", "selection_id", "reason"], "Unavailable Story Map V2 detail");
    sizedString(value.reason, "Story Map V2 detail reason", 1000, true);
    return value;
  }
  if (value.status === "unresolved") {
    exactKeys(value, ["schema", "semantic_level", "status", "selection_id", "binding", "source_navigation", "reason"], "Unresolved Story Map V2 detail");
    navigationBinding(value.binding, selectionId); storySourceNavigation(value.source_navigation);
    sizedString(value.reason, "Story Map V2 detail reason", 1000, true);
    return value;
  }
  exactKeys(value, ["schema", "semantic_level", "status", "selection_id", "binding", "source_navigation", "detail"], "Story Map V2 detail");
  if (value.status !== "available") throw new TypeError("Invalid Story Map V2 detail state");
  navigationBinding(value.binding, selectionId); storySourceNavigation(value.source_navigation);
  if (value.binding.destination_kind === "unresolved") throw new TypeError("Available Story Map V2 detail has an unresolved binding");
  assertStoryDetailPayload(value.detail);
  return value;
}

function sizedString(value, label, maximum, nonempty = false) {
  if (typeof value !== "string" || value.length > maximum || (nonempty && !value)) throw new TypeError(`${label} is not a bounded string`);
  return value;
}

function sizedStringArray(value, label, maximumItems, maximumChars) {
  if (!Array.isArray(value) || value.length > maximumItems) throw new TypeError(`${label} is not a bounded array`);
  value.forEach((item) => sizedString(item, label, maximumChars));
  return value;
}

function storyWitness(value) {
  exactKeys(value, ["scene_titles", "visible_choices", "requirements", "effects", "uncertainty", "instructions"], "Story Map V2 witness");
  sizedStringArray(value.scene_titles, "Story Map V2 scene title", 80, 160);
  sizedStringArray(value.visible_choices, "Story Map V2 visible choice", 80, 1000);
  sizedStringArray(value.effects, "Story Map V2 effect", 80, 1000);
  sizedStringArray(value.uncertainty, "Story Map V2 uncertainty", 40, 1000);
  if (!Array.isArray(value.requirements) || value.requirements.length > 80) throw new TypeError("Story Map V2 requirements are not bounded");
  value.requirements.forEach((requirement) => {
    exactKeys(requirement, ["expression", "source", "evidence_ids"], "Story Map V2 requirement");
    sizedString(requirement.expression, "Story Map V2 requirement expression", 1000);
    sizedString(requirement.source, "Story Map V2 requirement source", 80);
    sizedStringArray(requirement.evidence_ids, "Story Map V2 requirement evidence ID", 80, 160);
  });
  if (!Array.isArray(value.instructions) || value.instructions.length > 120) throw new TypeError("Story Map V2 instructions are not bounded");
  value.instructions.forEach((instruction) => {
    exactKeys(instruction, ["ordinal", "kind", "text"], "Story Map V2 instruction");
    if (!Number.isInteger(instruction.ordinal)) throw new TypeError("Story Map V2 instruction ordinal is not an integer");
    sizedString(instruction.kind, "Story Map V2 instruction kind", 80);
    sizedString(instruction.text, "Story Map V2 instruction text", 1000);
  });
  return value;
}

function storySourceNavigation(value) {
  if (!object(value) || !["available", "unavailable"].includes(value.status)) throw new TypeError("Invalid Story Map V2 source navigation");
  if (value.status === "unavailable") {
    exactKeys(value, ["status", "reason"], "Unavailable Story Map V2 source navigation");
    sizedString(value.reason, "Story Map V2 source reason", 1000, true); return value;
  }
  exactKeys(value, ["status", "path", "start_line", "end_line", "line_basis", "evidence_id"], "Story Map V2 source navigation");
  sizedString(value.path, "Story Map V2 source path", 1024);
  sizedString(value.line_basis, "Story Map V2 source line basis", 80);
  sizedString(value.evidence_id, "Story Map V2 source evidence ID", 512);
  if (!Number.isInteger(value.start_line) || !Number.isInteger(value.end_line) || value.start_line < 1 || value.end_line < value.start_line) throw new TypeError("Invalid Story Map V2 source lines");
  return value;
}

function assertStoryDetailPayload(value) {
  if (!object(value)) throw new TypeError("Invalid Story Map V2 detail payload");
  if (value.level === "scene_detail" || (value.status === "unavailable" && Object.hasOwn(value, "fallback"))) assertSceneDetail(value);
  else assertDetail(value);
  for (const candidate of [value.title, value.summary, value.reason, value.element?.title, value.element?.summary, value.scene?.title, value.scene?.summary]) {
    if (candidate !== undefined && candidate !== null) sizedString(candidate, "Story Map V2 rendered detail text", 16384);
  }
  if (!Array.isArray(value.evidence) || value.evidence.length > 60) throw new TypeError("Story Map V2 detail evidence is not bounded");
  value.evidence.forEach((record) => {
    if (!object(record)) throw new TypeError("Invalid Story Map V2 detail evidence");
    for (const candidate of [record.id, record.excerpt, record.text]) if (candidate !== undefined && candidate !== null) sizedString(candidate, "Story Map V2 rendered evidence text", 16384);
  });
  return value;
}

export function exactOrganizationBudgets(value) {
  exactKeys(value, ORGANIZATION_BUDGET_KEYS, "Organization budgets");
  const result = Object.fromEntries(ORGANIZATION_BUDGET_KEYS.map((key) => {
    if (!Number.isInteger(value[key]) || value[key] <= 0) throw new TypeError("Organization budgets must be finite positive integers");
    return [key, value[key]];
  }));
  if (result.soft_seconds > result.hard_seconds || result.soft_tokens > result.hard_tokens) throw new TypeError("Organization soft budgets exceed hard budgets");
  return result;
}

export function exactOrganizationModel(value) {
  exactKeys(value, Object.keys(ORGANIZATION_MODEL), "Organization model");
  if (Object.keys(ORGANIZATION_MODEL).some((key) => value[key] !== ORGANIZATION_MODEL[key])) throw new TypeError("Organization model identity is not Luna/High/fast-off");
  return { ...ORGANIZATION_MODEL };
}

function exactExpectedWindow(value, window) {
  exactKeys(value, EXPECTED_WINDOW_KEYS, "Bounded-window expectation");
  for (const key of EXPECTED_WINDOW_KEYS) {
    if (key.endsWith("_ids")) {
      const ids = uniqueStrings(value[key], `Expected ${key}`, key === "evidence_ids" ? 2048 : key === "fact_ids" ? 1024 : 256);
      if (!sameArray(ids, window[key])) throw new TypeError(`Bounded-window expectation drifted at ${key}`);
    } else if (value[key] !== window[key]) throw new TypeError(`Bounded-window expectation drifted at ${key}`);
  }
  return value;
}

export function assertBoundedWindow(value) {
  exactKeys(value, WINDOW_KEYS, "Bounded narrative window");
  if (value.schema_version !== 1 || typeof value.id !== "string" || !value.id.startsWith("bounded_window_")) throw new TypeError("Invalid bounded-window identity");
  if (!['node_ids', 'anchors'].includes(value.selection_kind)) throw new TypeError("Invalid bounded-window selection kind");
  const arrays = {
    node_ids: 64, internal_edge_ids: 256, boundary_node_ids: 256,
    boundary_edge_ids: 256, evidence_ids: 2048, fact_ids: 1024,
  };
  for (const [key, maximum] of Object.entries(arrays)) uniqueStrings(value[key], `Window ${key}`, maximum);
  if (!value.node_ids.length) throw new TypeError("Bounded narrative window is empty");
  if (value.selection_kind === "anchors") {
    if (typeof value.entry_node_id !== "string" || !value.entry_node_id || typeof value.exit_node_id !== "string" || !value.exit_node_id) throw new TypeError("Bounded-window anchors are incomplete");
  } else if (value.entry_node_id !== null || value.exit_node_id !== null) throw new TypeError("Explicit bounded-window selection has unexpected anchors");
  digest(value.input_hash, "Window input_hash"); digest(value.authority_hash, "Window authority_hash");
  return value;
}

export function assertWindowSelectionRequest(value, windowValue) {
  const window = assertBoundedWindow(windowValue);
  const selectorKeys = window.selection_kind === "anchors" ? ["entry_node_id", "exit_node_id", "expected"] : ["node_ids", "expected"];
  exactKeys(value, selectorKeys, "Bounded-window selection request");
  if (window.selection_kind === "anchors") {
    if (value.entry_node_id !== window.entry_node_id || value.exit_node_id !== window.exit_node_id) throw new TypeError("Bounded-window anchors were tampered");
  } else if (!sameArray(uniqueStrings(value.node_ids, "Selection node_ids"), window.node_ids)) throw new TypeError("Bounded-window node_ids were tampered");
  exactExpectedWindow(value.expected, window);
  return value;
}

export function assertBoundedWindowResolution(value) {
  exactKeys(value, ["window", "selection_request"], "Bounded-window resolution");
  assertWindowSelectionRequest(value.selection_request, value.window);
  return value;
}

function exactSelectedCounts(value, scopeCount, windowCount) {
  exactKeys(value, SELECTED_COUNT_KEYS, "Selected counts");
  if (SELECTED_COUNT_KEYS.some((key) => !Number.isInteger(value[key]) || value[key] < 0)) throw new TypeError("Selected counts must be finite non-negative integers");
  if (value.work_units !== scopeCount + windowCount || value.deterministic_scopes !== scopeCount || value.windows !== windowCount) throw new TypeError("Selected counts do not match the prepared work units");
  return value;
}

export function assertPreparedOrganization(value) {
  exactKeys(value, PREPARED_KEYS, "Prepared organization");
  if (typeof value.run_id !== "string" || !value.run_id.startsWith("m07_") || value.requires_confirm_cloud !== true) throw new TypeError("Prepared organization consent is invalid");
  const scopeIds = uniqueStrings(value.scope_ids, "Prepared scope_ids");
  const windowIds = uniqueStrings(value.window_ids, "Prepared window_ids");
  if (!scopeIds.length && !windowIds.length) throw new TypeError("Prepared organization selection is empty");
  if (scopeIds.length + windowIds.length > 64 || scopeIds.some((id) => windowIds.includes(id))) throw new TypeError("Prepared organization selection is invalid");
  if (!Number.isInteger(value.scopes) || value.scopes !== scopeIds.length + windowIds.length) throw new TypeError("Prepared organization scope count is inexact");
  if (!Array.isArray(value.windows) || value.windows.length !== windowIds.length) throw new TypeError("Prepared bounded windows are inexact");
  value.windows.forEach((window, index) => { assertBoundedWindow(window); if (window.id !== windowIds[index]) throw new TypeError("Prepared window_ids were tampered"); });
  exactSelectedCounts(value.selected_counts, scopeIds.length, windowIds.length);
  if (![value.cached, value.validated].every((count) => Number.isInteger(count) && count >= 0 && count <= value.scopes)) throw new TypeError("Prepared checkpoint counts are invalid");
  exactOrganizationModel(value.model); exactOrganizationBudgets(value.budgets);
  digest(value.authority_hash, "Prepared authority_hash"); digest(value.selection_hash, "Prepared selection_hash"); digest(value.recovered_source_acknowledgement, "Prepared recovered-source acknowledgement");
  if (!object(value.source_coverage)) throw new TypeError("Prepared source coverage is unavailable");
  return value;
}

export function assertRoutePage(page) {
  if (object(page) && page.status === "unavailable") {
    if (!["simplified", "canonical"].includes(page.view) || typeof page.reason !== "string" || !object(page.generation_status)) throw new TypeError("Invalid unavailable Route Map response");
    return page;
  }
  if (!object(page) || !Array.isArray(page.nodes) || !Array.isArray(page.edges)) {
    throw new TypeError("Invalid Route Map response");
  }
  const nodes = page.nodes.length;
  const edges = page.edges.length;
  if (nodes > RENDER_LIMITS.nodes || edges > RENDER_LIMITS.edges || nodes + edges > RENDER_LIMITS.items) {
    throw new RangeError("Route Map exceeds the packaged rendering boundary");
  }
  for (const key of ["edge_offset", "edge_limit", "page_edge_total"]) {
    if (!Number.isInteger(page[key]) || page[key] < 0) throw new TypeError(`Invalid Route Map ${key}`);
  }
  if (page.edge_next_offset !== null && (!Number.isInteger(page.edge_next_offset) || page.edge_next_offset < 0)) {
    throw new TypeError("Invalid Route Map edge_next_offset");
  }
  if (edges > page.edge_limit || page.edge_limit > RENDER_LIMITS.edges) {
    throw new RangeError("Route Map edge slice exceeds the packaged rendering boundary");
  }
  if (page.level && page.level !== "route_map") throw new TypeError("Unexpected semantic level");
  return page;
}

export function assertDetail(detail) {
  if (object(detail) && detail.status === "unavailable") {
    if (!["simplified", "canonical"].includes(detail.view) || typeof detail.reason !== "string" || !object(detail.generation_status)) throw new TypeError("Invalid unavailable detail response");
    return detail;
  }
  if (!object(detail) || !object(detail.element) || !Array.isArray(detail.evidence)) {
    throw new TypeError("Invalid Detail/Evidence response");
  }
  if (detail.level && detail.level !== "detail_evidence") throw new TypeError("Unexpected semantic level");
  return detail;
}

function membershipReferenceCount(value) {
  if (Array.isArray(value)) return value.reduce((total, item) => total + membershipReferenceCount(item), 0);
  if (!object(value)) return 0;
  return Object.entries(value).reduce((total, [key, item]) => total + (key.endsWith("_ids") && Array.isArray(item) && item.every((reference) => typeof reference === "string") ? item.length : membershipReferenceCount(item)), 0);
}

export function assertSceneMap(value) {
  if (!object(value) || !["available", "unavailable"].includes(value.status)) throw new TypeError("Invalid M11 Scene Map response");
  digest(value.canonical_hash, "M11 Scene Map canonical_hash");
  if (value.status === "unavailable") {
    if (typeof value.reason !== "string" || !object(value.fallback) || value.fallback.view !== "simplified") throw new TypeError("M11 Scene Map fallback is unavailable");
    return value;
  }
  if (value.level !== "scene_map" || !Array.isArray(value.nodes) || !Array.isArray(value.relationships) || !Array.isArray(value.chapter_bands) || !Array.isArray(value.lanes)) throw new TypeError("M11 Scene Map page is incomplete");
  if (value.nodes.length > RENDER_LIMITS.nodes || value.relationships.length > RENDER_LIMITS.edges) throw new RangeError("M11 Scene Map exceeds the packaged rendering boundary");
  digest(value.scene_model_hash, "M11 Scene Map model hash");
  for (const key of ["offset", "limit", "relationship_offset", "relationship_limit", "page_relationship_total", "total_nodes", "total_relationships"]) {
    if (!Number.isInteger(value[key]) || value[key] < 0) throw new TypeError(`Invalid M11 Scene Map ${key}`);
  }
  if (value.limit < 1 || value.limit > RENDER_LIMITS.nodes || value.relationship_limit < 1 || value.relationship_limit > RENDER_LIMITS.edges || value.nodes.length > value.limit || value.relationships.length > value.relationship_limit) throw new RangeError("M11 Scene Map slice is inconsistent");
  if (value.membership_reference_limit !== 240 || !Number.isInteger(value.membership_reference_count) || value.membership_reference_count < 0 || value.membership_reference_count > value.membership_reference_limit) throw new RangeError("M11 Scene Map membership references are unbounded");
  if (membershipReferenceCount([value.nodes, value.chapter_bands, value.lanes]) !== value.membership_reference_count) throw new TypeError("M11 Scene Map membership reference count is inexact");
  for (const key of ["next_offset", "relationship_next_offset"]) {
    if (value[key] !== null && (!Number.isInteger(value[key]) || value[key] < 0)) throw new TypeError(`Invalid M11 Scene Map ${key}`);
  }
  const nodeIds = new Set(value.nodes.map((node) => node.id));
  if (value.relationships.some((relationship) => !nodeIds.has(relationship.source_id) && !nodeIds.has(relationship.target_id))) throw new TypeError("M11 Scene Map returned an unrelated relationship");
  return value;
}

export function assertSceneDetail(value) {
  if (value?.status === "unavailable") return assertSceneMap(value);
  if (!object(value) || value.level !== "scene_detail" || value.status !== "available" || !Array.isArray(value.atoms) || !Array.isArray(value.temporary_branches) || !Array.isArray(value.arm_local_scenes) || !Array.isArray(value.call_occurrences) || !Array.isArray(value.loop_hubs) || !Array.isArray(value.related_scenes) || !Array.isArray(value.canonical_escape_ids) || !Array.isArray(value.canonical_records) || !Array.isArray(value.evidence)) throw new TypeError("Invalid M11 Scene Detail response");
  digest(value.canonical_hash, "M11 Scene Detail canonical_hash");
  for (const records of [value.atoms, value.temporary_branches, value.arm_local_scenes, value.call_occurrences, value.loop_hubs, value.canonical_escape_ids, value.canonical_records, value.evidence]) {
    if (records.length > 60) throw new RangeError("M11 Scene Detail exceeds its bounded response limits");
  }
  if (value.related_scenes.length > 60 || value.membership_reference_limit !== 60 || !Number.isInteger(value.membership_reference_count) || value.membership_reference_count < 0 || value.membership_reference_count > value.membership_reference_limit) throw new RangeError("M11 Scene Detail membership references are unbounded");
  const membershipRoots = [value.scene, value.temporary_branch, value.selected_occurrence, value.lane, value.chapter, value.boundary, value.atoms, value.temporary_branches, value.arm_local_scenes, value.call_occurrences, value.loop_hubs, value.related_scenes];
  if (membershipReferenceCount(membershipRoots) !== value.membership_reference_count) throw new TypeError("M11 Scene Detail membership reference count is inexact");
  if (value.canonical_record_reference_limit !== 60 || !Number.isInteger(value.canonical_record_reference_count) || value.canonical_record_reference_count < 0 || value.canonical_record_reference_count > value.canonical_record_reference_limit) throw new RangeError("M11 Scene Detail canonical record references are unbounded");
  if (membershipReferenceCount([value.canonical_records, value.evidence]) !== value.canonical_record_reference_count) throw new TypeError("M11 Scene Detail canonical record reference count is inexact");
  return value;
}

export function assertNarrativeSnapshot(value) {
  if (!object(value) || !["available", "unavailable"].includes(value.status) || value.schema !== "m13-narrative-snapshot-v1" || value.cloud_enabled !== false || !Array.isArray(value.jobs) || value.jobs.length > 200) throw new TypeError("Invalid M13 Narrative snapshot");
  if (!Number.isInteger(value.offset) || value.offset < 0 || !Number.isInteger(value.limit) || value.limit < 1 || value.limit > 200 || !Number.isInteger(value.total) || value.total < value.jobs.length) throw new TypeError("Invalid M13 Narrative job window");
  if (value.next_offset !== null && (!Number.isInteger(value.next_offset) || value.next_offset <= value.offset)) throw new TypeError("Invalid M13 Narrative next offset");
  if (value.status === "unavailable") {
    if (typeof value.reason !== "string" || value.jobs.length || value.total !== 0) throw new TypeError("Invalid unavailable M13 Narrative snapshot");
    return value;
  }
  digest(value.authority_hash, "M13 Narrative authority_hash");
  if (!object(value.coverage) || !object(value.state_counts)) throw new TypeError("M13 Narrative coverage is unavailable");
  for (const job of value.jobs) {
    if (!object(job) || typeof job.job_id !== "string" || typeof job.kind !== "string" || typeof job.owner_id !== "string" || typeof job.state !== "string" || (job.artifact !== null && !object(job.artifact))) throw new TypeError("Invalid M13 Narrative job");
    if (job.artifact && (typeof job.artifact.artifact_id !== "string" || typeof job.artifact.title !== "string" || typeof job.artifact.summary !== "string" || !object(job.artifact.coverage) || !Array.isArray(job.artifact.warnings))) throw new TypeError("Invalid M13 Narrative artifact summary");
  }
  return value;
}

export function assertNarrativeArtifact(value) {
  if (!object(value) || value.schema !== "m13-narrative-artifact-detail-v1" || value.status !== "available" || typeof value.artifact_id !== "string" || typeof value.logical_job_id !== "string" || typeof value.kind !== "string" || typeof value.publication !== "string" || typeof value.title !== "string" || !["interpretive", "deterministic_fallback"].includes(value.title_class) || typeof value.summary !== "string" || value.summary_class !== "interpretive" || !Array.isArray(value.claims) || value.claims.length > 256 || !object(value.coverage) || !Array.isArray(value.warnings)) throw new TypeError("Invalid M13 Narrative artifact detail");
  digest(value.authority_hash, "M13 Narrative artifact authority_hash");
  for (const claim of value.claims) if (!object(claim) || typeof claim.claim_id !== "string" || !["factual", "interpretive", "review_suggestion"].includes(claim.claim_class) || !["atomic", "ordered_summary", "comparison"].includes(claim.context_scope) || typeof claim.text !== "string" || !["direct_evidence", "child_claims"].includes(claim.support_kind)) throw new TypeError("Invalid M13 Narrative claim");
  return value;
}

export function assertNarrativeCitations(value) {
  if (!object(value) || value.schema !== "m13-narrative-claim-navigation-v1" || value.status !== "available" || typeof value.claim_id !== "string" || !Array.isArray(value.traversed_claim_ids) || value.traversed_claim_ids.length > 256 || !Array.isArray(value.claim_path) || value.claim_path.length > 256 || !Number.isInteger(value.maximum_depth) || value.maximum_depth < 0 || !Number.isInteger(value.citation_count) || value.citation_count < 0 || !Array.isArray(value.authority_labels) || value.authority_labels.length > 60 || !Array.isArray(value.citations) || value.citations.length > 60 || value.citation_count !== value.citations.length) throw new TypeError("Invalid M13 Narrative citations");
  digest(value.authority_hash, "M13 Narrative citation authority_hash");
  for (const citation of value.citations) {
    if (!object(citation) || !["m10", "m11", "m12"].includes(citation.authority) || typeof citation.record_kind !== "string" || typeof citation.record_id !== "string" || typeof citation.owner_id !== "string" || typeof citation.label !== "string" || !Array.isArray(citation.claim_path) || citation.claim_path.length < 1 || citation.claim_path.length > 256 || !object(citation.navigation) || !["canonical", "scenes", "m12_result"].includes(citation.navigation.mode) || typeof citation.navigation.element_id !== "string" || typeof citation.navigation.focus_record_id !== "string" || Object.hasOwn(citation, "record")) throw new TypeError("Invalid M13 Narrative citation");
    if (citation.navigation.mode === "m12_result" && (typeof citation.navigation.request_identity !== "string" || citation.navigation.request_identity !== citation.record_id)) throw new TypeError("Invalid M13 route-result citation navigation");
  }
  return value;
}

export function assertNarrativePreparation(value) {
  if (!object(value) || value.schema !== "m13-run-preparation-v1" || typeof value.preparation_id !== "string" || !value.preparation_id || typeof value.run_id !== "string" || !value.run_id || typeof value.consent_manifest_id !== "string" || !value.consent_manifest_id) throw new TypeError("Invalid M13 Narrative preparation");
  digest(value.authority_hash, "M13 Narrative preparation authority_hash");
  if (!object(value.provider) || typeof value.provider.provider !== "string" || typeof value.provider.adapter !== "string" || typeof value.provider.adapter_version !== "string" || typeof value.provider.requested_model !== "string" || typeof value.provider.resolved_model !== "string" || !object(value.provider.settings)) throw new TypeError("Invalid M13 Narrative provider identity");
  exactKeys(value.provider.settings, ["model_reasoning_effort", "fast_mode"], "M13 Narrative provider settings");
  if (!["low", "medium", "high", "xhigh"].includes(value.provider.settings.model_reasoning_effort) || value.provider.settings.fast_mode !== false) throw new TypeError("Invalid M13 Narrative provider settings");
  if (typeof value.provider_available !== "boolean" || !Array.isArray(value.selected_scope_ids) || value.selected_scope_ids.length !== 1 || value.selected_scope_ids.some((item) => typeof item !== "string" || !item)) throw new TypeError("Invalid M13 Narrative selected scope");
  if (!["fact_only", "story_text"].includes(value.privacy_mode) || typeof value.includes_m12_material !== "boolean" || value.consent_granted !== false || value.requires_confirm_cloud !== true || value.cloud_enabled !== false || !Number.isInteger(value.selected_scene_count) || value.selected_scene_count < 1) throw new TypeError("Invalid M13 Narrative consent state");
  const estimate = value.estimate;
  if (!object(estimate) || !["unavailable", "estimated", "reliable"].includes(estimate.cost_confidence)) throw new TypeError("Invalid M13 Narrative estimate");
  for (const key of ["logical_job_count", "provider_call_count", "input_tokens", "output_tokens"]) if (!Number.isInteger(estimate[key]) || estimate[key] < 0) throw new TypeError(`Invalid M13 Narrative estimate ${key}`);
  if ((estimate.estimated_cost_micros !== null && (!Number.isInteger(estimate.estimated_cost_micros) || estimate.estimated_cost_micros < 0)) || (estimate.cost_confidence === "unavailable" && estimate.estimated_cost_micros !== null)) throw new TypeError("Invalid M13 Narrative cost estimate");
  const limits = value.limits;
  if (!object(limits)) throw new TypeError("Invalid M13 Narrative limits");
  for (const key of ["max_provider_calls", "max_input_tokens", "max_output_tokens", "max_total_tokens", "timeout_seconds", "max_concurrency"]) if (!Number.isInteger(limits[key]) || limits[key] < 1) throw new TypeError(`Invalid M13 Narrative limit ${key}`);
  if (limits.max_cost_micros !== null && (!Number.isInteger(limits.max_cost_micros) || limits.max_cost_micros < 0)) throw new TypeError("Invalid M13 Narrative cost limit");
  return value;
}

export function assertNarrativeRunStatus(value) {
  const states = ["disabled", "prepared", "running", "cancelling", "succeeded", "partial", "failed", "cancelled", "hard_limit"];
  if (!object(value) || value.schema !== "m13-run-status-v1" || !states.includes(value.state) || typeof value.cloud_enabled !== "boolean" || typeof value.provider_transmission_active !== "boolean" || value.cloud_enabled !== ["running", "cancelling"].includes(value.state) || value.provider_transmission_active !== value.cloud_enabled || value.durable_completed_work_preserved !== true) throw new TypeError("Invalid M13 Narrative run status");
  if (value.preparation !== null) assertNarrativePreparation(value.preparation);
  if (value.latest_run !== null && (!object(value.latest_run) || typeof value.latest_run.run_id !== "string" || typeof value.latest_run.state !== "string")) throw new TypeError("Invalid M13 Narrative latest run");
  if (value.artifacts !== null && !object(value.artifacts)) throw new TypeError("Invalid M13 Narrative artifact set");
  if (!Array.isArray(value.unresolved_codes) || value.unresolved_codes.some((item) => typeof item !== "string")) throw new TypeError("Invalid M13 Narrative unresolved codes");
  if (typeof value.retry_available !== "boolean" || value.retry_available !== (value.retry_request !== null)) throw new TypeError("Invalid M13 Narrative retry state");
  if (value.retry_request !== null && (!object(value.retry_request) || typeof value.retry_request.resume_run_id !== "string" || typeof value.retry_request.resume_consent_id !== "string" || !object(value.retry_request.provider_settings) || !object(value.retry_request.limits) || !object(value.retry_request.batch_limits))) throw new TypeError("Invalid M13 Narrative retry request");
  return value;
}

export function assertAIStoryMap(value) {
  if (!object(value) || !["available", "unavailable"].includes(value.status)) throw new TypeError("Invalid AI Story Map response");
  digest(value.authority_hash, "AI Story Map authority_hash");
  if (value.status === "unavailable") {
    if (!object(value.technical_fallback) || value.technical_fallback.available !== true) throw new TypeError("AI Story Map fallback is unavailable");
    return value;
  }
  if (!Array.isArray(value.nodes) || !Array.isArray(value.edges) || !Array.isArray(value.continuation_endpoints) || !object(value.page) || !object(value.coverage)) throw new TypeError("AI Story Map page is incomplete");
  if (value.nodes.length > RENDER_LIMITS.nodes || value.edges.length > RENDER_LIMITS.edges || value.nodes.length + value.edges.length > RENDER_LIMITS.items) throw new RangeError("AI Story Map exceeds the packaged rendering boundary");
  if (value.level !== "ai_story_map" || value.presentation_levels?.length !== 2) throw new TypeError("Unexpected AI Story Map semantic levels");
  digest(value.organization_hash, "AI Story Map organization_hash");
  digest(value.projection_hash, "AI Story Map projection_hash");
  const page = value.page;
  for (const key of ["node_offset", "node_limit", "edge_offset", "edge_limit", "incident_edge_total", "total_nodes", "total_edges"]) {
    if (!Number.isInteger(page[key]) || page[key] < 0) throw new TypeError(`Invalid AI Story Map ${key}`);
  }
  if (page.edge_scope !== "incident_to_node_slice" || page.node_limit < 1 || page.node_limit > RENDER_LIMITS.nodes || page.edge_limit < 1 || page.edge_limit > RENDER_LIMITS.edges) throw new TypeError("Invalid AI Story Map incident-edge boundary");
  if (value.edges.length > page.edge_limit || page.edge_offset + value.edges.length > page.incident_edge_total || page.incident_edge_total > page.total_edges) throw new RangeError("AI Story Map incident-edge slice is inconsistent");
  const cursor = (token, offset, label) => {
    if (typeof token !== "string" || !/^v1\.\d+\.[0-9a-f]{64}$/.test(token) || Number(token.split(".")[1]) !== offset) throw new TypeError(`Invalid AI Story Map ${label}`);
  };
  if (page.edge_offset === 0) {
    if (page.edge_cursor !== null) throw new TypeError("Initial AI Story Map edge cursor must be null");
  } else cursor(page.edge_cursor, page.edge_offset, "edge_cursor");
  if ((page.next_edge_offset === null) !== (page.next_edge_cursor === null)) throw new TypeError("AI Story Map next edge cursor is incomplete");
  if (page.next_edge_offset !== null) {
    if (!Number.isInteger(page.next_edge_offset) || page.next_edge_offset !== page.edge_offset + value.edges.length || page.next_node_offset !== null) throw new TypeError("AI Story Map advances nodes before incident edges");
    cursor(page.next_edge_cursor, page.next_edge_offset, "next_edge_cursor");
  } else {
    if (page.edge_offset + value.edges.length !== page.incident_edge_total) throw new TypeError("AI Story Map dropped incident edges");
    if (page.next_node_offset !== null && (!Number.isInteger(page.next_node_offset) || page.next_node_offset <= page.node_offset)) throw new TypeError("Invalid AI Story Map next_node_offset");
  }
  const nodeIds = new Set(value.nodes.map((node) => node.id));
  const edgeById = new Map(value.edges.map((edge) => [edge.id, edge]));
  if (value.edges.some((edge) => !nodeIds.has(edge.source_id) && !nodeIds.has(edge.target_id))) throw new TypeError("AI Story Map returned an unrelated edge");
  const expectedContinuations = value.edges.flatMap((edge) => [["source", edge.source_id], ["target", edge.target_id]].filter(([, nodeId]) => !nodeIds.has(nodeId)).map(([endpoint, nodeId]) => `${edge.id}:${endpoint}:${nodeId}`));
  const actualContinuations = value.continuation_endpoints.map((item) => {
    if (!object(item) || !["source", "target"].includes(item.endpoint) || typeof item.edge_id !== "string" || typeof item.node_id !== "string" || typeof item.title !== "string" || !Number.isInteger(item.order)) throw new TypeError("Invalid AI Story Map continuation endpoint");
    const edge = edgeById.get(item.edge_id);
    if (!edge || edge[`${item.endpoint}_id`] !== item.node_id) throw new TypeError("AI Story Map continuation endpoint is not authoritative");
    return `${item.edge_id}:${item.endpoint}:${item.node_id}`;
  });
  if (!sameArray(actualContinuations, expectedContinuations)) throw new TypeError("AI Story Map continuation endpoints are incomplete");
  return value;
}

export function assertAIStoryDetail(value) {
  if (value?.status === "unavailable") return assertAIStoryMap(value);
  if (!object(value) || value.level !== "detail_evidence" || !object(value.element) || !Array.isArray(value.member_route_nodes) || !Array.isArray(value.member_route_edges) || !Array.isArray(value.evidence) || !Array.isArray(value.claims)) throw new TypeError("Invalid AI Detail/Evidence response");
  if (value.member_route_nodes.length > 30 || value.member_route_edges.length > 180 || value.evidence.length > 60) throw new RangeError("AI Detail/Evidence exceeds its bounded response limits");
  digest(value.authority_hash, "AI Detail authority_hash");
  return value;
}

export function assertMapComparison(value) {
  if (!object(value) || value.schema_version !== 1 || value.authority_unchanged !== true || !object(value.technical) || !object(value.ai)) throw new TypeError("Invalid map comparison response");
  digest(value.authority_hash, "Comparison authority_hash");
  assertRoutePage(value.technical);
  assertAIStoryMap(value.ai);
  if (value.technical.authority_hash !== value.authority_hash || value.ai.authority_hash !== value.authority_hash) throw new TypeError("Comparison authority changed");
  return value;
}

function exactOrganizationAccounting(value) {
  exactKeys(value, ["scope", "label", "run_id", "calls", "tokens", "elapsed_seconds", "elapsed_basis", "cache_hits", "attempts"], "Organization accounting");
  exactKeys(value.tokens, ["input", "output", "total"], "Organization accounting tokens");
  for (const item of [value.calls, value.tokens.input, value.tokens.output, value.tokens.total, value.cache_hits, value.attempts]) {
    if (!Number.isInteger(item) || item < 0) throw new TypeError("Organization accounting values must be non-negative integers");
  }
  if (value.tokens.total !== value.tokens.input + value.tokens.output || !Number.isFinite(value.elapsed_seconds) || value.elapsed_seconds < 0) throw new TypeError("Organization accounting totals are invalid");
  if (value.scope === "current_run") {
    if (value.label !== "Current run" || typeof value.run_id !== "string" || !value.run_id.startsWith("m07_") || value.elapsed_basis !== "wall_clock") throw new TypeError("Current-run accounting provenance is invalid");
  } else if (value.scope === "project_history") {
    if (value.label !== "Persisted project history" || value.run_id !== null || value.elapsed_basis !== "provider_attempts") throw new TypeError("Project-history accounting provenance is invalid");
  } else throw new TypeError("Organization accounting scope is invalid");
  return value;
}

export function assertOrganization(value) {
  if (!object(value)) throw new TypeError("Invalid organization response");
  exactOrganizationAccounting(value.accounting);
  if (!["current_run", "project_history"].includes(value.status_scope) || value.status_label !== value.accounting.label || !object(value.project_history) || value.project_history.scope !== "project_history" || value.project_history.label !== "Persisted project history") throw new TypeError("Organization status provenance is invalid");
  exactOrganizationAccounting(value.project_history.accounting);
  const scopeIds = uniqueStrings(value.scope_ids, "Organization scope_ids");
  const windowIds = uniqueStrings(value.window_ids, "Organization window_ids");
  exactSelectedCounts(value.selected_counts, scopeIds.length, windowIds.length);
  exactOrganizationModel(value.model); exactOrganizationBudgets(value.budgets);
  if (![value.cached, value.validated].every((count) => Number.isInteger(count) && count >= 0)) throw new TypeError("Organization checkpoint counts are invalid");
  if (value.selection_hash === null) {
    if (value.prepared_authority_hash !== null || value.recovered_source_acknowledgement !== null || scopeIds.length || windowIds.length) throw new TypeError("Unprepared organization exposes a partial consent binding");
  } else {
    digest(value.selection_hash, "Organization selection_hash"); digest(value.prepared_authority_hash, "Organization prepared_authority_hash"); digest(value.recovered_source_acknowledgement, "Organization recovered-source acknowledgement");
    if (!scopeIds.length && !windowIds.length) throw new TypeError("Organization consent selection is empty");
  }
  return value;
}
