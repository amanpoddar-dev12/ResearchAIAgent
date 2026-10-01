import { AlertTriangle, Check, Circle, LoaderCircle } from "lucide-react";
import type { ResearchEvent, ResearchStatus } from "../types/research";

export function ResearchTimeline({ events, status }: { events: ResearchEvent[]; status: ResearchStatus }) {
  const visible = events.filter((event) => event.type !== "research_progress").slice(-8);
  return <section className="card" aria-label="Live research activity">
    <div className="flex items-center justify-between gap-3"><h2 className="section-title">Live activity</h2><span className="text-xs text-slate-500">{visible.length} events</span></div>
    <ol className="mt-4 space-y-3" aria-live="polite">{visible.length ? visible.map((event, index) => {
      const terminal = event.type === "complete" || event.type === "research_completed";
      const warning = event.type === "conflict_detected" || event.type === "research_failed";
      return <li key={`${event.timestamp}-${index}`} className="flex gap-3 text-sm"><span className="mt-0.5 shrink-0">{warning ? <AlertTriangle size={15} className="text-amber-500" /> : terminal ? <Check size={15} className="text-emerald-500" /> : index === visible.length - 1 && status === "researching" ? <LoaderCircle size={15} className="animate-spin text-indigo-500 motion-reduce:animate-none" /> : <Circle size={15} className="text-slate-400" />}</span><span className="min-w-0"><span className="block break-words">{event.message}</span><time className="text-xs text-slate-500" dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleTimeString()}</time></span></li>;
    }) : <li className="text-sm text-slate-500">Waiting for the first research event.</li>}</ol>
  </section>;
}
