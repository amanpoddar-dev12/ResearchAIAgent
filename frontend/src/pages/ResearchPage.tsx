import { useState } from "react";
import { Header } from "../components/Header";
import { ResearchInput } from "../components/ResearchInput";
import { ResearchProgress } from "../components/ResearchProgress";
import { ActivityLog } from "../components/ActivityLog";
import { SourceList } from "../components/SourceList";
import { FindingCard } from "../components/FindingCard";
import { ConflictCard } from "../components/ConflictCard";
import { ResearchReport } from "../components/ResearchReport";
import { EmptyState } from "../components/EmptyState";
import { startResearch, streamResearch } from "../services/api";
import type { Conflict, Depth, Finding, ResearchEvent, ResearchSource, ResearchState } from "../types/research";

export function ResearchPage() {
  const [question, setQuestion] = useState(""); const [depth, setDepth] = useState<Depth>("standard"); const [maxSources, setMaxSources] = useState(10);
  const [events, setEvents] = useState<ResearchEvent[]>([]); const [sources, setSources] = useState<ResearchSource[]>([]); const [findings, setFindings] = useState<Finding[]>([]); const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [report, setReport] = useState(""); const [usage, setUsage] = useState<ResearchState | null>(null); const [status, setStatus] = useState<"idle" | "researching" | "completed" | "error">("idle"); const [error, setError] = useState(""); const [cleanup, setCleanup] = useState<(() => void) | null>(null); const [dark, setDark] = useState(() => localStorage.getItem("theme") === "dark");
  const reset = () => { cleanup?.(); setQuestion(""); setEvents([]); setSources([]); setFindings([]); setConflicts([]); setReport(""); setUsage(null); setError(""); setStatus("idle"); };
  const run = async () => { if (!question.trim() || status === "researching") return; reset(); setQuestion(question); setStatus("researching"); try { const id = await startResearch({ question, depth, max_sources: maxSources }); const stop = streamResearch(id, (event) => { setEvents((old) => [...old, event]); if (event.type === "source_found") setSources((old) => [...old, event.data as ResearchSource]); if (event.type === "finding_extracted") setFindings((old) => [...old, event.data as Finding]); if (event.type === "conflict_detected") setConflicts((old) => [...old, event.data as Conflict]); if (event.type === "complete") { const payload = event.data as { state: ResearchState; report: string }; setUsage(payload.state); setReport(payload.report); setStatus("completed"); } if (event.type === "research_failed") { setError(event.message); setStatus("error"); } }, (err) => { setError(err.message); setStatus("error"); }); setCleanup(() => stop); } catch (err) { setError(err instanceof Error ? err.message : "Could not start research."); setStatus("error"); } };
  const toggleTheme = () => { const next = !dark; setDark(next); document.documentElement.classList.toggle("dark", next); localStorage.setItem("theme", next ? "dark" : "light"); };
  return (
    <div className="app-shell min-h-screen">
      <Header dark={dark} onTheme={toggleTheme} onNew={reset} />
      <main id="main-content" className="mx-auto max-w-7xl overflow-x-hidden px-4 py-8 sm:px-6 sm:py-10 lg:px-8 lg:py-12">
        <ResearchInput value={question} setValue={setQuestion} depth={depth} setDepth={setDepth} maxSources={maxSources} setMaxSources={setMaxSources} disabled={status === "researching"} onSubmit={run} />
        {status === "idle" ? <EmptyState /> : (
          <div className="mt-10 grid min-w-0 gap-6 sm:mt-12 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
            <div className="space-y-6">
              <div className="rounded-2xl border border-indigo-100 bg-indigo-50/80 p-4 text-sm dark:border-indigo-900 dark:bg-indigo-950/30">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2"><span><b>Provider:</b> Gemini</span>{usage && <><span className="min-w-0 max-w-full truncate"><b>Model:</b> {usage.llm_model}</span><span><b>Searches:</b> {usage.searches_performed} / {usage.max_searches}</span><span><b>LLM:</b> {usage.llm_requests_used} / {usage.max_llm_requests}</span><span><b>Sources:</b> {usage.sources.length} / {usage.max_sources}</span></>}</div>
              </div>
              <ResearchProgress events={events} status={status} hasReport={Boolean(report)} />
              {error && <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300"><b>Research failed.</b> {error}<button onClick={run} className="ml-3 underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500">Retry</button></div>}
              {findings.length > 0 && <section><h2 className="mb-3 text-lg font-semibold">Findings</h2><div className="grid gap-4">{findings.map((finding, i) => <FindingCard key={`${finding.claim}-${i}`} finding={finding} />)}</div></section>}
              {conflicts.length > 0 && <section><h2 className="mb-3 text-lg font-semibold">Conflicting information</h2><div className="space-y-3">{conflicts.map((conflict, i) => <ConflictCard key={`${conflict.topic}-${i}`} conflict={conflict} />)}</div></section>}
              {report && <ResearchReport markdown={report} />}
            </div>
            <aside className="min-w-0 space-y-6 lg:sticky lg:top-6 lg:self-start"><ActivityLog events={events} /><SourceList sources={sources} /></aside>
          </div>
        )}
        <footer className="mx-auto mt-12 max-w-3xl border-t border-slate-200/80 py-8 text-center dark:border-slate-800">
          <h2 className="text-sm font-semibold">About the Developer</h2>
          <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-500">Research AI Agent is developed by <strong className="text-slate-700 dark:text-slate-300">Aman Poddar</strong>, a Software Engineer building practical tools for clear, evidence-based research.</p>
        </footer>
      </main>
    </div>
  );
}
