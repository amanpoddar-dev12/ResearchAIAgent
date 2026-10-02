import { ExternalLink, Link2, Copy } from "lucide-react";
import { useMemo, useState } from "react";
import type { Evidence, Finding, ResearchSource } from "../types/research";

export function EvidenceExplorer({ evidence, findings, sources, onPreview }: { evidence: Evidence[]; findings: Finding[]; sources: ResearchSource[]; onPreview: (source: ResearchSource) => void }) {
  const [filter, setFilter] = useState<"all" | "supports" | "contradicts" | "context">("all");
  const claimFor = (item: Evidence) => findings.find((finding) => finding.evidence_ids?.includes(item.id));
  const visible = useMemo(() => filter === "all" ? evidence : evidence.filter((item) => item.relation === filter), [evidence, filter]);
  return <section id="evidence" className="card">
    <div className="flex items-center justify-between gap-3"><h2 className="section-title"><Link2 size={17} /> Evidence explorer <span className="count">{evidence.length}</span></h2><span className="text-xs text-slate-500">Validated excerpts only</span></div>
    <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="Evidence filters">{(["all", "supports", "contradicts", "context"] as const).map((value) => <button key={value} type="button" className={`chip ${filter === value ? "border-indigo-400 bg-indigo-50 text-indigo-700 dark:border-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300" : ""}`} onClick={() => setFilter(value)}>{value === "all" ? "All" : value === "supports" ? "Supporting" : value === "contradicts" ? "Contradicting" : "Contextual"}</button>)}</div>
    <div className="mt-4 space-y-3">{visible.length ? visible.map((item) => {
      const source = sources.find((candidate) => candidate.id === item.source_id);
      const claim = claimFor(item);
      return <article key={item.id} className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
        <div className="flex flex-wrap items-center justify-between gap-2"><span className={`badge ${item.relation === "contradicts" ? "badge-error" : item.relation === "supports" ? "badge-success" : ""}`}>{item.relation}</span><span className="text-xs text-slate-500">{item.id} · {item.evidence_type || item.strength} · relevance {item.relevance_score === undefined ? "Not available" : `${Math.round(item.relevance_score * 100)}%`}</span></div>
        <blockquote className="mt-3 border-l-2 border-indigo-300 pl-3 text-sm leading-6">“{item.excerpt}”</blockquote>
        <p className="mt-3 text-xs text-slate-500"><strong>Related claim:</strong> {claim?.claim || "Not available"}</p>
        {source && <div className="mt-3 flex flex-wrap items-center gap-2 text-xs"><button className="button-secondary" onClick={() => onPreview(source)}><ExternalLink size={14} /> View source</button><a className="button-secondary" href={source.url} target="_blank" rel="noreferrer">Open original</a><button className="button-secondary" onClick={() => void navigator.clipboard?.writeText(`[${item.id}] ${item.excerpt}`)}><Copy size={14} /> Copy citation</button><span className="text-slate-500">{source.domain} · {source.source_type || "Type not available"} · {source.publication_date || "Date not available"}</span></div>}
      </article>;
    }) : <p className="text-sm text-slate-500">{evidence.length ? "No evidence matches this filter." : "No validated evidence has been reported yet."}</p>}</div>
  </section>;
}
