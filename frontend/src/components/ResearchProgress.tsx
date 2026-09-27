import { useEffect, useState } from "react";
import { Check, Circle, LoaderCircle } from "lucide-react";
import type { ResearchEvent } from "../types/research";

const steps = [
  { label: "Understanding question", starts: ["research_started"], completes: ["planning_started"] },
  { label: "Creating research plan", starts: ["planning_started"], completes: ["planning_completed"] },
  { label: "Searching the web", starts: ["search_started"], completes: ["search_completed", "source_found"] },
  { label: "Analyzing sources", starts: ["analysis_started", "finding_extracted"], completes: ["gap_detected", "synthesis_started"] },
  { label: "Checking conflicts", starts: ["analysis_started", "conflict_detected"], completes: ["synthesis_started"] },
  { label: "Writing final report", starts: ["synthesis_started"], completes: ["report_generated", "research_completed"] },
];

const progressFor = (types: string[]) => {
  if (types.includes("complete") || types.includes("research_completed")) return 100;
  if (types.includes("report_generated")) return 95;
  if (types.includes("synthesis_started")) return 86;
  if (types.includes("analysis_started") || types.includes("finding_extracted") || types.includes("gap_detected")) return 65;
  if (types.includes("search_started") || types.includes("source_found") || types.includes("search_completed")) return 40;
  if (types.includes("planning_started") || types.includes("planning_completed")) return 15;
  return types.length ? 10 : 0;
};

export function ResearchProgress({ events, status, hasReport }: { events: ResearchEvent[]; status: "idle" | "researching" | "completed" | "error"; hasReport: boolean }) {
  const types = events.map((event) => event.type);
  const latest = events.length ? events[events.length - 1].type : undefined;
  const finished = status === "completed" && hasReport;
  const target = finished ? 100 : Math.min(progressFor(types), 99);
  const [percent, setPercent] = useState(0);
  useEffect(() => {
    if (status === "error") return;
    const timer = window.setInterval(() => setPercent((current) => current < target ? current + 1 : current), 180);
    return () => window.clearInterval(timer);
  }, [status, target]);
  return <div className="card">
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0"><h2 className="section-title">Research Progress</h2><p className="mt-1 text-xs text-slate-500">Live updates from the research agent</p></div>
      <span className={`shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${finished ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300" : events.length ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"}`}>{finished ? "Complete" : events.length ? `${percent}%` : "Ready"}</span>
    </div>
    <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800" role="progressbar" aria-label="Research progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><div className="h-full rounded-full bg-indigo-600 transition-[width] duration-300 dark:bg-indigo-400" style={{ width: `${percent}%` }} /></div>
    <div className="mt-6 space-y-4" aria-live="polite">
      {steps.map((step, index) => {
        const done = step.completes.some((type) => types.includes(type)) || (finished && index < steps.length);
        const current = !done && (step.starts.includes(latest || "") || (index === 0 && events.length > 0));
        return <div className={`flex items-center gap-3 text-sm ${done ? "text-emerald-600 dark:text-emerald-400" : current ? "font-medium text-indigo-600 dark:text-indigo-400" : "text-slate-400"}`} key={step.label}>
          {done ? <Check aria-hidden="true" size={17} /> : current ? <LoaderCircle aria-hidden="true" className="animate-spin motion-reduce:animate-none" size={17} /> : <Circle aria-hidden="true" size={17} />}
          <span>{step.label}{current && !finished ? `... ${percent}%` : ""}</span>
        </div>;
      })}
    </div>
  </div>;
}
