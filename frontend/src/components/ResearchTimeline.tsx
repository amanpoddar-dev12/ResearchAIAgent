import { AlertTriangle, Check, Circle, LoaderCircle } from "lucide-react";
import type { ResearchEvent, ResearchStatus } from "../types/research";

export function ResearchTimeline({ events, status }: { events: ResearchEvent[]; status: ResearchStatus }) {
  const visible = events.filter((event) => event.type !== "research_progress").slice(-8);
  const stages = [
    { label: 'Plan', types: ['planning_started', 'planning_completed', 'question_refined'] },
    { label: 'Find sources', types: ['search_started', 'search_completed', 'source_found'] },
    { label: 'Review evidence', types: ['source_analyzed', 'evidence_found', 'evidence_linked', 'finding_extracted', 'claim_extracted', 'analysis_started', 'verification_started', 'verification_completed', 'conflict_detected'] },
    { label: 'Write report', types: ['synthesis_started', 'report_generated'] },
  ];
  const limited = events.some(event => event.type === "gap_detected");
  const reached = Math.max(0, ...events.map(event => stages.findIndex(stage => stage.types.includes(event.type))));
  return <section className="card" aria-label="Live research activity">
    <div className="flex items-center justify-between gap-3"><h2 className="section-title">Live activity</h2><span className="text-xs text-muted-foreground">{visible.length} events</span></div>
    {status === 'completed' && limited && <p className="mt-3 text-xs text-warning">Completed with limits: some discovery, evidence or review steps remain incomplete. See the report methodology and audit.</p>}
    <ol className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Research steps">{stages.map((stage, index) => {
      const state = status === 'completed' ? 'done' : index < reached ? 'done' : index > reached || status === 'idle' ? 'pending' : status === 'error' ? 'failed' : 'running';
      const Icon = state === 'done' ? Check : state === 'failed' ? AlertTriangle : state === 'running' ? LoaderCircle : Circle;
      return <li key={stage.label} aria-current={state === 'running' ? 'step' : undefined} className={`rounded-lg border p-3 ${state === 'running' ? 'border-primary/40 bg-primary/5' : 'border-border'}`}><Icon size={16} aria-hidden="true" className={state === 'done' ? 'text-success' : state === 'failed' ? 'text-destructive' : 'text-muted-foreground'} /><p className="mt-2 text-xs font-medium">{stage.label}</p><p className="mt-1 text-xs capitalize text-muted-foreground">{state}</p></li>;
    })}</ol>
    <ol className="mt-4 space-y-3" aria-live="polite">{visible.length ? visible.map((event, index) => {
      const terminal = event.type === "complete" || event.type === "research_completed";
      const warning = event.type === "conflict_detected" || event.type === "research_failed" || event.type === "gap_detected";
      return <li key={`${event.timestamp}-${index}`} className="flex gap-3 text-sm"><span className="mt-0.5 shrink-0">{warning ? <AlertTriangle size={15} className="text-warning" /> : terminal ? <Check size={15} className="text-success" /> : index === visible.length - 1 && status === "researching" ? <LoaderCircle size={15} className="animate-spin text-link motion-reduce:animate-none" /> : <Circle size={15} className="text-muted-foreground" />}</span><span className="min-w-0"><span className="block break-words">{event.message}</span><time className="text-xs text-muted-foreground" dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleTimeString()}</time></span></li>;
    }) : <li className="text-sm text-muted-foreground">Waiting for the first research event.</li>}</ol>
  </section>;
}
