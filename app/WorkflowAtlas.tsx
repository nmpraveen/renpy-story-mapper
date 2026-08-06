"use client";

/* eslint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex -- the canvas is intentionally a keyboard-operable application surface */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import workflowMap from "./workflow-map.json";

type Status = "passed" | "failed" | "attention" | "not-built";
type Flow = "evidence" | "ai" | "validation" | "publication";
type Executor = "python" | "ai" | "browser";
type TraceMode = "both" | "upstream" | "downstream";

type Project = {
  title: string;
  subtitle: string;
  commit: string;
  updatedAt: string;
  status: Status;
  summary: string;
  evidence: string;
};

type Phase = {
  id: string;
  label: string;
  title: string;
  status: Status;
  x: number;
  y: number;
  width: number;
  height: number;
  summary: string;
};

type Lane = {
  id: string;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  flow: Flow;
};

type WorkflowNode = {
  id: string;
  label: string;
  kicker: string;
  status: Status;
  executor: Executor;
  x: number;
  y: number;
  width: number;
  height: number;
  flow: Flow;
  description: string;
  why: string;
  evidence: string;
  history?: string[];
  error?: {
    whatFailed: string;
    expected: string;
    got: string;
    next: string;
  };
};

type Edge = {
  id: string;
  source: string;
  target: string;
  flow: Flow;
  kind?: "feedback";
  label?: string;
};

type WorkflowData = {
  project: Project;
  canvas: { width: number; height: number };
  phases: Phase[];
  lanes: Lane[];
  nodes: WorkflowNode[];
  edges: Edge[];
};

type ViewState = { x: number; y: number; zoom: number };

const data = workflowMap as WorkflowData;
const MIN_ZOOM = 0.32;
const MAX_ZOOM = 1.8;

const statusLabels: Record<Status, string> = {
  passed: "Passed",
  failed: "Failed",
  attention: "Needs attention",
  "not-built": "Not built",
};

const flowLabels: Record<Flow, string> = {
  evidence: "Evidence flow",
  ai: "AI flow",
  validation: "Validation flow",
  publication: "Publication flow",
};

const executorLabels: Record<Executor, string> = {
  python: "Python",
  ai: "AI",
  browser: "Browser check",
};

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function formatDate(value: string) {
  const date = new Date(`${value}T12:00:00`);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      }).format(date);
}

function connectorPath(source: WorkflowNode, target: WorkflowNode, edge: Edge) {
  const x1 = source.x + source.width;
  const y1 = source.y + source.height / 2;
  const x2 = target.x;
  const y2 = target.y + target.height / 2;

  if (edge.kind === "feedback") {
    const loopY = Math.max(y1, y2) + 165;
    return `M ${x1} ${y1} C ${x1 + 130} ${loopY}, ${x2 - 180} ${loopY}, ${x2} ${y2}`;
  }

  const distance = Math.max(Math.abs(x2 - x1) * 0.48, 70);
  const direction = x2 >= x1 ? 1 : -1;
  return `M ${x1} ${y1} C ${x1 + distance * direction} ${y1}, ${x2 - distance * direction} ${y2}, ${x2} ${y2}`;
}

