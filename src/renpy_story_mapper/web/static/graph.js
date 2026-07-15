import { RENDER_LIMITS } from "./contract.js";

const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));
const X_STEP = 222;
const LANE_STEP = 128;
const NODE_WIDTH = 164;
const NODE_HEIGHT = 78;

function stableHue(value) {
  let hash = 2166136261;
  for (const character of String(value)) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
  return Math.abs(hash) % 360;
}

export class RouteGraph {
  constructor({ viewport, world, canvas, onSelect, onOpen }) {
    this.viewport = viewport;
    this.world = world;
    this.canvas = canvas;
    this.context = canvas.getContext("2d");
    this.onSelect = onSelect;
    this.onOpen = onOpen;
    this.nodes = [];
    this.edges = [];
    this.positions = new Map();
    this.edgePositions = new Map();
    this.selectedId = null;
    this.scale = 1;
    this.offset = { x: 24, y: 20 };
    this.bounds = { width: 1, height: 1 };
    this.drag = null;
    new ResizeObserver(() => this.draw()).observe(viewport);
    this.bind();
  }

  bind() {
    this.viewport.addEventListener("pointerdown", (event) => {
      if (event.target.closest?.(".station, .edge-stop, .continuation-portal")) return;
      this.drag = { x: event.clientX, y: event.clientY, ox: this.offset.x, oy: this.offset.y };
      this.viewport.setPointerCapture(event.pointerId);
      this.viewport.classList.add("is-panning");
    });
    this.viewport.addEventListener("pointermove", (event) => {
      if (!this.drag) return;
      this.offset.x = this.drag.ox + event.clientX - this.drag.x;
      this.offset.y = this.drag.oy + event.clientY - this.drag.y;
      this.transform();
    });
    const stop = () => { this.drag = null; this.viewport.classList.remove("is-panning"); };
    this.viewport.addEventListener("pointerup", stop);
    this.viewport.addEventListener("pointercancel", stop);
    this.viewport.addEventListener("wheel", (event) => {
      event.preventDefault();
      this.zoomBy(event.deltaY < 0 ? .1 : -.1, { x: event.offsetX, y: event.offsetY });
    }, { passive: false });
    this.viewport.addEventListener("keydown", (event) => this.keyboard(event));
  }

  laneOrder(nodes, lanes = []) {
    const metadata = new Map(lanes.map((lane) => [lane.id, lane]));
    for (const node of nodes) if (!metadata.has(node.lane_id)) metadata.set(node.lane_id, { id: node.lane_id, kind: node.lane_kind, label: node.lane_label });
    return [...metadata.values()].filter((lane) => lane.id).sort((a, b) => {
      const priority = (lane) => lane.kind === "spine" ? 0 : lane.kind === "detour" ? 1 : 2;
      return priority(a) - priority(b) || String(a.id).localeCompare(String(b.id));
    });
  }

