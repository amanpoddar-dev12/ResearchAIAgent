import { useEffect, useReducer, useRef, useState } from "react";
import { Header } from "../components/Header";
import { Sidebar } from "../components/Sidebar";
import { ResearchInput } from "../components/ResearchInput";
import { ResearchProgress } from "../components/ResearchProgress";
import { ActivityLog } from "../components/ActivityLog";
import { SourceList } from "../components/SourceList";
import { SourcePreview } from "../components/SourcePreview";
import { FindingCard } from "../components/FindingCard";
import { ConflictCard } from "../components/ConflictCard";
import { ResearchReport } from "../components/ResearchReport";
import { ResearchGraph } from "../components/ResearchGraph";
import { AuditView } from "../components/AuditView";
import { EmptyState } from "../components/EmptyState";
import { MetricCard } from "../components/MetricCard";
import { ResearchTimeline } from "../components/ResearchTimeline";
import { EvidenceExplorer } from "../components/EvidenceExplorer";
import { ResearchQuality } from "../components/ResearchQuality";
import { ResearchInsights } from "../components/ResearchInsights";
import { startResearch, streamResearch } from "../services/api";
import { emptyFilters } from "../types/research";
import type { ResearchEvent, ResearchSource, ResearchStatus, ResearchMode, SourceFilters, ResearchBudgets } from "../types/research";
import { initialResearchSession, researchReducer } from "../state/researchStore";
import { highQualitySources, relevantSources, researchCoverage, verifiedClaims } from "../scoring/metrics";

