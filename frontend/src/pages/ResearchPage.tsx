import { gapLabel } from '../ui/researchPresentation';
import { cloudEnabled } from '../services/auth';
import { useTheme } from "../theme";
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
import { ClaimExplorer } from "../components/ClaimExplorer";
import { ResearchGaps } from "../components/ResearchGaps";
import { generalChatId as getGeneralChatId } from "../storage/chatStorage";
import { ResearchChat } from "../components/ResearchChat";
import { startResearch, streamResearch, cancelResearch } from "../services/api";
import { emptyFilters } from "../types/research";
import type { ResearchEvent, ResearchSource, ResearchStatus, ResearchMode, SourceFilters, ResearchBudgets } from "../types/research";
import { initialResearchSession, researchReducer } from "../state/researchStore";
import { restoreResearch } from "../state/researchStore";
import { deleteSavedResearch, clearSavedResearch, listSavedResearch, saveResearch, toSavedResearch, type SavedResearch } from "../storage/researchStorage";
import { citationCoverage, evidenceCount, highQualitySources, relevantSources, researchCoverage, verifiedClaims } from "../scoring/metrics";
export function ResearchPage() {
  const [generalChatId] = useState(getGeneralChatId);
  const [activeTab, setActiveTab] = useState<"research" | "assistant">("research");
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<ResearchMode>("quick");
  const [maxSources, setMaxSources] = useState(10);
  const [budgets, setBudgets] = useState<ResearchBudgets>({});
  const [filters, setFilters] = useState<SourceFilters>(emptyFilters);
  const [targets, setTargets] = useState("");
  const [session, dispatch] = useReducer(researchReducer, initialResearchSession);
  const [preview, setPreview] = useState<ResearchSource | null>(null);
  const { theme, setTheme, dark, cycleTheme } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(() => window.matchMedia("(min-width: 768px)").matches);
  const [elapsed, setElapsed] = useState(0);
  const [saved, setSaved] = useState<SavedResearch[]>([]);
  const [storageError, setStorageError] = useState("");
  const [continuationParent, setContinuationParent] = useState<string | null>(null);
  const [restoredResearchId, setRestoredResearchId] = useState<string | null>(null);
  const cleanup = useRef<(() => void) | null>(null);
  const generation = useRef(0);
  const savedSessionId = useRef<string | null>(null);
  const status: ResearchStatus = session.status;
  const snapshot = session.snapshot;
  useEffect(() => () => { generation.current++; cleanup.current?.(); }, []);
  useEffect(() => {
    if (status !== "researching") return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [status]);
  useEffect(() => {
    listSavedResearch().then(setSaved).catch((error) => setStorageError(error.message || 'Saved research could not be loaded.'));
    const closeSidebar = () => { if (window.matchMedia("(max-width: 767px)").matches) setSidebarOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") closeSidebar(); };
    window.addEventListener("hashchange", closeSidebar);
    document.addEventListener("keydown", escape);
    return () => { window.removeEventListener("hashchange", closeSidebar); document.removeEventListener("keydown", escape); };
  }, []);
  useEffect(() => {
    if (status !== "completed" || !snapshot || !session.report) return;
    const id = session.events.find((event) => event.research_id)?.research_id || restoredResearchId || `saved-${Date.now()}`;
    if (savedSessionId.current === id) return;
    savedSessionId.current = id;
    const item = toSavedResearch(id, snapshot.question.question, snapshot.mode || mode, session.report, snapshot);
    saveResearch(item).then(() => listSavedResearch().then(setSaved)).catch(() => setStorageError("This report could not be saved. Browser storage may be full; export the report before leaving."));
  }, [mode, restoredResearchId, session.events, session.report, snapshot, status]);
  useEffect(() => {
    const revealSection = () => requestAnimationFrame(() => {
      const target = document.getElementById(window.location.hash.slice(1));
      if (!target) return;
      let ancestor = target.parentElement;
      while (ancestor) { if (ancestor instanceof HTMLDetailsElement) ancestor.open = true; ancestor = ancestor.parentElement; }
    });
    window.addEventListener('hashchange', revealSection);
    revealSection();
    return () => window.removeEventListener('hashchange', revealSection);
  }, [activeTab, snapshot]);
  const clearResults = () => {
    generation.current++;
    const activeId = session.events.find((event) => event.research_id)?.research_id;
    if (status === "researching" && activeId) void cancelResearch(activeId).catch(() => {});
    cleanup.current?.();
    cleanup.current = null;
    dispatch({ type: "reset" });
    setRestoredResearchId(null);
    setActiveTab("research");
    setPreview(null);
  };
  const reset = () => {
    setContinuationParent(null);
    clearResults(); window.scrollTo({ top: 0, behavior: 'auto' }); savedSessionId.current = null; setQuestion(""); setTargets(""); setFilters(emptyFilters()); setMode("quick"); setMaxSources(10); setBudgets({});
  };
  const openSaved = (item: SavedResearch) => {
    setContinuationParent(null);
    cleanup.current?.(); cleanup.current = null; generation.current++;
    savedSessionId.current = item.id;
    setRestoredResearchId(item.id);
    setActiveTab("research");
    dispatch({ type: "restore", session: restoreResearch(item) });
    setQuestion(item.question); setMode(item.mode); setFilters(item.state.filters || emptyFilters()); setTargets((item.mode === "compare" ? item.state.question.comparison_items || [] : item.state.question.target_claims || []).join("\n")); setStorageError("");
  };
  const renameSaved = async (item: SavedResearch) => {
    const name = window.prompt("Name this saved research", item.name || item.question);
    if (!name?.trim()) return;
    try { const renamed = { ...item, name: name.trim() }; await saveResearch(renamed); setSaved(await listSavedResearch()); }
    catch (error) { setStorageError(error instanceof Error ? error.message : "This saved research could not be renamed."); }
  };
  const removeSaved = async (id: string) => { if (!window.confirm("Delete this saved report permanently? Its independent chats and PDFs will remain.")) return; try { await deleteSavedResearch(id); setSaved(await listSavedResearch()); } catch { setStorageError("This saved research could not be deleted."); } };
  const clearSaved = async () => { if (window.confirm(cloudEnabled ? "Delete all saved research from your cloud workspace? Independent chats and PDFs will remain." : "Clear all saved research from this browser?")) { try { await clearSavedResearch(); setSaved([]); } catch { setStorageError("Saved research could not be cleared."); } } };
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
        target_claims: mode === "fact_check" ? items : [], comparison_items: mode === "compare" ? items : [], ...(continuationParent ? { parent_research_id: continuationParent } : {}) });
      setContinuationParent(null);
      if (generation.current !== current) { void cancelResearch(id).catch(() => {}); return; }
      cleanup.current = streamResearch(id, (event: ResearchEvent) => {
        if (event.type === 'cloud_save_failed') setStorageError(event.message);
        if (['complete', 'research_failed'].includes(event.type)) window.dispatchEvent(new Event('research-usage-changed'));
        if (generation.current === current) dispatch(event);
      }, (error) => {
        if (generation.current === current) dispatch({ type: "error", message: error.message });
      });
    } catch (error) {
      if (generation.current === current) dispatch({ type: "error", message: error instanceof Error ? error.message : "Could not start research." });
    }
  };
  const researchId = session.events.find((event) => event.research_id)?.research_id || restoredResearchId;
  const prepareContinuation = (query: string) => {
    if (!researchId) return;
    const parent = researchId;
    clearResults();
    setContinuationParent(parent);
    setQuestion(query);
    window.scrollTo({ top: 0, behavior: 'auto' });
    window.location.hash = 'main-content';
  };
  return <div className="app-shell min-h-screen">
    <Sidebar open={sidebarOpen} onClose={() => { if (window.matchMedia("(max-width: 767px)").matches) setSidebarOpen(false); }} onNew={reset} saved={saved} onOpenSaved={openSaved} onRenameSaved={renameSaved} onDeleteSaved={removeSaved} onClearSaved={clearSaved} activeView={activeTab} onViewChange={setActiveTab} theme={theme} onTheme={setTheme} />
    <div className={sidebarOpen ? "md:pl-[260px]" : ""}>
      <Header dark={dark} onTheme={cycleTheme} onNew={reset} onMenu={() => setSidebarOpen((open) => !open)} status={status === "completed" ? snapshot?.completion_quality === "partial" ? "Evidence incomplete" : "Finished" : status} mode={mode} />
      <main id="main-content" className={`mx-auto max-w-7xl overflow-x-hidden px-6 py-8 lg:px-8 ${activeTab === "assistant" ? "assistant-workspace" : ""}`}>
        {(activeTab === "assistant" || status !== "idle") && <div className="mb-8 flex flex-wrap items-end justify-between gap-4 no-print">
          <div><p className="eyebrow">{activeTab === "assistant" ? "Research Assistant" : "Research workspace"}</p><h1 className="mt-2 text-2xl font-medium tracking-tight sm:text-3xl">{activeTab === "assistant" ? "Chat with your assistant" : snapshot?.question.refined_question || question || "Start with a research question"}</h1></div>
          {activeTab === "research" && status !== "idle" && <span className={`badge ${status === "error" ? "badge-error" : status === "completed" ? snapshot?.completion_quality === "partial" ? "badge-error" : "badge-success" : "badge-indigo"}`} role="status">{status === "researching" ? "Live research" : status === "completed" ? snapshot?.completion_quality === "partial" ? "Finished · Evidence incomplete" : "Finished" : status}</span>}
        </div>}
        <div className={activeTab === "research" ? "" : "hidden print:block"}>
        {status === 'completed' && snapshot && <section className="card mb-6 no-print" aria-label="Research answer"><h2 className="section-title">The answer so far</h2>{session.findings.some(finding => finding.evidence_status === 'Supported') ? <><p className="mt-3 leading-7">{session.findings.find(finding => finding.evidence_status === 'Supported')!.claim}</p><div className="mt-3 flex flex-wrap gap-2">{session.findings.find(finding => finding.evidence_status === 'Supported')!.source_ids.map(id => { const source = session.sources.find(item => item.id === id); return source ? <button key={id} className="badge" onClick={() => setPreview(source)}>View {id}</button> : null; })}</div><p className="mt-3 text-xs text-muted-foreground">This is one supported finding. Read the report for its scope, other findings, and limitations.</p></> : <p className="mt-3 text-sm text-warning">No supported answer was established in this session. Retrieved sources and tentative claims are available in the report; they do not establish a conclusion.</p>}</section>}
        {continuationParent && <p className="mb-4 text-sm text-muted-foreground" role="status">Continuing a saved report. This run will save a separate version with its own evidence.<button className="ml-2 underline" onClick={() => setContinuationParent(null)}>Start independently</button></p>}
        {status === "completed" && researchId && <section className="card mb-6 no-print" aria-label="Continue saved research"><h2 className="section-title">Continue research</h2><p className="mt-2 text-sm text-muted-foreground">Investigate a follow-up or evidence gap. The original report stays saved.</p><button className="button-secondary mt-3" onClick={() => prepareContinuation(`Update the research on: ${snapshot?.question.question || question}. Investigate new primary evidence and unresolved questions.`)}>Update this research</button>{snapshot?.research_gaps?.filter((gap, index, all) => all.findIndex(other => gapLabel(other) === gapLabel(gap)) === index).slice(0, 3).map((gap) => <button key={gap.gap_id} className="chip mt-3 ml-2 text-left" onClick={() => prepareContinuation(`For the research on ${snapshot.question.question}, investigate this evidence gap: ${gap.description}. Search focus: ${gap.recommended_search}`)} title={gap.description}>{gapLabel(gap)}</button>)}</section>}
        {snapshot?.parent_research_id && <p className="mb-4 text-sm text-muted-foreground no-print">Continued research · <button className="underline" onClick={() => { const parent = saved.find((item) => item.id === snapshot.parent_research_id); if (parent) openSaved(parent); else setStorageError('The original report is no longer available in this workspace.'); }}>Open original report</button></p>}
        {status === "idle" ? <><ResearchInput value={question} setValue={setQuestion} mode={mode} setMode={setMode} maxSources={maxSources} setMaxSources={setMaxSources} filters={filters} setFilters={setFilters} targets={targets} setTargets={setTargets} disabled={false} onSubmit={run} budgets={budgets} setBudgets={setBudgets} /><EmptyState /></> :
          <div className="research-results grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(300px,380px)]">
            {status === "completed" && <div className="report-full-width no-print"><p className="text-sm text-muted-foreground">{restoredResearchId ? `Saved report · ${new Date(saved.find(item => item.id === restoredResearchId)?.savedAt || Date.now()).toLocaleDateString()}` : "Research finished"}</p>{snapshot?.completion_quality === "partial" && <p role="status" className="mt-2 text-sm text-warning">The evidence is incomplete. Review the limitations or continue researching a gap before relying on the conclusions.</p>}</div>}
            {session.report && <div className="report-full-width"><ResearchReport markdown={session.report} structured={snapshot?.structured_report} sources={session.sources} onPreview={setPreview} /></div>}
            <details className="report-full-width research-diagnostics no-print" open={status !== "completed"}><summary className="cursor-pointer rounded-xl border border-border p-4 text-sm font-medium">Evidence, sources &amp; research diagnostics</summary><div className="mt-6 grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(300px,380px)]">
            <div className="min-w-0 space-y-6 no-print">
              {!restoredResearchId && <ResearchProgress events={session.events} status={status} hasReport={Boolean(session.report)} mode={mode} sources={session.sources} />}
              {!restoredResearchId && <ResearchTimeline events={session.events} status={status} />}
              {status === "researching" && researchId && <button className="button-secondary" onClick={() => void cancelResearch(researchId).catch((error: Error) => dispatch({ type: "error", message: error.message }))}>Cancel research</button>}
              {status === "completed" && snapshot?.completion_quality === "partial" && <p className="text-sm text-warning dark:text-warning" role="status">Report ready with unresolved evidence gaps. Review the limitations before using its conclusions.</p>}
              {snapshot && <section aria-label="Research overview"><div className="grid gap-3 sm:grid-cols-3">
                <MetricCard label="Sources found" value={session.sources.length} description="Number of sources discovered in this session." />
                <MetricCard label="Supported claims" value={verifiedClaims(snapshot).value ?? "Not available"} description={verifiedClaims(snapshot).formula} />
                <MetricCard label="Reported gaps" value={session.gaps.length} description="Number of research gaps reported in this session. A zero count does not prove complete coverage." />
              </div><details className="mt-3 rounded-xl border border-border p-4"><summary className="cursor-pointer text-sm text-muted-foreground">More research metrics</summary><div className="metric-grid mt-4">
                <MetricCard label="Relevant sources" value={relevantSources(session.sources, snapshot.relevance_threshold ?? 0.3).value ?? "Not available"} description={relevantSources(session.sources, snapshot.relevance_threshold ?? 0.3).formula} />
                <MetricCard label="High-quality sources" value={highQualitySources(session.sources).value ?? "Not available"} description={highQualitySources(session.sources).formula} />
                <MetricCard label="Claims" value={session.findings.length} description="Number of findings reported by the research state." />
                <MetricCard label="Conflicts" value={session.conflicts.length} description="Conflicts detected from linked claims and evidence." />
                <MetricCard label="Research coverage" value={researchCoverage(snapshot).value === null ? "Not available" : `${Math.round(researchCoverage(snapshot).value! * 100)}%`} description={researchCoverage(snapshot).formula} />
                <MetricCard label="Evidence" value={evidenceCount(snapshot).value ?? "Not available"} description={evidenceCount(snapshot).formula} />
                <MetricCard label="Citation coverage" value={citationCoverage(snapshot).value === null ? "Not available" : `${Math.round(citationCoverage(snapshot).value! * 100)}%`} description={citationCoverage(snapshot).formula} />
              </div></details></section>}
              {status === "researching" && <p className="text-xs text-muted-foreground" role="timer">Elapsed time: {Math.floor(elapsed / 60)}m {elapsed % 60}s</p>}
              {session.error && <div role="alert" className="error-state"><p className="font-medium">Research interrupted</p><p className="mt-1 text-sm">{session.error}</p><button onClick={run} className="button-secondary mt-3">Retry Research</button></div>}
              {snapshot && <section id="research-settings" className="card text-sm"><h2 className="section-title">Settings used for this report</h2><p className="mt-2">Mode: {snapshot.mode || mode}. Limits: {snapshot.max_sources} sources, {snapshot.max_searches} searches, {snapshot.max_iterations} rounds.</p><p className="mt-2 text-xs text-muted-foreground">{snapshot.filters?.include_domains.length ? `Included domains: ${snapshot.filters.include_domains.join(', ')}` : 'All domains eligible, subject to quality checks.'}</p><button className="button-secondary mt-3" disabled={status !== 'completed'} onClick={() => prepareContinuation(`Follow up on ${snapshot.question.question} using new evidence and unresolved questions.`)}>Use these settings for a follow-up</button></section>}
              {snapshot && <div className="card text-sm"><p><strong>Research scope:</strong> {snapshot.question.refined_question || snapshot.question.question}</p>{snapshot.question.assumptions?.map((assumption) => <p key={assumption} className="mt-2 text-xs text-muted-foreground">Assumption: {assumption}</p>)}</div>}
              {snapshot?.graph && <ResearchGraph graph={snapshot.graph} sources={session.sources} onPreview={setPreview} />}
              {session.findings.length > 0 && <section id="findings"><h2 className="mb-3 text-lg font-medium">Findings and evidence</h2><div className="grid gap-4">{session.findings.map((finding, index) => <FindingCard key={finding.id || index} finding={finding} sources={session.sources} evidence={session.evidence} onPreview={setPreview} />)}</div></section>}
              {session.findings.length > 0 && <ClaimExplorer findings={session.findings} evidence={session.evidence} sources={session.sources} verifications={session.verifications} onPreview={setPreview} />}
              {session.evidence.length > 0 && <EvidenceExplorer evidence={session.evidence} findings={session.findings} sources={session.sources} onPreview={setPreview} />}
              {session.conflicts.length > 0 && <section id="conflicts"><h2 className="mb-3 text-lg font-medium">Conflicts</h2><div className="space-y-3">{session.conflicts.map((conflict, index) => <ConflictCard key={index} conflict={conflict} sources={session.sources} evidence={session.evidence} onPreview={setPreview} />)}</div></section>}
              {snapshot && <ResearchQuality state={snapshot} />}
              {session.gaps.length > 0 && <ResearchGaps gaps={session.gaps} />}
            </div>
            <aside className="min-w-0 space-y-6 no-print"><SourceList sources={session.sources} conflicts={session.conflicts} onPreview={setPreview} />{snapshot?.audit_log && <AuditView entries={snapshot.audit_log} />}{!restoredResearchId && <ActivityLog events={session.events} />}</aside></div></details>
            <div className="report-support-panels report-full-width no-print">
              {snapshot && <details className="report-support-panel"><summary>Research insights</summary><ResearchInsights state={snapshot} findings={session.findings} /></details>}
              {snapshot && <details className="card"><summary className="cursor-pointer text-sm font-medium">Citation validation log ({snapshot.citation_rejections?.length || 0})</summary>{snapshot.citation_rejections?.length ? <ul className="mt-4 space-y-3 text-sm">{snapshot.citation_rejections.map((item, index) => <li key={index}><strong>{item.claim_id}</strong> · {item.source_id || item.evidence_id || "Report"}<p className="mt-1 text-muted-foreground">{item.reason}</p></li>)}</ul> : <p className="mt-3 text-sm text-muted-foreground">No citations have been rejected in this session.</p>}</details>}
            </div>
          </div>}
        </div>
        <section className="no-print"><ResearchChat key={snapshot && researchId ? researchId : generalChatId} researchId={snapshot && researchId ? researchId : generalChatId} state={snapshot && researchId ? snapshot : null} findings={session.findings} evidence={session.evidence} sources={session.sources} onPreview={setPreview} embedded={activeTab === "assistant"} /></section>
        {storageError && <p className="no-print mt-4 text-sm text-warning" role="alert">{storageError}</p>}
        <footer className="mx-auto mt-12 max-w-3xl border-t border-border py-8 text-center dark:border-border no-print"><p className="text-xs text-muted-foreground">{cloudEnabled ? 'Private workspace. Research and documents are saved until you delete them.' : 'Session-scoped research. Saved reports stay in this browser only.'}</p></footer>
      </main>
    </div>
    {preview && <SourcePreview source={preview} evidence={session.evidence} findings={session.findings} onClose={() => setPreview(null)} />}
  </div>;
}
