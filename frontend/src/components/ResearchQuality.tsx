import type { ResearchState } from "../types/research";
import { averageSourceQuality, citationCoverage, evidenceCoverage, freshness, researchCoverage, sourceDiversity } from "../scoring/metrics";
import { ConfidenceBar } from "./ConfidenceBar";

export function ResearchQuality({ state }: { state: ResearchState }) {
  const metrics = [
    ["Research coverage", researchCoverage(state), "Coverage reported by the backend stop decision."],
    ["Evidence coverage", evidenceCoverage(state), "Findings with at least one linked evidence item."],
    ["Source quality", averageSourceQuality(state.sources), "Average of reported source quality scores."],
    ["Source diversity", sourceDiversity(state.sources), "Estimated from unique domains and source types; diversity alone does not determine correctness."],
    ["Freshness", freshness(state.sources), "Average of reported source freshness scores."],
    ["Citation coverage", citationCoverage(state), "Findings with both a source and linked evidence."],
  ] as const;
  const verified = state.findings.filter((item) => item.evidence_status === "Supported").length;
  const rows = [
    ["Claim verification", state.findings.length ? `${verified}/${state.findings.length}` : "0", "Count of Supported findings divided by total findings."],
    ["Conflict resolution", state.conflicts.length ? `${state.conflicts.length} unresolved` : "0 reported", "Conflict resolution status is not reported; conflicts are shown neutrally and are not treated as resolved."],
  ] as const;
  return <section id="research-quality" className="card" aria-label="Research quality"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="section-title">Research quality</h2><p className="mt-1 text-xs text-muted-foreground">System-generated indicators, not probabilities of truth.</p></div><span className="badge badge-indigo">{state.sources.length} sources · {state.findings.length} claims</span></div><div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{metrics.map(([label, metric, explanation]) => <details key={label} className="rounded-xl border border-border p-3 dark:border-border"><summary className="cursor-pointer list-none"><div className="flex items-center justify-between gap-2 text-xs"><span>{label}</span><strong>{metric.value === null ? "Not available" : `${Math.round(metric.value * 100)}%`}</strong></div>{metric.value !== null && <div className="mt-2"><ConfidenceBar value={metric.value} label="" /></div>}</summary><p className="mt-3 text-[11px] leading-5 text-muted-foreground">{explanation} {metric.formula}</p><ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">{metric.factors.map((factor) => <li key={factor.label}><strong>{factor.label}:</strong> {factor.value}</li>)}</ul></details>)}</div><div className="mt-3 grid gap-2 sm:grid-cols-2">{rows.map(([label, value, explanation]) => <div key={label} className="rounded-lg border border-border p-3 dark:border-border" title={explanation}><div className="flex justify-between gap-2 text-xs"><span>{label}</span><strong>{value}</strong></div><p className="mt-1 text-[11px] text-muted-foreground">{explanation}</p></div>)}</div></section>;
}