export function ResearchPage() {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<ResearchMode>("quick");
  const [maxSources, setMaxSources] = useState(10);
  const [budgets, setBudgets] = useState<ResearchBudgets>({});
  const [filters, setFilters] = useState<SourceFilters>(emptyFilters);
  const [targets, setTargets] = useState("");
  const [session, dispatch] = useReducer(researchReducer, initialResearchSession);
  const [preview, setPreview] = useState<ResearchSource | null>(null);
  const [dark, setDark] = useState(() => localStorage.getItem("research-theme") === "dark");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const cleanup = useRef<(() => void) | null>(null);
  const generation = useRef(0);
  const status: ResearchStatus = session.status;

  useEffect(() => () => { generation.current++; cleanup.current?.(); }, []);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("research-theme", dark ? "dark" : "light");
  }, [dark]);
  useEffect(() => {
    if (status !== "researching") return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [status]);

  const clearResults = () => {
    generation.current++;
    cleanup.current?.();
    cleanup.current = null;
    dispatch({ type: "reset" });
    setPreview(null);
  };
  const reset = () => {
    clearResults(); setQuestion(""); setTargets(""); setFilters(emptyFilters()); setMode("quick"); setMaxSources(10); setBudgets({});
  };
  const run = async () => {
    if (question.trim().length < 3 || status === "researching") return;
    clearResults();
    const current = generation.current;
    dispatch({ type: "reset" });
    // The backend remains the source of truth for progress; no client-side timer or estimate is used.
    dispatch({ type: "research_started", message: "Starting research", timestamp: new Date().toISOString() });
    const items = targets.split("\n").map((item) => item.trim()).filter(Boolean);
    try {
      const id = await startResearch({ question: question.trim(), depth: mode === "quick" ? "quick" : "deep", mode, max_sources: maxSources, filters, budgets,
        target_claims: mode === "fact_check" ? items : [], comparison_items: mode === "compare" ? items : [] });
      if (generation.current !== current) return;
      cleanup.current = streamResearch(id, (event: ResearchEvent) => {
        if (generation.current === current) dispatch(event);
      }, (error) => {
        if (generation.current === current) dispatch({ type: "error", message: error.message });
      });
    } catch (error) {
      if (generation.current === current) dispatch({ type: "error", message: error instanceof Error ? error.message : "Could not start research." });
    }
  };

  const snapshot = session.snapshot;
  return <div className="app-shell min-h-screen">
    <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} onNew={reset} />
    <div className="lg:pl-64">
      <Header dark={dark} onTheme={() => setDark((old) => !old)} onNew={reset} onMenu={() => setSidebarOpen(true)} status={status} mode={mode} />
      <main id="main-content" className="mx-auto max-w-7xl overflow-x-hidden px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div><p className="eyebrow">Research workspace</p><h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">{snapshot?.question.refined_question || question || "Start with a research question"}</h1></div>
          {status !== "idle" && <span className={`badge ${status === "error" ? "badge-error" : status === "completed" ? "badge-success" : "badge-indigo"}`} role="status">{status === "researching" ? "Live research" : status}</span>}
        </div>
        {status === "idle" ? <><ResearchInput value={question} setValue={setQuestion} mode={mode} setMode={setMode} maxSources={maxSources} setMaxSources={setMaxSources} filters={filters} setFilters={setFilters} targets={targets} setTargets={setTargets} disabled={false} onSubmit={run} budgets={budgets} setBudgets={setBudgets} /><EmptyState /></> :
          <div className="research-results grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(300px,380px)]">
            <div className="min-w-0 space-y-6">
              <ResearchProgress events={session.events} status={status} hasReport={Boolean(session.report)} mode={mode} sources={session.sources} />
              <ResearchTimeline events={session.events} status={status} />
              {snapshot && <div className="metric-grid">
                <MetricCard label="Sources found" value={session.sources.length} description="Number of sources discovered in this session." />
                <MetricCard label="Relevant sources" value={relevantSources(session.sources).value ?? "Not available"} description={relevantSources(session.sources).formula} />
                <MetricCard label="High-quality sources" value={highQualitySources(session.sources).value ?? "Not available"} description={highQualitySources(session.sources).formula} />
                <MetricCard label="Claims" value={session.findings.length} description="Number of findings reported by the research state." />
                <MetricCard label="Verified claims" value={verifiedClaims(snapshot).value ?? "Not available"} description={verifiedClaims(snapshot).formula} />
                <MetricCard label="Conflicts" value={session.conflicts.length} description="Conflicts detected from linked claims and evidence." />
                <MetricCard label="Research coverage" value={researchCoverage(snapshot).value === null ? "Not available" : `${Math.round(researchCoverage(snapshot).value! * 100)}%`} description={researchCoverage(snapshot).formula} />
                <MetricCard label="Evidence coverage" value="Not available" description="Not available: the backend does not report an aggregate evidence coverage metric." />
              </div>}
              {status === "researching" && <p className="text-xs text-slate-500" role="timer">Elapsed time: {Math.floor(elapsed / 60)}m {elapsed % 60}s</p>}
              {session.error && <div role="alert" className="error-state"><p className="font-medium">Research interrupted</p><p className="mt-1 text-sm">{session.error}</p><button onClick={run} className="button-secondary mt-3">Retry Research</button></div>}
              {snapshot && <div className="card text-sm"><p><strong>Research scope:</strong> {snapshot.question.refined_question || snapshot.question.question}</p>{snapshot.question.assumptions?.map((assumption) => <p key={assumption} className="mt-2 text-xs text-slate-500">Assumption: {assumption}</p>)}</div>}
              {snapshot?.graph && <ResearchGraph graph={snapshot.graph} sources={session.sources} onPreview={setPreview} />}
              {session.findings.length > 0 && <section id="findings"><h2 className="mb-3 text-lg font-semibold">Findings and evidence</h2><div className="grid gap-4">{session.findings.map((finding, index) => <FindingCard key={finding.id || index} finding={finding} sources={session.sources} evidence={session.evidence} onPreview={setPreview} />)}</div></section>}
              {session.evidence.length > 0 && <EvidenceExplorer evidence={session.evidence} findings={session.findings} sources={session.sources} onPreview={setPreview} />}
              {session.conflicts.length > 0 && <section id="conflicts"><h2 className="mb-3 text-lg font-semibold">Conflicts</h2><div className="space-y-3">{session.conflicts.map((conflict, index) => <ConflictCard key={index} conflict={conflict} sources={session.sources} evidence={session.evidence} onPreview={setPreview} />)}</div></section>}
              {snapshot && <ResearchQuality state={snapshot} />}
              {snapshot && <ResearchInsights state={snapshot} findings={session.findings} />}
              {snapshot && Boolean(snapshot.citation_rejections?.length) && <details className="card"><summary className="cursor-pointer text-sm font-medium">Citation validation log ({snapshot.citation_rejections!.length})</summary></details>}
              {session.report && <ResearchReport markdown={session.report} sources={session.sources} onPreview={setPreview} />}
            </div>
            <aside className="min-w-0 space-y-6"><SourceList sources={session.sources} onPreview={setPreview} />{snapshot?.audit_log && <AuditView entries={snapshot.audit_log} />}<ActivityLog events={session.events} /></aside>
          </div>}
        <footer className="mx-auto mt-12 max-w-3xl border-t border-slate-200 py-8 text-center dark:border-slate-800"><p className="text-xs text-slate-500">Session-scoped research. Metrics are shown only when supported by the research state.</p></footer>
      </main>
    </div>
    {preview && <SourcePreview source={preview} evidence={session.evidence} onClose={() => setPreview(null)} />}
  </div>;
}
