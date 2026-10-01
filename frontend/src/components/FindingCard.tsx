import { BarChart3 } from "lucide-react";
import { Citation } from "./Citation";
import { ConfidenceBar } from "./ConfidenceBar";
import type { Evidence, Finding, ResearchSource } from "../types/research";
export function FindingCard({ finding, sources, evidence, onPreview }: { finding: Finding; sources: ResearchSource[]; evidence: Evidence[]; onPreview: (source: ResearchSource) => void }) {
  return <article className="card">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs font-semibold"><span className="uppercase tracking-wider text-indigo-600">{finding.category}</span><span className="rounded-full bg-slate-100 px-3 py-1 dark:bg-slate-800">{finding.evidence_status || "Unverified"}</span></div>
    <p className="font-medium leading-7">{finding.claim}</p><p className="mt-2 text-sm leading-6 text-slate-500">{finding.explanation}</p>
    {Boolean(finding.depends_on?.length) && <p className="mt-2 text-xs text-slate-500">Depends on: {finding.depends_on!.join(", ")}</p>}
    {finding.dependency_rejected && <p className="mt-2 text-xs text-amber-700">Invalid dependency rejected; this claim remains Unverified.</p>}
    <div className="mt-3 flex gap-2">{finding.source_ids.map((id) => { const index = sources.findIndex((source) => source.id === id); return index >= 0 ? <Citation key={id} n={index + 1} onClick={() => onPreview(sources[index])} /> : null; })}</div>
    <div className="mt-4 flex flex-wrap items-center gap-4"><ConfidenceBar value={finding.confidence} label="Evidence confidence" /><span className="text-xs text-slate-500"><BarChart3 size={15} className="mr-1 inline" />{finding.evidence_ids?.length || 0} validated excerpts · {evidence.filter((item) => finding.evidence_ids?.includes(item.id) && item.relation === "supports").length} supporting · {evidence.filter((item) => finding.evidence_ids?.includes(item.id) && item.relation === "contradicts").length} contradicting</span></div>
    <details className="mt-4 text-xs"><summary className="cursor-pointer font-medium">Why this score?</summary><ul className="mt-2 list-inside list-disc space-y-1 text-slate-500"><li>Reported model confidence: {finding.confidence}</li><li>Evidence status: {finding.evidence_status || "Unverified"}</li><li>Linked evidence: {finding.evidence_ids?.length || 0}</li><li>Source support count: {finding.source_ids.length}</li></ul></details>
  </article>;
}
