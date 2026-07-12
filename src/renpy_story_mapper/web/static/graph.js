import { RENDER_LIMITS } from "./contract.js";

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

export class StoryGraph {
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
    this.offset = { x: 32, y: 32 };
    this.drag = null;
    this.resizeObserver = new ResizeObserver(() => this.draw());
    this.resizeObserver.observe(viewport);
    this.bind();
  }

  bind() {
    this.viewport.addEventListener("pointerdown", (event) => {
      if (event.target.closest?.(".map-node")) return;
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
      this.zoomBy(event.deltaY < 0 ? 0.1 : -0.1, { x: event.offsetX, y: event.offsetY });
    }, { passive: false });
    this.viewport.addEventListener("keydown", (event) => this.keyboard(event));
  }

  setData(nodes, edges, selectedId = null) {
    if (nodes.length > RENDER_LIMITS.nodes || edges.length > RENDER_LIMITS.edges || nodes.length + edges.length > RENDER_LIMITS.items) throw new RangeError("Graph render boundary exceeded");
    this.nodes = nodes;
    const ids = new Set(nodes.map((node) => node.id));
    this.edges = edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
    this.positions.clear();
    this.world.replaceChildren();
    const columns = nodes.length <= 6 ? 3 : 4;
    nodes.forEach((node, index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);
      const branch = node.kind === "choice" ? 34 : node.kind === "merge" ? -18 : 0;
      const position = { x: 40 + column * 300, y: 38 + row * 190 + branch, width: 240, height: 120 };
      this.positions.set(node.id, position);
      const card = document.createElement("button");
      card.type = "button";
      card.className = "map-node";
      card.dataset.nodeId = node.id;
      card.dataset.kind = node.kind || "story";
      card.setAttribute("role", "option");
      card.setAttribute("aria-selected", "false");
      card.style.left = `${position.x}px`;
      card.style.top = `${position.y}px`;
      card.tabIndex = -1;
      card.append(this.span("node-index", String(index + 1).padStart(2, "0")), this.span("node-title", node.title || "Untitled story item"), this.span("node-summary", node.summary || ""));
      const footer = document.createElement("span");
      footer.className = "node-footer";
      footer.append(this.span("", node.kind || "story"), this.span("", `${node.evidence_count || 0} evidence`));
      card.append(footer);
      card.addEventListener("click", () => this.select(node.id, true));
      card.addEventListener("dblclick", () => this.onOpen?.(node));
      this.world.append(card);
    });
    this.select(ids.has(selectedId) ? selectedId : nodes[0]?.id || null, false);
    this.fit();
  }

  span(className, value) {
    const span = document.createElement("span");
    span.className = className;
    span.textContent = String(value);
    return span;
  }

  select(id, notify = true) {
    if (!id) return;
    const next = this.nodes.find((node) => node.id === id);
    if (!next) return;
    this.selectedId = id;
    for (const card of this.world.querySelectorAll(".map-node")) {
      const selected = card.dataset.nodeId === id;
      card.setAttribute("aria-selected", String(selected));
      card.tabIndex = selected ? 0 : -1;
    }
    this.draw();
    if (notify) this.onSelect?.(next);
  }

  keyboard(event) {
    if (!this.nodes.length) return;
    const current = Math.max(0, this.nodes.findIndex((node) => node.id === this.selectedId));
    let next = current;
    if (["ArrowRight", "ArrowDown"].includes(event.key)) next = (current + 1) % this.nodes.length;
    else if (["ArrowLeft", "ArrowUp"].includes(event.key)) next = (current - 1 + this.nodes.length) % this.nodes.length;
    else if (event.key === "Enter") { this.onOpen?.(this.nodes[current]); event.preventDefault(); return; }
    else if (event.key === "+" || event.key === "=") { this.zoomBy(.1); event.preventDefault(); return; }
    else if (event.key === "-") { this.zoomBy(-.1); event.preventDefault(); return; }
    else if (event.key === "0") { this.fit(); event.preventDefault(); return; }
    else return;
    event.preventDefault();
    this.select(this.nodes[next].id, true);
    this.world.querySelector(`[data-node-id="${CSS.escape(this.nodes[next].id)}"]`)?.focus();
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
    const maxX = Math.max(...[...this.positions.values()].map((position) => position.x + position.width)) + 40;
    const maxY = Math.max(...[...this.positions.values()].map((position) => position.y + position.height)) + 40;
    const rect = this.viewport.getBoundingClientRect();
    this.scale = clamp(Math.min((rect.width - 32) / maxX, (rect.height - 32) / maxY, 1), .5, 1);
    this.offset = { x: 16, y: 16 };
    this.transform();
  }

  transform() {
    this.world.style.transform = `translate(${this.offset.x}px, ${this.offset.y}px) scale(${this.scale})`;
    this.draw();
  }

  draw() {
    const rect = this.viewport.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    this.canvas.width = Math.max(1, Math.floor(rect.width * ratio));
    this.canvas.height = Math.max(1, Math.floor(rect.height * ratio));
    this.context.setTransform(ratio, 0, 0, ratio, 0, 0);
    this.context.clearRect(0, 0, rect.width, rect.height);
    const style = getComputedStyle(document.documentElement);
    for (const edge of this.edges) {
      const source = this.positions.get(edge.source);
      const target = this.positions.get(edge.target);
      if (!source || !target) continue;
      const sx = this.offset.x + (source.x + source.width) * this.scale;
      const sy = this.offset.y + (source.y + source.height / 2) * this.scale;
      const tx = this.offset.x + target.x * this.scale;
      const ty = this.offset.y + (target.y + target.height / 2) * this.scale;
      this.context.beginPath();
      this.context.moveTo(sx, sy);
      const midpoint = (sx + tx) / 2;
      this.context.bezierCurveTo(midpoint, sy, midpoint, ty, tx, ty);
      this.context.strokeStyle = style.getPropertyValue(edge.kind === "choice" ? "--choice" : "--flow").trim();
      this.context.lineWidth = edge.source === this.selectedId || edge.target === this.selectedId ? 2.6 : 1.35;
      this.context.setLineDash(edge.kind === "unresolved" ? [5, 5] : []);
      this.context.stroke();
      const angle = Math.atan2(ty - sy, tx - sx);
      this.context.beginPath();
      this.context.moveTo(tx, ty);
      this.context.lineTo(tx - 8 * Math.cos(angle - .45), ty - 8 * Math.sin(angle - .45));
      this.context.lineTo(tx - 8 * Math.cos(angle + .45), ty - 8 * Math.sin(angle + .45));
      this.context.closePath();
      this.context.fillStyle = this.context.strokeStyle;
      this.context.fill();
      if (edge.label) {
        this.context.setLineDash([]);
        this.context.font = "11px Consolas, monospace";
        this.context.fillStyle = style.getPropertyValue("--ink").trim();
        this.context.fillText(String(edge.label).slice(0, 32), midpoint + 5, (sy + ty) / 2 - 6);
      }
    }
  }
}
