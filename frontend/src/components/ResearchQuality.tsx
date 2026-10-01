import type { ResearchState } from "../types/research";
import { researchCoverage } from "../scoring/metrics";

export function ResearchQuality({ state }: { state: ResearchState }) {
  const coverage = researchCoverage(state);
  const rows = [
    ["Research coverage", coverage.value === null ? null : `${Math.round(coverage.value * 100)}%`, coverage.formula],
    ["Evidence coverage", null, "Not available: no aggregate evidence coverage field is reported."],
    ["Source diversity", null, "Not available: source diversity is not reported by the backend."],
    ["Source quality", null, "Not available: no aggregate source quality field is reported."],
    ["Freshness", null, "Not available: freshness is reported per source only."],
    ["Claim verification", state.findings.length ? `${state.findings.filter((item) => item.evidence_status === "Supported").length}/${state.findings.length}` : "0", "Count of Supported findings divided by total findings."],
    ["Citation coverage", null, "Not available: no aggregate citation coverage field is reported."],
    ["Conflict resolution", state.conflicts.length ? "Conflicts present" : "No conflicts reported", "Based on the backend conflict collection; absence of conflicts is not proof of resolution."],
  ] as const;
  return <section className="card" aria-label="Research quality"><h2 className="section-title">Research quality</h2><div className="mt-4 grid gap-2 sm:grid-cols-2">{rows.map(([label, value, explanation]) => <div key={label} className="rounded-lg border border-slate-100 p-3 dark:border-slate-800" title={explanation}><div className="flex justify-between gap-2 text-xs"><span>{label}</span><strong>{value ?? "Not available"}</strong></div><p className="mt-1 text-[11px] text-slate-500">{value === null ? "Signal not reported" : explanation}</p></div>)}</div></section>;
}
