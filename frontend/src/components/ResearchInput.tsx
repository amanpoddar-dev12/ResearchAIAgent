import { useEffect, useState } from "react";
import { freshResearchIdeas, loadResearchIdeas, randomIdeas } from "../services/researchIdeas";
import { ArrowUp, Sparkles } from "lucide-react";
import { modes, sourceTypes } from "../types/research";
import type { ResearchMode, SourceFilters, ResearchBudgets } from "../types/research";

interface Props {
  value: string; setValue: (value: string) => void;
  mode: ResearchMode; setMode: (mode: ResearchMode) => void;
  maxSources: number; setMaxSources: (value: number) => void;
  filters: SourceFilters; setFilters: (filters: SourceFilters) => void;
  targets: string; setTargets: (value: string) => void;
  disabled: boolean; onSubmit: () => void;
  budgets: ResearchBudgets; setBudgets: (value: ResearchBudgets) => void;
}
function ideaLabel(question: string): string {
  const topic = question.replace(/^(?:What does (?:recent )?evidence (?:show|say) about|What are the benefits and limitations of|Which open research questions remain about|How do current approaches compare for)\s+/i, "").replace(/\s+as of [^?]+\?$/i, "").replace(/[.?]+$/, "");
  const words = topic.split(/\s+/);
  return words.length > 7 ? `${words.slice(0,7).join(" ")}…` : topic;
}
export function ResearchInput({ value, setValue, mode, setMode, maxSources, setMaxSources, filters, setFilters, targets, setTargets, disabled, onSubmit, budgets, setBudgets }: Props) {
  const [ideas, setIdeas] = useState(() => randomIdeas(freshResearchIdeas()));
  useEffect(() => {
    let active = true;
    let pool = freshResearchIdeas();
    loadResearchIdeas().then((items) => { pool = items; if (active) setIdeas(randomIdeas(pool)); });
    const timer = window.setInterval(() => setIdeas(randomIdeas(pool)), 5 * 60000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  const splitDomains = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);
  const invalidDates = Boolean(filters.date_from && filters.date_to && filters.date_from > filters.date_to);
  const invalidTargets = mode === "compare" && new Set(targets.split("\n").map((item) => item.trim()).filter(Boolean)).size < 2;
  return <section className="research-input mx-auto max-w-3xl">
    <div className="mb-5 text-center"><div className="mb-4 inline-flex items-center gap-2 rounded-full bg-accent/10 px-3 py-1.5 text-xs font-medium text-link dark:bg-primary/10 dark:text-link"><Sparkles size={14} aria-hidden="true" /> Evidence-led research</div>
      <h1 className="text-3xl font-medium tracking-tight sm:text-4xl">Turn a question into a sourced report.</h1>
      <p className="mt-3 text-sm text-muted-foreground">Choose a research strategy, refine your sources, and inspect the evidence.</p>
    </div>
    <form id="research-settings" onSubmit={(event) => { event.preventDefault(); if (!invalidDates && !invalidTargets) onSubmit(); }} className="rounded-xl border border-border bg-surface p-4 shadow-soft dark:border-border dark:bg-surface">
      <fieldset disabled={disabled} className="space-y-4">
        <label className="block text-sm font-medium" htmlFor="research-question">Research question</label>
        <textarea id="research-question" required minLength={3} value={value} onChange={(event) => setValue(event.target.value)} rows={3} placeholder="What would you like to investigate?" className="w-full rounded-xl border border-border bg-transparent p-3 outline-none focus:ring-2 focus:ring-primary dark:border-border" />
        <div className="flex flex-wrap gap-3">
          <label className="flex-1 text-xs">Research mode<select aria-label="Research mode" value={mode} onChange={(event) => { setMode(event.target.value as ResearchMode); setTargets(""); }} className="select mt-1 block min-h-10 w-full">{modes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          <label className="text-xs">Maximum sources<select aria-label="Maximum sources" value={maxSources} onChange={(event) => setMaxSources(Number(event.target.value))} className="select mt-1 block min-h-10">{[5, 10, 15, 20].map((number) => <option key={number} value={number}>{number}</option>)}</select></label>
        </div>
        {(mode === "fact_check" || mode === "compare") && <label className="block text-sm">{mode === "compare" ? "Items to compare (one per line, 2–6)" : "Specific claims to verify (one per line, up to 10; defaults to your question)"}<textarea aria-label={mode === "compare" ? "Items to compare" : "Claims to verify"} rows={3} value={targets} onChange={(event) => setTargets(event.target.value)} className="mt-2 w-full rounded-lg border border-border bg-transparent p-3 dark:border-border" /></label>}
        <details className="rounded-xl border border-border p-3 dark:border-border">
          <summary className="cursor-pointer text-sm font-medium">Source filters</summary>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="text-xs">Published from<input aria-label="Published from" type="date" value={filters.date_from || ""} onChange={(event) => setFilters({ ...filters, date_from: event.target.value || null })} className="select mt-1 block w-full" /></label>
            <label className="text-xs">Published through<input aria-label="Published through" type="date" value={filters.date_to || ""} onChange={(event) => setFilters({ ...filters, date_to: event.target.value || null })} className="select mt-1 block w-full" /></label>
            <label className="text-xs">Include domains (comma separated)<input aria-label="Include domains" value={filters.include_domains.join(",")} onChange={(event) => setFilters({ ...filters, include_domains: event.target.value.split(",") })} placeholder="example.org, docs.example.org" className="select mt-1 block w-full" onBlur={(event) => setFilters({ ...filters, include_domains: splitDomains(event.target.value) })} /></label>
            <label className="text-xs">Exclude domains (comma separated)<input aria-label="Exclude domains" value={filters.exclude_domains.join(",")} onChange={(event) => setFilters({ ...filters, exclude_domains: event.target.value.split(",") })} placeholder="example.net" className="select mt-1 block w-full" onBlur={(event) => setFilters({ ...filters, exclude_domains: splitDomains(event.target.value) })} /></label>
            <div className="sm:col-span-2"><p className="mb-2 text-xs">Source types (none selected includes all)</p><div className="flex flex-wrap gap-3">{sourceTypes.map((type) => <label key={type} className="flex items-center gap-1.5 text-xs capitalize"><input type="checkbox" checked={filters.source_types.includes(type)} onChange={(event) => setFilters({ ...filters, source_types: event.target.checked ? [...filters.source_types, type] : filters.source_types.filter((item) => item !== type) })} />{type}</label>)}</div></div>
            <label className="flex items-center gap-2 text-xs sm:col-span-2"><input type="checkbox" checked={filters.prefer_primary} onChange={(event) => setFilters({ ...filters, prefer_primary: event.target.checked })} />Prefer primary sources, original studies and documentation</label>
            <p className="text-xs text-muted-foreground sm:col-span-2">Filters apply before extraction. Date filters exclude undated sources. Types are inferred; primary preference ranks each search batch.</p>
          </div>
        </details>
        <details className="rounded-xl border border-border p-3 dark:border-border"><summary className="cursor-pointer text-sm font-medium">Research budgets</summary><p className="mt-2 text-xs text-muted-foreground">Leave blank to use mode defaults. Maximum sources above applies unless overridden here.</p><div className="mt-3 grid gap-3 sm:grid-cols-2">{([
          ["max_searches", "Searches", 100], ["max_sources", "Sources", 100], ["max_iterations", "Iterations", 20], ["max_parallel_tasks", "Parallel searches", 8], ["max_wall_seconds", "Time limit (seconds)", 3600],
        ] as const).map(([key, label, max]) => <label key={key} className="text-xs">{label}<input aria-label={label} type="number" min={1} max={max} step={1} value={budgets[key] ?? ""} placeholder="Mode default" onChange={(event) => setBudgets({ ...budgets, [key]: event.target.value ? Number(event.target.value) : undefined })} className="select mt-1 block w-full" /></label>)}</div></details>
        {invalidDates && <p role="alert" className="text-sm text-destructive">Start date must be on or before end date.</p>}
        {invalidTargets && <p className="text-sm text-muted-foreground">Enter at least two distinct comparison items.</p>}
        <button disabled={disabled || value.trim().length < 3 || invalidDates || invalidTargets} className="button-primary min-h-10 w-full justify-center">Research <ArrowUp size={16} aria-hidden="true" /></button>
      </fieldset>
    </form>
    <div className="mt-4" aria-label="Example research questions"><p className="mb-2 text-center text-xs text-muted-foreground">Explore a research idea</p><div className="flex flex-wrap justify-center gap-2">{ideas.map((example) => <button key={example} type="button" className="chip" title={example} aria-label={example} onClick={() => setValue(example)}>{ideaLabel(example)}</button>)}</div></div>
  </section>;
}
