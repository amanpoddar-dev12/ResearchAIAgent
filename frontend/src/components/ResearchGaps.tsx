import { CircleHelp, Search } from "lucide-react";
import type { ResearchGap } from "../types/research";

export function ResearchGaps({ gaps }: { gaps: ResearchGap[] }) {
  if (!gaps.length) return null;
  return <section id="research-gaps" className="card" aria-label="Research gaps"><div className="flex items-center justify-between gap-3"><h2 className="section-title"><CircleHelp size={17} /> Research gaps <span className="count">{gaps.length}</span></h2><span className="text-xs text-slate-500">Open questions from the research state</span></div><div className="mt-4 grid gap-3 sm:grid-cols-2">{gaps.map((gap) => <article key={gap.gap_id} className="rounded-xl border border-slate-200 p-4 dark:border-slate-800"><div className="flex items-center justify-between gap-2"><span className="text-xs font-semibold text-indigo-600">{gap.gap_id}</span><span className="badge">{gap.importance} importance</span></div><h3 className="mt-2 text-sm font-medium">{gap.description}</h3><p className="mt-2 text-xs leading-5 text-slate-500">{gap.reason}</p><p className="mt-3 flex gap-2 text-xs text-slate-600 dark:text-slate-300"><Search size={14} className="shrink-0" /><span><strong>Recommended:</strong> {gap.recommended_search}</span></p></article>)}</div></section>;
}
