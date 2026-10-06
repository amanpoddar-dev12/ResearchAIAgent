import { useEffect, useRef } from "react";
import type { Evidence, ResearchSource } from "../types/research";

export function SourcePreview({ source, evidence, onClose }: { source: ResearchSource; evidence: Evidence[]; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => element?.close(); }, []);
  const excerpts = evidence.filter((item) => item.source_id === source.id);
  return <dialog ref={dialog} onCancel={onClose} onClose={() => { if (dialog.current && !dialog.current.open) onClose(); }} aria-labelledby="source-preview-title" className="source-preview w-[min(94vw,42rem)] max-h-[85vh] overflow-auto rounded-2xl bg-white p-6 text-slate-900 shadow-xl backdrop:bg-slate-950/50 dark:bg-slate-900 dark:text-slate-100">
    <div className="flex items-start justify-between gap-4"><h2 id="source-preview-title" className="text-xl font-semibold">{source.title}</h2><button autoFocus className="button-secondary" onClick={onClose}>Close</button></div>
    <p className="my-3 text-sm">{source.domain} · {source.publication_date || "Date unknown"} · {source.source_type || "Type unknown"}</p>
    <a href={source.url} target="_blank" rel="noreferrer" className="break-all text-indigo-600 underline">Open original source</a>
    {source.quality && <section className="my-5"><h3 className="font-semibold">Quality estimate: {Math.round(source.quality.total * 100)}%</h3><dl className="mt-2 grid grid-cols-2 gap-2 text-sm">{(["relevance", "authority", "freshness", "source_type", "evidence_strength"] as const).map((key) => <div key={key}><dt className="capitalize text-slate-500">{key.replace(/_/g, " ")}</dt><dd>{Math.round(source.quality![key] * 100)}%</dd></div>)}</dl><p className="mt-3 text-xs text-slate-500">{source.quality.notes.join(" ")}</p></section>}
    <h3 className="mt-5 font-semibold">Linked evidence excerpts</h3>
    {excerpts.length ? excerpts.map((item) => <blockquote key={item.id} className="my-3 border-l-2 border-indigo-400 pl-3 text-sm"><p>{item.excerpt}</p><footer className="mt-2 text-xs text-slate-500">{item.id} · {item.relation} · {item.strength}</footer></blockquote>) : <p className="mt-2 text-sm text-slate-500">No validated evidence excerpt is linked to this source.</p>}
  </dialog>;
}
