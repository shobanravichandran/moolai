import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import { api } from "../api";
import { GROUPS, INK, groupOf, useDarkMode } from "../graphPalette";
import type { GraphData, GraphNode } from "../types";

type PositionedNode = GraphNode & { x?: number; y?: number };

const RADIUS: Record<string, number> = { Decision: 9, Component: 8, Team: 8, Person: 6, PR: 5, Issue: 6 };

function short(node: GraphNode): string {
  if (node.label === "PR") return `#${node.key.split("#")[1]}`;
  if (node.label === "Issue") return `${node.key.split("/")[1]}`;
  if (node.label === "Decision") return node.key;
  return node.name.length > 24 ? `${node.name.slice(0, 23)}…` : node.name;
}

// The subgraph behind the latest answer: decision -> discussion -> implementing PRs -> people -> components.
// Click a node to open it on GitHub.
export default function GraphView({ keys }: { keys: string[] }) {
  const dark = useDarkMode();
  const ink = dark ? INK.dark : INK.light;
  const wrapRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<ForceGraphMethods | undefined>(undefined);
  const [size, setSize] = useState({ width: 300, height: 300 });
  const [data, setData] = useState<GraphData>({ nodes: [], links: [] });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: Math.floor(entry.contentRect.width), height: Math.floor(entry.contentRect.height) }),
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const keyString = keys.join("\n");
  useEffect(() => {
    if (keys.length === 0) {
      setData({ nodes: [], links: [] });
      return;
    }
    setError(null);
    api
      .graph(keys)
      .then(setData)
      .catch((e: Error) => setError(e.message));
    // keyString captures the content of keys; the array identity changes on every render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyString]);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force("charge")?.strength?.(-160);
    fg.d3Force("link")?.distance?.(45);
  }, [data]);

  // react-force-graph mutates nodes/links with positions, so hand it fresh copies per fetch.
  const graph = useMemo(
    () => ({ nodes: data.nodes.map((n) => ({ ...n })), links: data.links.map((l) => ({ ...l })) }),
    [data],
  );
  const present = new Set(data.nodes.map((n) => groupOf(n.label).key));

  return (
    <div className="graph">
      <div className="graph-canvas" ref={wrapRef}>
        {error && <p className="muted">{error}</p>}
        {!error && data.nodes.length === 0 && <p className="muted">Ask something: the graph behind the answer shows up here.</p>}
        <div className="graph-layer">
          <ForceGraph2D
            ref={fgRef}
            graphData={graph}
            width={size.width}
            height={size.height}
            backgroundColor={ink.surface}
            nodeId="id"
            nodeLabel={(n) => `${(n as GraphNode).label}: ${(n as GraphNode).name}`}
            linkLabel={(l) => (l as { type: string }).type}
            linkColor={() => ink.link}
            linkWidth={1}
            linkDirectionalArrowLength={3}
            linkDirectionalArrowRelPos={1}
            cooldownTicks={100}
            onEngineStop={() => fgRef.current?.zoomToFit(400, 30)}
            onNodeClick={(n) => {
              const url = (n as GraphNode).url ?? ((n as GraphNode).label === "Person" ? `https://github.com/${(n as GraphNode).key}` : null);
              if (url) window.open(url, "_blank", "noopener,noreferrer");
            }}
            nodeCanvasObjectMode={() => "replace"}
            nodeCanvasObject={(n, ctx, scale) => {
              const node = n as PositionedNode;
              const group = groupOf(node.label);
              const r = RADIUS[node.label] ?? 5;
              const x = node.x ?? 0;
              const y = node.y ?? 0;
              ctx.beginPath();
              ctx.arc(x, y, r, 0, 2 * Math.PI);
              ctx.fillStyle = dark ? group.dark : group.light;
              ctx.fill();
              ctx.lineWidth = 2 / scale; // surface ring keeps overlapping nodes apart
              ctx.strokeStyle = ink.surface;
              ctx.stroke();
              const fontSize = Math.max(10 / scale, 2.5);
              ctx.font = `${fontSize}px system-ui, -apple-system, "Segoe UI", sans-serif`;
              ctx.textAlign = "center";
              ctx.textBaseline = "top";
              ctx.fillStyle = ink.primary;
              ctx.fillText(short(node), x, y + r + 1.5);
            }}
            nodePointerAreaPaint={(n, color, ctx) => {
              const node = n as PositionedNode;
              ctx.fillStyle = color;
              ctx.beginPath();
              ctx.arc(node.x ?? 0, node.y ?? 0, (RADIUS[node.label] ?? 5) + 3, 0, 2 * Math.PI);
              ctx.fill();
            }}
          />
        </div>
      </div>
      <ul className="legend">
        {GROUPS.filter((g) => present.has(g.key)).map((g) => (
          <li key={g.key}>
            <span className="swatch" style={{ background: dark ? g.dark : g.light }} />
            {g.key} <span className="muted">{g.note}</span>
          </li>
        ))}
        {data.nodes.length > 0 && (
          <li className="muted">
            {data.nodes.length} nodes · {data.links.length} edges
          </li>
        )}
      </ul>
    </div>
  );
}