  setData(nodes, edges, selectedId = null, lanes = []) {
    if (nodes.length > RENDER_LIMITS.nodes || edges.length > RENDER_LIMITS.edges || nodes.length + edges.length > RENDER_LIMITS.items) throw new RangeError("Route Map render boundary exceeded");
    this.nodes = [...nodes].sort((a, b) => Number(a.order || 0) - Number(b.order || 0) || String(a.id).localeCompare(String(b.id)));
    const ids = new Set(nodes.map((node) => node.id));
    this.edges = edges.filter((edge) => ids.has(edge.source_id) || ids.has(edge.target_id));
    this.positions.clear();
    this.edgePositions.clear();
    this.world.replaceChildren();

    const laneRows = this.laneOrder(nodes, lanes);
    const laneIndex = new Map(laneRows.map((lane, index) => [lane.id, index]));
    const orders = [...new Set(this.nodes.map((node) => Number(node.order || 0)))].sort((a, b) => a - b);
    const orderIndex = new Map(orders.map((order, index) => [order, index]));
    const laneTop = 82;

    laneRows.forEach((lane, index) => {
      const label = document.createElement("span");
      label.className = "lane-label";
      label.style.top = `${laneTop + index * LANE_STEP - 32}px`;
      label.textContent = String(lane.label || (lane.kind === "spine" ? "Story spine" : lane.kind === "detour" ? "Local detours" : "Persistent route"));
      this.world.append(label);
    });

    this.nodes.forEach((node, index) => {
      const x = 92 + (orderIndex.get(Number(node.order || 0)) ?? index) * X_STEP;
      const y = laneTop + (laneIndex.get(node.lane_id) ?? 0) * LANE_STEP;
      const position = { x, y, width: NODE_WIDTH, height: NODE_HEIGHT, lane: node.lane_id };
      this.positions.set(node.id, position);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "station";
      button.dataset.elementId = node.id;
      button.dataset.kind = node.kind || "event";
      button.dataset.role = node.presentation_role || node.kind || "event";
      button.dataset.laneKind = node.lane_kind || "spine";
      button.dataset.laneId = node.lane_id || "story-spine";
      button.style.left = `${x}px`;
      button.style.top = `${y}px`;
      button.tabIndex = -1;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", "false");
      const gateCount = Number(node.gate_ids?.length || node.fact_ids?.length || 0);
      button.setAttribute("aria-label", `${node.kind || "Event"}: ${node.title || "Untitled event"}${gateCount ? `, ${gateCount} facts` : ""}. Open Detail and Evidence.`);
      button.append(this.span("station-shape", this.shape(node.kind)), this.span("station-title", node.title || "Untitled event"));
      if (node.summary) button.append(this.span("station-summary", node.summary));
      button.append(this.span("station-meta", `${String(index + 1).padStart(2, "0")} · ${String(node.source_kind || node.kind || "event").replaceAll("_", " ")}`));
      button.addEventListener("click", () => { this.select(node.id, true); this.onOpen?.(node); });
      this.world.append(button);
    });

    const minX = 42;
    const maxX = Math.max(300, ...[...this.positions.values()].map((position) => position.x + position.width + 80));
    for (const edge of this.edges) {
      const source = this.positions.get(edge.source_id);
      const target = this.positions.get(edge.target_id);
      const known = source || target;
      if (!known) continue;
      const missingSource = !source;
      const missingTarget = !target;
      const sourcePoint = source ? { x: source.x + source.width, y: source.y + 26 } : { x: minX, y: target.y + 26 };
      const targetPoint = target ? { x: target.x, y: target.y + 26 } : { x: maxX, y: source.y + 26 };
      this.edgePositions.set(edge.id, { source: sourcePoint, target: targetPoint, missingSource, missingTarget });
      const midpoint = { x: (sourcePoint.x + targetPoint.x) / 2, y: (sourcePoint.y + targetPoint.y) / 2 };
      const interactive = edge.interactive !== false;
      const button = document.createElement(interactive ? "button" : "span");
      if (interactive) button.type = "button";
      button.className = missingSource || missingTarget ? "continuation-portal" : "edge-stop";
      if (interactive) button.dataset.elementId = edge.id;
      button.dataset.role = edge.role || edge.presentation_role || "transition";
      button.dataset.continuation = missingSource ? "previous" : missingTarget ? "next" : "";
      button.style.left = `${(missingSource ? sourcePoint.x : missingTarget ? targetPoint.x : midpoint.x) - 14}px`;
      button.style.top = `${(missingSource ? sourcePoint.y : missingTarget ? targetPoint.y : midpoint.y) - 14}px`;
      if (interactive) {
        button.tabIndex = -1;
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", "false");
      } else button.setAttribute("aria-hidden", "true");
      const continuation = missingSource ? `Continues from ${edge.source_title || edge.source_id} on another page` : missingTarget ? `Continues to ${edge.target_title || edge.target_id} on another page` : "Route segment";
      const detail = [edge.role || edge.presentation_role, edge.gate_ids?.length ? `${edge.gate_ids.length} gate` : "", edge.effect_ids?.length ? `${edge.effect_ids.length} effect` : "", edge.technical_hops ? `${edge.technical_hops} technical steps` : ""].filter(Boolean).join(", ");
      if (interactive) button.setAttribute("aria-label", `${continuation}: ${detail || "flow"}. Open Detail and Evidence.`);
      button.textContent = missingSource ? "←" : missingTarget ? "→" : edge.gate_ids?.length ? "G" : edge.effect_ids?.length ? "+" : edge.technical_hops ? String(edge.technical_hops) : "·";
      if (interactive) button.addEventListener("click", () => { this.select(edge.id, true); this.onOpen?.(edge); });
      this.world.append(button);
    }
    this.bounds = { width: maxX + 30, height: laneTop + laneRows.length * LANE_STEP + 50 };
    this.world.style.width = `${this.bounds.width}px`;
    this.world.style.height = `${this.bounds.height}px`;
    this.select(this.elements().some((item) => item.id === selectedId) ? selectedId : this.nodes[0]?.id, false);
    this.fit();
  }

  elements() { return [...this.nodes, ...this.edges.filter((edge) => edge.interactive !== false)]; }
  shape(kind) { return kind === "choice" || kind === "choice_outcome" ? "◆" : kind === "merge" ? "◇" : kind === "loop" ? "↻" : kind === "terminal" || kind === "ending" ? "■" : kind === "unresolved" ? "?" : "●"; }
  span(className, value) { const span = document.createElement("span"); span.className = className; span.textContent = String(value); return span; }

  select(id, notify = true) {
    const selected = this.elements().find((item) => item.id === id);
    if (!selected) return;
    this.selectedId = id;
    for (const item of this.world.querySelectorAll("[data-element-id]")) {
      const active = item.dataset.elementId === id;
      item.setAttribute("aria-selected", String(active));
      item.tabIndex = active ? 0 : -1;
    }
    this.draw();
    if (notify) this.onSelect?.(selected);
  }

