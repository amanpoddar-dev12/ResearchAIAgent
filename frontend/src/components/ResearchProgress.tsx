import { Check, Circle, LoaderCircle } from "lucide-react";
import { ResearchCompanion, type CompanionTask } from "./ResearchCompanion";
import { modes } from "../types/research";
import type { ResearchEvent, ResearchSource, ResearchMode, ResearchStatus } from "../types/research";

const phases = [{ id: "planning", label: "Plan" }, { id: "search", label: "Sources" }, { id: "evidence", label: "Evidence" }, { id: "conflicts", label: "Conflicts" }, { id: "synthesis", label: "Report" }];
export function ResearchProgress({ events, status, hasReport, mode, sources }: { events: ResearchEvent[]; status: ResearchStatus; hasReport: boolean; mode: ResearchMode; sources: ResearchSource[] }) {
  const latest = [...events].reverse().find((event) => event.progress !== undefined);
  const finished = status === "completed" && hasReport;
  const percent = finished ? 100 : Math.min(latest?.progress ?? 0, 99);
  const phase = latest?.phase || "planning";
  const activeIndex = phase === "complete" ? phases.length : phases.findIndex((item) => item.id === phase);
  const companionTask: CompanionTask = phase === "search" || phase === "conflicts" || phase === "synthesis" ? phase : phase === "evidence" ? events.slice(-3).some(event => event.type === "finding_extracted" || event.type === "finding_updated") ? "finding" : "evidence" : "planning";
  const currentActivity = events.length ? events[events.length - 1].message : "Waiting for research events";
  const analyzed = sources.filter((source) => events.some((event) => event.type === "source_analyzed" && (event.data as { source_id?: string })?.source_id === source.id)).length;
  return <section className="card" aria-label="Research progress">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="section-title">Research timeline</h2><span className="text-sm">{modes.find((item) => item.value === (latest?.mode || mode))?.label || mode} · {status === "error" ? "Interrupted" : finished ? "Complete" : phase} · {percent}%</span></div>
    {status === "researching" && <ResearchCompanion task={companionTask} />}
    <div className="mt-4 h-2 overflow-hidden rounded-full bg-muted dark:bg-surface" role="progressbar" aria-label="Research progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><div className="h-full bg-primary transition-colors motion-reduce:transition-none" style={{ width: percent + "%" }} /></div>
    <p className="mt-4 text-sm text-muted-foreground dark:text-muted-foreground" aria-live="polite">{currentActivity}</p>
    <ol className="mt-5 flex flex-wrap gap-4">{phases.map((item, index) => <li key={item.id} className="flex items-center gap-1.5 text-xs">{finished || index < activeIndex ? <Check size={15} className="text-success" /> : index === activeIndex && status === "researching" ? <LoaderCircle size={15} className="animate-spin motion-reduce:animate-none" /> : <Circle size={15} />}{item.label}</li>)}</ol>
    <div className="mt-4 grid gap-2 text-xs text-muted-foreground sm:grid-cols-3"><span>Sources discovered: {sources.length}</span><span>Sources analyzed: {analyzed}</span><span>Claims extracted: {new Set(events.filter((event) => event.type === "finding_extracted" || event.type === "finding_updated").map((event) => (event.data as { id?: string })?.id).filter(Boolean)).size}</span></div>
    {sources.length > 0 && <details className="mt-4 text-sm"><summary className="cursor-pointer">Per-source progress ({sources.length})</summary><ul className="mt-3 max-h-52 space-y-2 overflow-auto">{sources.map((source) => {
      const analyzed = events.find((event) => event.type === "source_analyzed" && (event.data as { source_id: string })?.source_id === source.id);
      const count = (analyzed?.data as { evidence_count?: number })?.evidence_count;
      const skipped = (analyzed?.data as { status?: string })?.status === "below_relevance_threshold";
      return <li key={source.id} className="flex flex-wrap justify-between gap-1"><span className="truncate">{source.title}</span><span className="text-xs text-muted-foreground">{skipped ? "Skipped: low relevance" : analyzed ? "Analyzed · " + count + " excerpts" : source.quality ? "Quality evaluated" : "Discovered"}</span></li>;
    })}</ul></details>}
  </section>;
}