export default function WorkflowAtlas() {
  const viewportRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    pointerId: number;
    clientX: number;
    clientY: number;
    viewX: number;
    viewY: number;
  } | null>(null);
  const [view, setView] = useState<ViewState>({ x: 24, y: 68, zoom: 0.54 });
  const [viewportSize, setViewportSize] = useState({ width: 1400, height: 820 });
  const [isDragging, setIsDragging] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>("final-validator");
  const [traceMode, setTraceMode] = useState<TraceMode>("both");
  const [search, setSearch] = useState("");
  const [showHelp, setShowHelp] = useState(false);

  const nodeMap = useMemo(
    () => new Map(data.nodes.map((node) => [node.id, node])),
    [],
  );

  const structuralEdges = useMemo(
    () => data.edges.filter((edge) => edge.kind !== "feedback"),
    [],
  );

  const trace = useMemo(() => {
    const upstream = new Set<string>();
    const downstream = new Set<string>();

    if (!selectedId) {
      return { upstream, downstream, active: new Set<string>() };
    }

    const walkUp = (id: string) => {
      for (const edge of structuralEdges) {
        if (edge.target === id && !upstream.has(edge.source)) {
          upstream.add(edge.source);
          walkUp(edge.source);
        }
      }
    };

    const walkDown = (id: string) => {
      for (const edge of structuralEdges) {
        if (edge.source === id && !downstream.has(edge.target)) {
          downstream.add(edge.target);
          walkDown(edge.target);
        }
      }
    };

    walkUp(selectedId);
    walkDown(selectedId);

    const active = new Set<string>([selectedId]);
    if (traceMode !== "downstream") {
      upstream.forEach((id) => active.add(id));
    }
    if (traceMode !== "upstream") {
      downstream.forEach((id) => active.add(id));
    }

    return { upstream, downstream, active };
  }, [selectedId, structuralEdges, traceMode]);

  const selectedNode = selectedId ? nodeMap.get(selectedId) ?? null : null;
  const selectedInputs = selectedNode
    ? structuralEdges
        .filter((edge) => edge.target === selectedNode.id)
        .map((edge) => nodeMap.get(edge.source)?.label)
        .filter((label): label is string => Boolean(label))
    : [];
  const selectedOutputs = selectedNode
    ? structuralEdges
        .filter((edge) => edge.source === selectedNode.id)
        .map((edge) => nodeMap.get(edge.target)?.label)
        .filter((label): label is string => Boolean(label))
    : [];

  const statusCounts = useMemo(() => {
    return data.nodes.reduce(
      (counts, node) => {
        counts[node.status] += 1;
        return counts;
      },
      { passed: 0, failed: 0, attention: 0, "not-built": 0 } as Record<
        Status,
        number
      >,
    );
  }, []);

  const fitAll = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    setViewportSize({
      width: viewport.clientWidth,
      height: viewport.clientHeight,
    });
    const horizontalPadding = viewport.clientWidth < 760 ? 38 : 92;
    const verticalPadding = viewport.clientHeight < 700 ? 110 : 150;
    const nextZoom = clamp(
      Math.min(
        (viewport.clientWidth - horizontalPadding) / data.canvas.width,
        (viewport.clientHeight - verticalPadding) / data.canvas.height,
      ),
      MIN_ZOOM,
      0.78,
    );
    setView({
      zoom: nextZoom,
      x: Math.max(24, (viewport.clientWidth - data.canvas.width * nextZoom) / 2),
      y: Math.max(70, (viewport.clientHeight - data.canvas.height * nextZoom) / 2),
    });
  }, []);

  useEffect(() => {
    fitAll();
    window.addEventListener("resize", fitAll);
    return () => window.removeEventListener("resize", fitAll);
  }, [fitAll]);

  const zoomAt = useCallback(
    (nextZoom: number, clientX?: number, clientY?: number) => {
      const viewport = viewportRef.current;
      if (!viewport) return;
      const rect = viewport.getBoundingClientRect();
      const localX = (clientX ?? rect.left + rect.width / 2) - rect.left;
      const localY = (clientY ?? rect.top + rect.height / 2) - rect.top;
      setView((current) => {
        const zoom = clamp(nextZoom, MIN_ZOOM, MAX_ZOOM);
        const worldX = (localX - current.x) / current.zoom;
        const worldY = (localY - current.y) / current.zoom;
        return {
          zoom,
          x: localX - worldX * zoom,
          y: localY - worldY * zoom,
        };
      });
    },
    [],
  );

  const focusNode = useCallback((node: WorkflowNode) => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    const nextZoom = 1.08;
    const inspectorOffset = viewport.clientWidth > 900 ? 170 : 0;
    setView({
      zoom: nextZoom,
      x:
        viewport.clientWidth / 2 -
        inspectorOffset -
        (node.x + node.width / 2) * nextZoom,
      y: viewport.clientHeight / 2 - (node.y + node.height / 2) * nextZoom,
    });
  }, []);

  const handleSearch = useCallback(() => {
    const query = search.trim().toLowerCase();
    if (!query) return;
    const match = data.nodes.find(
      (node) =>
        node.label.toLowerCase().includes(query) ||
        node.description.toLowerCase().includes(query) ||
        node.kicker.toLowerCase().includes(query),
    );
    if (match) {
      setSelectedId(match.id);
      setTraceMode("both");
      focusNode(match);
    }
  }, [focusNode, search]);

  const handleWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    const multiplier = event.deltaY > 0 ? 0.9 : 1.1;
    zoomAt(view.zoom * multiplier, event.clientX, event.clientY);
  };

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (
      target.closest(
        ".atlas-node, .atlas-toolbar, .atlas-inspector, .atlas-controls, .atlas-minimap, .atlas-help",
      )
    ) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      viewX: view.x,
      viewY: view.y,
    };
    setIsDragging(true);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    setView((current) => ({
      ...current,
      x: drag.viewX + event.clientX - drag.clientX,
      y: drag.viewY + event.clientY - drag.clientY,
    }));
  };

  const endPointerDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) {
      dragRef.current = null;
      setIsDragging(false);
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    }
  };

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.tagName === "INPUT") return;
    const panStep = event.shiftKey ? 110 : 48;
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      zoomAt(view.zoom * 1.12);
    } else if (event.key === "-") {
      event.preventDefault();
      zoomAt(view.zoom * 0.88);
    } else if (event.key === "0") {
      event.preventDefault();
      fitAll();
    } else if (event.key === "ArrowLeft") {
      setView((current) => ({ ...current, x: current.x + panStep }));
    } else if (event.key === "ArrowRight") {
      setView((current) => ({ ...current, x: current.x - panStep }));
    } else if (event.key === "ArrowUp") {
      setView((current) => ({ ...current, y: current.y + panStep }));
    } else if (event.key === "ArrowDown") {
      setView((current) => ({ ...current, y: current.y - panStep }));
    } else if (event.key === "Escape") {
      setSelectedId(null);
    }
  };

  const minimapScale = 0.102;
  const minimapViewport = {
    left: (-view.x / view.zoom) * minimapScale,
    top: (-view.y / view.zoom) * minimapScale,
    width: (viewportSize.width / view.zoom) * minimapScale,
    height: (viewportSize.height / view.zoom) * minimapScale,
  };
  const zoomBand = view.zoom >= 1.1 ? "detail" : view.zoom < 0.52 ? "overview" : "normal";

  return (
    <main className="atlas-shell">
      <header className="atlas-toolbar" aria-label="Workflow Atlas toolbar">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span className="brand-copy">
            <strong>{data.project.title}</strong>
            <small>{data.project.subtitle}</small>
          </span>
        </div>

        <div className="atlas-search" role="search">
          <span aria-hidden="true">⌕</span>
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => event.key === "Enter" && handleSearch()}
            placeholder="Find a phase, step, or output…"
            aria-label="Search workflow nodes"
          />
          <button type="button" onClick={handleSearch} aria-label="Search">
            Enter
          </button>
        </div>

        <div className="toolbar-status">
          <span className="status-live-dot" aria-hidden="true" />
          <span>
            <strong>Current map</strong>
            <small>Commit {data.project.commit}</small>
          </span>
          <button
            type="button"
            className="toolbar-icon-button"
            onClick={() => setShowHelp((current) => !current)}
            aria-label="Show canvas help"
            aria-expanded={showHelp}
          >
            ?
          </button>
        </div>
      </header>

      <div className="atlas-summary-strip">
        <span className="summary-path">
          PROJECT <b>›</b> {selectedNode ? selectedNode.kicker : "ALL PHASES"}
        </span>
        <span className="summary-copy">{data.project.summary}</span>
        <span className="summary-evidence">{data.project.evidence}</span>
      </div>

      <div
        ref={viewportRef}
        className={`atlas-viewport ${isDragging ? "is-dragging" : ""}`}
        tabIndex={0}
        role="application"
        aria-label="Interactive project dependency map. Drag to pan, scroll to zoom, and select a node to trace dependencies."
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endPointerDrag}
        onPointerCancel={endPointerDrag}
        onKeyDown={handleKeyDown}
      >
        <div
          className="atlas-stage"
          data-zoom={zoomBand}
          style={{
            width: data.canvas.width,
            height: data.canvas.height,
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`,
          }}
          onDoubleClick={(event) => {
            if ((event.target as HTMLElement).closest(".atlas-node")) return;
            zoomAt(view.zoom * 1.2, event.clientX, event.clientY);
          }}
        >
          {data.phases.map((phase) => (
            <section
              key={phase.id}
              className={`phase-container status-${phase.status}`}
              style={{
                left: phase.x,
                top: phase.y,
                width: phase.width,
                height: phase.height,
              }}
              aria-label={`${phase.label}: ${phase.title}. ${phase.summary}`}
            >
              <div className="phase-title">
                <span className="phase-status-icon" aria-hidden="true">
                  {phase.status === "passed" ? "✓" : "○"}
                </span>
                <div>
                  <b>{phase.label}</b>
                  <strong>{phase.title}</strong>
                </div>
                <small>{phase.summary}</small>
              </div>
              {phase.status === "not-built" && (
                <div className="phase-placeholder">
                  <span aria-hidden="true">⌁</span>
                  <p>
                    Internal workflow will appear here when this phase is
                    planned.
                  </p>
                </div>
              )}
            </section>
          ))}

          {data.lanes.map((lane) => (
            <div
              key={lane.id}
              className={`workflow-lane flow-${lane.flow}`}
              style={{
                left: lane.x,
                top: lane.y,
                width: lane.width,
                height: lane.height,
              }}
              aria-hidden="true"
            >
              <span>{lane.label}</span>
            </div>
          ))}

          <svg
            className="edge-layer"
            width={data.canvas.width}
            height={data.canvas.height}
            aria-hidden="true"
          >
            <defs>
              <marker
                id="arrow-evidence"
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" />
              </marker>
              <marker
                id="arrow-ai"
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" />
              </marker>
              <marker
                id="arrow-validation"
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" />
              </marker>
              <marker
                id="arrow-publication"
                viewBox="0 0 10 10"
                refX="8"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" />
              </marker>
            </defs>
            {data.edges.map((edge) => {
              const source = nodeMap.get(edge.source);
              const target = nodeMap.get(edge.target);
              if (!source || !target) return null;
              const isActive =
                !selectedId ||
                (trace.active.has(edge.source) && trace.active.has(edge.target));
              const isFault =
                source.status === "failed" || target.status === "failed";
              const isFeedback = edge.kind === "feedback";
              const path = connectorPath(source, target, edge);
              const labelX = (source.x + source.width + target.x) / 2;
              const labelY =
                isFeedback
                  ? Math.max(source.y, target.y) + 220
                  : (source.y + source.height / 2 + target.y + target.height / 2) /
                    2;
              return (
                <g
                  key={edge.id}
                  className={`edge-group flow-${edge.flow} ${
                    isActive ? "is-active" : "is-dimmed"
                  } ${isFault ? "is-fault" : ""} ${
                    isFeedback ? "is-feedback" : ""
                  }`}
                >
                  <path
                    className="edge-halo"
                    d={path}
                    fill="none"
                  />
                  <path
                    className="edge-path"
                    d={path}
                    fill="none"
                    markerEnd={`url(#arrow-${edge.flow})`}
                  />
                  {edge.label && (
                    <text x={labelX} y={labelY} className="edge-label">
                      {edge.label}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>

          {data.nodes.map((node) => {
            const isSelected = selectedId === node.id;
            const isDimmed = Boolean(selectedId && !trace.active.has(node.id));
            const direction = trace.upstream.has(node.id)
              ? "upstream"
              : trace.downstream.has(node.id)
                ? "downstream"
                : null;
            return (
              <button
                key={node.id}
                type="button"
                className={`atlas-node executor-${node.executor} status-${node.status} flow-${node.flow} ${
                  isSelected ? "is-selected" : ""
                } ${isDimmed ? "is-dimmed" : ""}`}
                style={{
                  left: node.x,
                  top: node.y,
                  width: node.width,
                  height: node.height,
                }}
                onClick={(event) => {
                  event.stopPropagation();
                  setSelectedId(node.id);
                  setTraceMode("both");
                }}
                onDoubleClick={(event) => {
                  event.stopPropagation();
                  setSelectedId(node.id);
                  focusNode(node);
                }}
                aria-label={`${node.label}. ${statusLabels[node.status]}. ${node.description}`}
              >
                <span className="node-topline">
                  <span className="node-kicker">{node.kicker}</span>
                  <span className="node-status" aria-hidden="true">
                    {node.status === "passed"
                      ? "✓"
                      : node.status === "failed"
                        ? "×"
                        : node.status === "attention"
                          ? "!"
                          : "○"}
                  </span>
                </span>
                <strong>{node.label}</strong>
                <small>{node.description}</small>
                {direction && (
                  <span className={`direction-chip ${direction}`}>
                    {direction === "upstream" ? "INPUT" : "OUTPUT"}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        <div className="atlas-controls" aria-label="Canvas controls">
          <button type="button" onClick={fitAll} aria-label="Fit entire project">
            Fit
          </button>
          <button
            type="button"
            onClick={() => zoomAt(view.zoom * 0.86)}
            aria-label="Zoom out"
          >
            −
          </button>
          <span>{Math.round(view.zoom * 100)}%</span>
          <button
            type="button"
            onClick={() => zoomAt(view.zoom * 1.14)}
            aria-label="Zoom in"
          >
            +
          </button>
        </div>

        <div className="atlas-legend" aria-label="Map legend">
          <strong>Box fill = who did the work</strong>
          <div className="legend-executor-row">
            {(Object.keys(executorLabels) as Executor[]).map((executor) => (
              <span key={executor} className={`executor-${executor}`}>
                <i /> {executorLabels[executor]}
              </span>
            ))}
          </div>
          <strong>Line = information flow</strong>
          <div className="legend-flow-row">
            {(Object.keys(flowLabels) as Flow[]).map((flow) => (
              <span key={flow} className={`flow-${flow}`}>
                <i /> {flowLabels[flow]}
              </span>
            ))}
          </div>
          <strong>Border = result</strong>
          <div className="legend-status-row">
            {(Object.keys(statusLabels) as Status[]).map((status) => (
              <span key={status} className={`status-${status}`}>
                <i /> {statusLabels[status]}
              </span>
            ))}
          </div>
        </div>

        <div className="atlas-statusbar" aria-label="Current workflow totals">
          <span className="status-passed">{statusCounts.passed} passed</span>
          <span className="status-attention">
            {statusCounts.attention} attention
          </span>
          <span className="status-failed">{statusCounts.failed} failed</span>
          <span className="status-not-built">2 future phases</span>
          <b>Last synced {formatDate(data.project.updatedAt)}</b>
        </div>

        <button
          className="atlas-minimap"
          type="button"
          onClick={fitAll}
          aria-label="Fit project using minimap"
        >
          <span className="minimap-label">PROJECT MAP</span>
          <span
            className="minimap-stage"
            style={{
              width: data.canvas.width * minimapScale,
              height: data.canvas.height * minimapScale,
            }}
          >
            {data.phases.map((phase) => (
              <i
                key={phase.id}
                className={`minimap-phase status-${phase.status}`}
                style={{
                  left: phase.x * minimapScale,
                  top: phase.y * minimapScale,
                  width: phase.width * minimapScale,
                  height: phase.height * minimapScale,
                }}
              />
            ))}
            {data.nodes.map((node) => (
              <i
                key={node.id}
                className={`minimap-node executor-${node.executor} status-${node.status}`}
                style={{
                  left: node.x * minimapScale,
                  top: node.y * minimapScale,
                  width: Math.max(node.width * minimapScale, 5),
                  height: Math.max(node.height * minimapScale, 4),
                }}
              />
            ))}
            <i
              className="minimap-viewport"
              style={{
                left: minimapViewport.left,
                top: minimapViewport.top,
                width: minimapViewport.width,
                height: minimapViewport.height,
              }}
            />
          </span>
        </button>

        {selectedNode && (
          <aside
            className={`atlas-inspector status-${selectedNode.status}`}
            aria-label={`Details for ${selectedNode.label}`}
          >
            <div className="inspector-heading">
              <div>
                <span>{selectedNode.kicker}</span>
                <h2>{selectedNode.label}</h2>
              </div>
              <button
                type="button"
                onClick={() => setSelectedId(null)}
                aria-label="Close node details"
              >
                ×
              </button>
            </div>

            <div className="inspector-status">
              <span className="node-status" aria-hidden="true">
                {selectedNode.status === "passed"
                  ? "✓"
                  : selectedNode.status === "failed"
                    ? "×"
                    : selectedNode.status === "attention"
                      ? "!"
                      : "○"}
              </span>
              <div>
                <b>{statusLabels[selectedNode.status]}</b>
                <small>
                  {selectedNode.status === "failed"
                    ? "Downstream work is blocked"
                    : "No active blocker at this step"}
                </small>
              </div>
            </div>

            <div className={`inspector-executor executor-${selectedNode.executor}`}>
              <span aria-hidden="true" />
              Handled by {executorLabels[selectedNode.executor]}
            </div>

            {selectedNode.error ? (
              <div className="fault-card">
                <p>
                  <b>What failed</b>
                  {selectedNode.error.whatFailed}
                </p>
                <p>
                  <b>Expected</b>
                  {selectedNode.error.expected}
                </p>
                <p>
                  <b>Got</b>
                  {selectedNode.error.got}
                </p>
                <p>
                  <b>Next</b>
                  {selectedNode.error.next}
                </p>
              </div>
            ) : (
              <>
                <section className="inspector-section">
                  <h3>What it does</h3>
                  <p>{selectedNode.description}</p>
                </section>
                <section className="inspector-section">
                  <h3>Why it matters</h3>
                  <p>{selectedNode.why}</p>
                </section>
                <section className="inspector-section evidence-section">
                  <h3>Proof</h3>
                  <p>{selectedNode.evidence}</p>
                </section>
              </>
            )}

            <section className="inspector-section dependency-section">
              <h3>Immediate dependencies</h3>
              <div>
                <span>Inputs</span>
                <b>{selectedInputs.length}</b>
                <p>{selectedInputs.join(" • ") || "None"}</p>
              </div>
              <div>
                <span>Outputs</span>
                <b>{selectedOutputs.length}</b>
                <p>{selectedOutputs.join(" • ") || "None"}</p>
              </div>
            </section>

            {selectedNode.history && (
              <section className="inspector-section history-section">
                <h3>Resolved canary history</h3>
                <div className="history-track">
                  {selectedNode.history.map((item, index) => (
                    <span
                      key={`${item}-${index}`}
                      className={
                        index === selectedNode.history!.length - 1
                          ? "is-pass"
                          : "is-fail"
                      }
                    >
                      {item}
                    </span>
                  ))}
                </div>
              </section>
            )}

            <div className="trace-controls" aria-label="Dependency trace mode">
              <button
                type="button"
                className={traceMode === "upstream" ? "is-active" : ""}
                onClick={() => setTraceMode("upstream")}
              >
                ↑ {trace.upstream.size} upstream
              </button>
              <button
                type="button"
                className={traceMode === "downstream" ? "is-active" : ""}
                onClick={() => setTraceMode("downstream")}
              >
                ↓ {trace.downstream.size} downstream
              </button>
              <button
                type="button"
                className={traceMode === "both" ? "is-active" : ""}
                onClick={() => setTraceMode("both")}
              >
                Trace both
              </button>
            </div>
          </aside>
        )}

        {showHelp && (
          <div className="atlas-help" role="dialog" aria-label="Canvas help">
            <div>
              <b>Move</b>
              <span>Drag the canvas or use arrow keys.</span>
            </div>
            <div>
              <b>Zoom</b>
              <span>Scroll, use + / −, or press 0 to fit.</span>
            </div>
            <div>
              <b>Inspect</b>
              <span>Click a box. Double-click to zoom into it.</span>
            </div>
            <div>
              <b>Trace</b>
              <span>Choose upstream, downstream, or both.</span>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
