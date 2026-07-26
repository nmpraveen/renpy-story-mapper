/** Phase 04 reader freshness and API-authored NEW presentation. */

export const READER_CONTRACT_SCHEMA = "story-map-v2-reader-contract-v2";

const FRESHNESS_PRESENTATION = Object.freeze({
  current: Object.freeze({ key: "current", label: "Current", is_stale: false }),
  building: Object.freeze({ key: "building", label: "Updating", is_stale: false }),
  stale: Object.freeze({ key: "stale", label: "Stale", is_stale: true }),
  phase03_compatible: Object.freeze({ key: "phase03_compatible", label: "Compatible", is_stale: false }),
});

const ROUTE_KEYS = Object.freeze([
  "manifest",
  "status",
  "section_page",
  "branch_page",
  "locate",
  "search",
  "path_page",
  "detail_page",
  "view_state",
  "save_view_state",
]);

function object(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
  return value;
}

function nonempty(value, label, maximum = 512) {
  if (typeof value !== "string" || !value || value.length > maximum) {
    throw new TypeError(`${label} must be bounded nonempty text`);
  }
  return value;
}

function revision(value, label = "map_revision") {
  if (!Number.isSafeInteger(value) || value < 0) throw new TypeError(`${label} must be a nonnegative integer`);
  return value;
}

function newFacts(value) {
  if (!Array.isArray(value) || value.length > 240) throw new TypeError("new_facts must be a bounded array");
  const seen = new Set();
  return value.map((entry) => {
    const fact = object(entry, "NEW fact");
    const kind = nonempty(fact.kind, "NEW fact kind");
    const factId = nonempty(fact.fact_id, "NEW fact id");
    const identity = `${kind}\u0000${factId}`;
    if (seen.has(identity)) throw new TypeError("new_facts contains a duplicate fact");
    seen.add(identity);
    return Object.freeze({ kind, fact_id: factId });
  });
}

export function validateReaderContract(bundle) {
  const contract = object(bundle, "reader contract");
  if (contract.schema !== READER_CONTRACT_SCHEMA) throw new TypeError("Unsupported reader contract schema");
  if (contract.extends !== "story-map-v2-reader-contract-v1" ||
      object(contract.delta, "reader contract delta").locate_location_required_field !== "branch_id") {
    throw new TypeError("Reader contract lacks the v2 locate identity extension");
  }
  const routes = object(contract.routes, "reader routes");
  for (const key of ROUTE_KEYS) {
    const route = nonempty(routes[key], `reader route ${key}`);
    if (!route.startsWith("/api/v1/story-map-v2/")) throw new TypeError(`Reader route ${key} is not local and versioned`);
  }
  const limits = object(contract.limits, "reader limits");
  if (limits.events_per_section_page !== 30 || limits.rendered_items_per_page !== 240 ||
      limits.serialized_bytes_per_page !== 1048576 || limits.live_story_items !== 600) {
    throw new TypeError("Reader limits do not match the frozen v1 contract");
  }
  return contract;
}

export function presentFreshness(value) {
  const key = typeof value === "string" ? value : object(value, "reader manifest").freshness;
  const presentation = FRESHNESS_PRESENTATION[key];
  if (!presentation) throw new TypeError("Unknown reader freshness");
  return presentation;
}

export function presentNew(record, { hideNew = false } = {}) {
  const entity = object(record, "reader entity");
  if (typeof hideNew !== "boolean") throw new TypeError("hideNew must be boolean");
  const hasFlag = Object.hasOwn(entity, "is_new");
  const hasFacts = Object.hasOwn(entity, "new_facts");
  if (!hasFlag && !hasFacts) {
    return Object.freeze({ is_new: false, visible: false, label: null, facts: Object.freeze([]) });
  }
  if (!hasFlag || !hasFacts || typeof entity.is_new !== "boolean") {
    throw new TypeError("Reader entity NEW fields must be supplied together");
  }
  const facts = Object.freeze(newFacts(entity.new_facts));
  if (entity.is_new !== (facts.length > 0)) throw new TypeError("Reader entity NEW flag and facts disagree");
  return Object.freeze({
    is_new: entity.is_new,
    visible: entity.is_new && !hideNew,
    label: entity.is_new && !hideNew ? "NEW" : null,
    facts,
  });
}

export function presentReaderDiff(manifest, viewState = {}) {
  const value = object(manifest, "reader manifest");
  if (value.schema !== READER_CONTRACT_SCHEMA) throw new TypeError("Unsupported reader manifest schema");
  const state = object(viewState, "reader view state");
  const hideNew = state.hide_new === undefined ? false : state.hide_new;
  if (typeof hideNew !== "boolean") throw new TypeError("hide_new must be boolean");
  if (!Array.isArray(value.sections)) throw new TypeError("reader manifest sections must be an array");
  return Object.freeze({
    map_revision: revision(value.map_revision),
    generation_id: nonempty(value.generation_id, "generation_id"),
    freshness: presentFreshness(value),
    hide_new: hideNew,
    sections: Object.freeze(value.sections.map((section) => Object.freeze({
      id: nonempty(object(section, "reader section").id, "section id"),
      presentation: presentNew(section, { hideNew }),
    }))),
  });
}

export function staleRevisionFromResponse(status, payload) {
  if (status !== 409) return null;
  const response = object(payload, "stale response");
  const error = object(response.error, "stale response error");
  if (error.code !== "stale_map_revision") return null;
  nonempty(error.message, "stale response message", 4096);
  return revision(response.map_revision);
}
