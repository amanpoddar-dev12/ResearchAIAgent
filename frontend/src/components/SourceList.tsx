import { useState } from "react";
import { Globe, Search } from "lucide-react";
import type { ResearchSource } from "../types/research";

export function SourceList({ sources, onPreview }: { sources: ResearchSource[]; onPreview: (source: ResearchSource) => void }) {
  const [sort, setSort] = useState("quality");
  const [domain, setDomain] = useState("");
  const [type, setType] = useState("");
  const [quality, setQuality] = useState(0);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [query, setQuery] = useState("");
  const [qualityFilter, setQualityFilter] = useState("");
  const visible = sources.filter((source) => {
    const date = source.publication_date ? Date.parse(source.publication_date) : NaN;
    return (!query || `${source.title} ${source.domain}`.toLowerCase().includes(query.toLowerCase())) &&
      (!qualityFilter || (qualityFilter === "high" ? (source.quality?.total ?? 0) >= 0.7 : qualityFilter === "conflicting" ? false : source.source_type === qualityFilter)) &&
      (!domain || source.domain === domain) && (!type || source.source_type === type) &&
      (source.quality?.total ?? 0) * 100 >= quality &&
      (!from || Number.isFinite(date) && date >= Date.parse(from)) &&
      (!to || Number.isFinite(date) && date < Date.parse(to) + 86400000);
  }).sort((left, right) => sort === "domain" ? left.domain.localeCompare(right.domain) : sort === "type" ? (left.source_type || "").localeCompare(right.source_type || "") : sort === "date" ? (Date.parse(right.publication_date || "") || 0) - (Date.parse(left.publication_date || "") || 0) : (right.quality?.total ?? 0) - (left.quality?.total ?? 0));
  return <section className="card"><h2 className="section-title"><Globe size={17} /> Source explorer <span className="count">{visible.length} / {sources.length}</span></h2>
    <div className="mt-4 grid grid-cols-2 gap-2">
      <label className="col-span-2 text-xs"><span className="sr-only">Search sources</span><div className="flex items-center gap-2"><Search size={14} /><input aria-label="Search sources" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search title or domain" className="select w-full" /></div></label>
      <label className="text-xs">Category<select aria-label="Filter source category" value={qualityFilter} onChange={(event) => setQualityFilter(event.target.value)} className="select mt-1 w-full"><option value="">All</option><option value="high">High quality</option><option value="official">Official</option><option value="academic">Academic</option><option value="news">News</option><option value="technical">Technical</option><option value="conflicting">Conflicting</option></select></label>
      <label className="text-xs">Sort by<select aria-label="Sort sources" value={sort} onChange={(event) => setSort(event.target.value)} className="select mt-1 w-full"><option value="quality">Quality</option><option value="domain">Domain</option><option value="date">Newest</option><option value="type">Type</option></select></label>
      <label className="text-xs">Minimum quality %<input aria-label="Minimum quality" type="number" min={0} max={100} value={quality} onChange={(event) => setQuality(Math.max(0, Math.min(100, Number(event.target.value))))} className="select mt-1 w-full" /></label>
      <select aria-label="Filter source domain" value={domain} onChange={(event) => setDomain(event.target.value)} className="select"><option value="">All domains</option>{[...new Set(sources.map((source) => source.domain))].sort().map((item) => <option key={item}>{item}</option>)}</select>
      <select aria-label="Filter source type" value={type} onChange={(event) => setType(event.target.value)} className="select"><option value="">All types</option>{[...new Set(sources.map((source) => source.source_type).filter(Boolean))].sort().map((item) => <option key={item}>{item}</option>)}</select>
      <label className="min-w-0 text-xs">From<input aria-label="Explorer date from" type="date" value={from} onChange={(event) => setFrom(event.target.value)} className="select mt-1 w-full" /></label>
      <label className="min-w-0 text-xs">Through<input aria-label="Explorer date through" type="date" value={to} onChange={(event) => setTo(event.target.value)} className="select mt-1 w-full" /></label>
    </div>
    <div className="mt-4 max-h-[36rem] space-y-3 overflow-auto">{visible.map((source) => <button type="button" onClick={() => onPreview(source)} key={source.id} className="source-item w-full text-left">
      <div className="flex items-start gap-3"><span className="source-avatar" aria-hidden="true">{source.domain.slice(0, 1).toUpperCase() || "?"}</span><div className="min-w-0 flex-1"><div className="flex items-start gap-2"><span className="source-number">{sources.findIndex((item) => item.id === source.id) + 1}</span><h3 className="min-w-0 truncate text-sm font-medium">{source.title}</h3></div><p className="mt-1 truncate text-xs text-slate-500">{source.domain}</p><p className="mt-2 text-xs text-slate-500">{source.publication_date || "Date unknown"} · {source.source_type || "other"}</p><p className="mt-1 text-xs font-medium text-indigo-600">{source.quality ? Math.round(source.quality.total * 100) + "% quality estimate" : "Quality not evaluated"}</p></div></div>
    </button>)}{!visible.length && <p className="text-sm text-slate-500">No sources match these explorer filters.</p>}</div>
  </section>;
}
