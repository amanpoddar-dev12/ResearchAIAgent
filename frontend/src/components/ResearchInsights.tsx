import { Lightbulb } from "lucide-react";
import type { Finding, ResearchState } from "../types/research";

export function ResearchInsights({ state, findings }: { state: ResearchState; findings: Finding[] }) {
  const items = [
    ...findings.slice(0, 5).map((finding) => ({ label: "Finding", text: finding.claim })),
    ...(state.gaps || []).map((gap) => ({ label: "Evidence gap", text: gap })),
    ...(state.unresolved_questions || []).map((question) => ({ label: "Unresolved question", text: question })),
  ];
  if (!items.length) return null;
  return <section className="card" aria-label="Research insights"><h2 className="section-title"><Lightbulb size={17} /> Research insights</h2><div className="mt-4 grid gap-2">{items.map((item, index) => <div key={`${item.label}-${index}`} className="border-l-2 border-border pl-3"><p className="text-[11px] font-medium uppercase tracking-wide text-link">{item.label}</p><p className="mt-1 text-sm">{item.text}</p></div>)}</div></section>;
}
