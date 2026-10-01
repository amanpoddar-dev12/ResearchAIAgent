import { useState } from "react";
import type { ResearchGraphData, ResearchSource } from "../types/research";

const columns = ["question", "claim", "evidence", "source", "conflict"];
export function ResearchGraph({ graph, sources, onPreview }: { graph: ResearchGraphData; sources: ResearchSource[]; onPreview: (source: ResearchSource) => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const groups = columns.map((type) => graph.nodes.filter((node) => node.type === type));
  const positions = new Map(groups.flatMap((nodes, column) => nodes.map((node, row) => [node.id, { x: column * 220 + 10, y: row * 80 + 40 }] as const)));
  const height = Math.max(150, ...groups.map((nodes) => nodes.length * 80 + 60));
  const node = graph.nodes.find((item) => item.id === selected);
  const connected = graph.edges.filter((edge) => edge.source === selected || edge.target === selected);
  return <section className="card min-w-0" aria-label="Research evidence graph">
    <h2 className="text-lg font-semibold">Research graph</h2>
    <p className="mt-1 text-xs text-slate-500">Select a node to inspect its evidence path. Dashed edges indicate claim dependencies.</p>
    <div className="mt-4 max-h-[480px] overflow-auto rounded-lg border border-slate-200 dark:border-slate-700">
      <svg width="1110" height={height} role="group" aria-label="Question to claims, evidence, sources and conflicts" className="text-slate-700 dark:text-slate-200">
        <defs><marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" /></marker></defs>
        {columns.map((type, column) => <text key={type} x={column * 220 + 10} y={20} fill="currentColor" fontSize="12">{type.toUpperCase()}</text>)}
        {graph.edges.map((edge, index) => {
          const start = positions.get(edge.source), end = positions.get(edge.target);
          if (!start || !end) return null;
          const active = edge.source === selected || edge.target === selected;
          const sameColumn = start.x === end.x;
          return <path key={index} d={sameColumn ? `M ${start.x + 195} ${start.y + 28} C ${start.x + 216} ${start.y + 28}, ${end.x + 216} ${end.y + 28}, ${end.x + 195} ${end.y + 28}` : `M ${start.x + 195} ${start.y + 28} L ${end.x} ${end.y + 28}`} stroke={active ? "#6366f1" : "#94a3b8"} strokeWidth={active ? 2 : 1} strokeDasharray={edge.type === "depends_on" ? "4 3" : undefined} fill="none" markerEnd="url(#graph-arrow)"><title>{`${edge.source} → ${edge.target}: ${edge.type}`}</title></path>;
        })}
        {graph.nodes.map((item) => {
          const position = positions.get(item.id)!;
          const select = () => setSelected(item.id);
          return <g key={item.id} role="button" tabIndex={0} aria-label={`${item.id}: ${item.label}${item.status ? `, ${item.status}` : ""}`} onClick={select} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } }} className="cursor-pointer outline-indigo-500">
            <rect x={position.x} y={position.y} width={195} height={57} rx={8} fill={item.id === selected ? "#e0e7ff" : "#f8fafc"} stroke={item.id === selected ? "#6366f1" : "#cbd5e1"} />
            <text x={position.x + 8} y={position.y + 18} fontSize="11" fill="#334155">{item.id} {item.status ? `· ${item.status}` : ""}</text>
            <text x={position.x + 8} y={position.y + 39} fontSize="11" fill="#334155">{item.label.length > 27 ? item.label.slice(0, 27) + "…" : item.label}</text><title>{item.label}</title>
          </g>;
        })}
      </svg>
    </div>
    {node && <div className="mt-3 space-y-2 text-sm"><p className="break-words"><strong>{node.id}</strong>: {node.label}</p>{node.status && <p>{node.status}</p>}
      {node.type === "source" && <button className="text-indigo-600 underline" onClick={() => { const source = sources.find((item) => item.id === node.id); if (source) onPreview(source); }}>Preview source</button>}
      <ul className="space-y-1 text-xs">{connected.map((edge, index) => <li key={index}>{edge.source} → {edge.target}: {edge.type.replace(/_/g, " ")}</li>)}</ul>
    </div>}
  </section>;
}