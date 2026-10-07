import { useEffect, useRef } from "react";
import type { Evidence, Finding, ResearchSource } from "../types/research";

export function SourcePreview({ source, evidence, findings = [], onClose }: { source: ResearchSource; evidence: Evidence[]; findings?: Finding[]; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => element?.close(); }, []);
  const excerpts = evidence.filter((item) => item.source_id === source.id);
  return <dialog ref={dialog} onCancel={onClose} onClose={() => { if (dialog.current && !dialog.current.open) onClose(); }} aria-labelledby="source-preview-title" className="source-preview w-[min(94vw,42rem)] max-h-[85vh] overflow-auto rounded-xl bg-surface p-6 text-foreground shadow-soft backdrop:bg-background/50 dark:bg-surface dark:text-foreground">
    <div className="flex items-start justify-between gap-4"><h2 id="source-preview-title" className="text-xl font-medium">{source.title}</h2><button autoFocus className="button-secondary" onClick={onClose}>Close</button></div>
    <div className="my-4 grid gap-3 rounded-xl border border-border p-4 sm:grid-cols-3 text-sm"><div><p className="text-xs text-muted-foreground">Publisher</p><p className="mt-1 break-all">{source.domain}</p></div><div><p className="text-xs text-muted-foreground">Publication date</p><p className="mt-1">{source.publication_date || "Date unknown"}</p></div><div><p className="text-xs text-muted-foreground">Source type</p><p className="mt-1">{source.source_type || "Type unknown"}</p></div></div>
    <a href={source.url} target="_blank" rel="noreferrer" className="break-all text-link underline">Open original source</a>
    {source.quality && <section className="my-5"><h3 className="font-medium">Quality estimate: {Math.round(source.quality.total * 100)}%</h3><dl className="mt-2 grid grid-cols-2 gap-2 text-sm">{(["relevance", "authority", "freshness", "source_type", "evidence_strength"] as const).map((key) => <div key={key}><dt className="capitalize text-muted-foreground">{key.replace(/_/g, " ")}</dt><dd>{Math.round(source.quality![key] * 100)}%</dd></div>)}</dl><p className="mt-3 text-xs text-muted-foreground">{source.quality.notes.join(" ")}</p></section>}
    <h3 className="mt-6 font-medium">Supporting passages</h3><p className="mt-1 text-xs text-muted-foreground">Inspect each excerpt and its reported relationship to the claim.</p>
    {excerpts.length ? excerpts.map((item) => {
      const claim = findings.find((finding) => finding.id === item.claim_id);
      return <section key={item.id} className="mt-4 rounded-xl border border-border p-4"><div className="flex flex-wrap items-center gap-2"><span className="badge">{item.relation}</span><span className="badge">{claim?.evidence_status || "Status not reported"}</span><span className="text-xs text-muted-foreground">{item.id} · {item.strength} evidence</span></div><blockquote className="mt-3 border-l-2 border-link bg-accent/10 p-3 text-sm leading-6">{item.excerpt}</blockquote>{claim && <p className="mt-3 text-sm"><span className="text-muted-foreground">Linked claim: </span>{claim.claim}</p>}</section>;
    }) : <p className="mt-3 text-sm text-muted-foreground">No validated evidence excerpt is linked to this source.</p>}

  </dialog>;
}
