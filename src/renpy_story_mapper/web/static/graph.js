import { RENDER_LIMITS } from "./contract.js";

const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));
const laneY = Object.freeze({ spine: 240, "detour-a": 105, red: 390, blue: 510 });

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
    this.selectedId = null;
    this.scale = 1;
    this.offset = { x: 34, y: 20 };
    this.drag = null;
    new ResizeObserver(() => this.draw()).observe(viewport);
    this.bind();
  }

  bind() {
    this.viewport.addEventListener("pointerdown", (event) => {
      if (event.target.closest?.(".station, .edge-stop")) return;
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

  setData(nodes, edges, selectedId = null) {
    if (nodes.length > RENDER_LIMITS.nodes || edges.length > RENDER_LIMITS.edges || nodes.length + edges.length > RENDER_LIMITS.items) throw new RangeError("Route Map render boundary exceeded");
    this.nodes = nodes;
    const ids = new Set(nodes.map((node) => node.id));
    this.edges = edges.filter((edge) => ids.has(edge.source_id) || ids.has(edge.target_id));
    this.positions.clear();
    this.world.replaceChildren();
    const chronological = [...nodes].sort((a, b) => Number(a.order || 0) - Number(b.order || 0));
    chronological.forEach((node, index) => {
      const lane = node.lane_id in laneY ? node.lane_id : node.lane_kind === "persistent" ? (index % 2 ? "blue" : "red") : node.lane_kind === "detour" ? "detour-a" : "spine";
      const position = { x: 70 + index * 178, y: laneY[lane], width: 136, height: 62 };
      this.positions.set(node.id, position);
      const button = document.createElement("button");
      button.type = "button";
      button.className = "station";
      button.dataset.elementId = node.id;
      button.dataset.kind = node.kind || "milestone";
      button.dataset.lane = node.lane_kind || "spine";
      button.style.left = `${position.x}px`;
      button.style.top = `${position.y}px`;
      button.tabIndex = -1;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", "false");
      button.setAttribute("aria-label", `${node.kind || "Milestone"}: ${node.title || "Untitled station"}. Open Detail and Evidence.`);
      button.append(this.span("station-shape", this.shape(node.kind)), this.span("station-title", node.title || "Untitled station"));
      const marker = this.span("station-meta", `${String(index + 1).padStart(2, "0")} · ${String(node.kind || "milestone").replaceAll("_", " ")}`);
      button.append(marker);
      button.addEventListener("click", () => { this.select(node.id, true); this.onOpen?.(node); });
      this.world.append(button);
    });
    for (const edge of this.edges) {
      const source = this.positions.get(edge.source_id);
      const target = this.positions.get(edge.target_id);
      if (!source || !target) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "edge-stop";
      button.dataset.elementId = edge.id;
      button.dataset.role = edge.role || "flow";
      button.style.left = `${(source.x + source.width + target.x) / 2 - 12}px`;
      button.style.top = `${(source.y + target.y) / 2 + 20}px`;
      button.tabIndex = -1;
      const detail = [edge.role, edge.gate_ids?.length ? "gate" : "", edge.effect_ids?.length ? "effect" : "", edge.technical_hops ? `${edge.technical_hops} technical steps` : ""].filter(Boolean).join(", ");
      button.setAttribute("aria-label", `Route segment: ${detail || "flow"}. Open Detail and Evidence.`);
      button.textContent = edge.gate_ids?.length ? "G" : edge.effect_ids?.length ? "+" : edge.technical_hops ? String(edge.technical_hops) : "·";
      button.addEventListener("click", () => { this.select(edge.id, true); this.onOpen?.(edge); });
      this.world.append(button);
    }
    this.select(this.elements().some((item) => item.id === selectedId) ? selectedId : chronological[0]?.id, false);
    this.fit();
  }

  elements() { return [...this.nodes, ...this.edges]; }
  shape(kind) { return kind === "choice" ? "◆" : kind === "merge" ? "◇" : kind === "loop" ? "↻" : kind === "terminal" ? "■" : kind === "unresolved" ? "?" : "●"; }
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
    const values = [...this.positions.values()];
    const width = Math.max(...values.map((position) => position.x + position.width)) + 80;
    const height = Math.max(...values.map((position) => position.y + position.height)) + 70;
    const rect = this.viewport.getBoundingClientRect();
    this.scale = clamp(Math.min((rect.width - 32) / width, (rect.height - 32) / height, 1), .5, 1);
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
    const root = getComputedStyle(document.documentElement);
    for (const edge of this.edges) {
      const source = this.positions.get(edge.source_id);
      const target = this.positions.get(edge.target_id);
      if (!source || !target) continue;
      const sx = this.offset.x + (source.x + source.width / 2) * this.scale;
      const sy = this.offset.y + (source.y + 20) * this.scale;
      const tx = this.offset.x + (target.x + target.width / 2) * this.scale;
      const ty = this.offset.y + (target.y + 20) * this.scale;
      const role = String(edge.role || "flow");
      const color = role.includes("unresolved") ? "--unresolved" : edge.lane_id === "red" ? "--route-red" : edge.lane_id === "blue" ? "--route-blue" : role.includes("detour") || role.includes("choice") ? "--detour" : "--flow";
      this.context.beginPath();
      this.context.moveTo(sx, sy);
      const bend = Math.max(26, Math.abs(tx - sx) * .35);
      this.context.bezierCurveTo(sx + bend, sy, tx - bend, ty, tx, ty);
      this.context.strokeStyle = root.getPropertyValue(color).trim();
      this.context.lineWidth = edge.id === this.selectedId ? 5 : role === "technical_corridor" ? 8 : 3;
      this.context.setLineDash(role.includes("unresolved") ? [7, 6] : role.includes("loop") ? [4, 4] : []);
      this.context.stroke();
      if (edge.proven_merge) {
        this.context.setLineDash([]);
        this.context.strokeRect(tx - 5, ty - 5, 10, 10);
      }
    }
  }
}