  keyboard(event) {
    const items = this.elements();
    if (!items.length) return;
    let index = Math.max(0, items.findIndex((item) => item.id === this.selectedId));
    if (["ArrowRight", "ArrowDown"].includes(event.key)) index = (index + 1) % items.length;
    else if (["ArrowLeft", "ArrowUp"].includes(event.key)) index = (index - 1 + items.length) % items.length;
    else if (event.key === "Home") index = 0;
    else if (event.key === "End") index = items.length - 1;
    else if (event.key === "Enter") { this.onOpen?.(items[index]); event.preventDefault(); return; }
    else if (["+", "="].includes(event.key)) { this.zoomBy(.1); event.preventDefault(); return; }
    else if (event.key === "-") { this.zoomBy(-.1); event.preventDefault(); return; }
    else if (event.key === "0") { this.fit(); event.preventDefault(); return; }
    else return;
    event.preventDefault();
    this.select(items[index].id, true);
    this.world.querySelector(`[data-element-id="${CSS.escape(items[index].id)}"]`)?.focus();
  }

  zoomBy(delta, anchor = null) {
    const before = this.scale;
    this.scale = clamp(Math.round((this.scale + delta) * 10) / 10, .5, 2);
    if (anchor && before !== this.scale) {
      const ratio = this.scale / before;
      this.offset.x = anchor.x - (anchor.x - this.offset.x) * ratio;
      this.offset.y = anchor.y - (anchor.y - this.offset.y) * ratio;
    }
    this.transform();
    return this.scale;
  }

  fit() {
    if (!this.nodes.length) return;
    const rect = this.viewport.getBoundingClientRect();
    this.scale = clamp(Math.min((rect.width - 32) / this.bounds.width, (rect.height - 32) / this.bounds.height, 1), .5, 1);
    this.offset = { x: 16, y: 16 };
    this.transform();
  }

  transform() { this.world.style.transform = `translate(${this.offset.x}px, ${this.offset.y}px) scale(${this.scale})`; this.draw(); }

  draw() {
    const rect = this.viewport.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = Math.max(1, Math.floor(rect.width * ratio));
    this.canvas.height = Math.max(1, Math.floor(rect.height * ratio));
    this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.context.clearRect(0, 0, rect.width, rect.height);
    const styles = getComputedStyle(document.documentElement);
    const rule = styles.getPropertyValue("--rule").trim();
    const ink = styles.getPropertyValue("--ink").trim();
    const accent = styles.getPropertyValue("--accent").trim();
    this.context.strokeStyle = rule;
    this.context.lineWidth = 1;
    this.context.setLineDash([2, 10]);
    for (let y = 86; y < rect.height; y += LANE_STEP * this.scale) {
      this.context.beginPath();
      this.context.moveTo(0, Math.round(y) + .5);
      this.context.lineTo(rect.width, Math.round(y) + .5);
      this.context.stroke();
    }
    this.context.setLineDash([]);
    for (const edge of this.edges) {
      const points = this.edgePositions.get(edge.id);
      if (!points) continue;
      const sx = this.offset.x + points.source.x * this.scale;
      const sy = this.offset.y + points.source.y * this.scale;
      const tx = this.offset.x + points.target.x * this.scale;
      const ty = this.offset.y + points.target.y * this.scale;
      const role = String(edge.role || edge.presentation_role || "transition");
      this.context.beginPath();
      this.context.moveTo(sx, sy);
      if (role.includes("loop") || tx <= sx) {
        const lift = Math.max(46, Math.abs(tx - sx) * .28);
        this.context.bezierCurveTo(sx + 50, sy - lift, tx - 50, ty - lift, tx, ty);
      } else {
        const bend = Math.max(30, Math.abs(tx - sx) * .36);
        this.context.bezierCurveTo(sx + bend, sy, tx - bend, ty, tx, ty);
      }
      this.context.strokeStyle = role.includes("persistent") || role.includes("detour") ? accent : ink;
      this.context.lineWidth = edge.id === this.selectedId ? 5 : role === "technical_corridor" ? 8 : 2.5;
      this.context.setLineDash(points.missingSource || points.missingTarget ? [10, 5] : role.includes("unresolved") ? [7, 6] : role.includes("loop") ? [4, 4] : []);
      this.context.stroke();
      this.context.setLineDash([]);
      if (edge.gate_ids?.length) {
        const mx = (sx + tx) / 2; const my = (sy + ty) / 2;
        this.context.strokeStyle = accent;
        this.context.strokeRect(mx - 5, my - 5, 10, 10);
      }
      if (edge.proven_merge) {
        this.context.strokeStyle = ink;
        this.context.strokeRect(tx - 6, ty - 6, 12, 12);
      }
    }
  }
}

export { stableHue };
