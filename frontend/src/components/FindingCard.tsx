import { BarChart3 } from "lucide-react";
import { Citation } from "./Citation";
import { ConfidenceBar } from "./ConfidenceBar";
import type { Evidence, Finding, ResearchSource } from "../types/research";
import { VerificationBadge } from "./VerificationBadge";
export function FindingCard({ finding, sources, evidence, onPreview }: { finding: Finding; sources: ResearchSource[]; evidence: Evidence[]; onPreview: (source: ResearchSource) => void }) {
  return <article className="card">
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs font-medium"><span className="uppercase tracking-wider text-link">{finding.category}</span><VerificationBadge status={finding.evidence_status} /></div>
    <p className="font-medium leading-7">{finding.claim}</p><p className="mt-2 text-sm leading-6 text-muted-foreground">{finding.explanation}</p>
    {Boolean(finding.depends_on?.length) && <p className="mt-2 text-xs text-muted-foreground">Depends on: {finding.depends_on!.join(", ")}</p>}
    {finding.dependency_rejected && <p className="mt-2 text-xs text-warning">Invalid dependency rejected; this claim remains Unverified.</p>}
    <div className="mt-3 flex gap-2">{finding.source_ids.map((id) => { const index = sources.findIndex((source) => source.id === id); return index >= 0 ? <Citation key={id} n={index + 1} onClick={() => onPreview(sources[index])} /> : null; })}</div>
    <div className="mt-4 flex flex-wrap items-center gap-4"><ConfidenceBar value={finding.confidence_score ?? finding.confidence} label="Evidence confidence" /><span className="text-xs text-muted-foreground"><BarChart3 size={15} className="mr-1 inline" />{finding.supporting_evidence_ids?.length ?? evidence.filter((item) => finding.evidence_ids?.includes(item.id) && item.relation === "supports").length} supporting · {finding.contradicting_evidence_ids?.length ?? evidence.filter((item) => finding.evidence_ids?.includes(item.id) && item.relation === "contradicts").length} contradicting</span></div>
    <details className="mt-4 text-xs"><summary className="cursor-pointer font-medium">Why this score?</summary><ul className="mt-2 list-inside list-disc space-y-1 text-muted-foreground"><li>Source quality: {finding.score_source_quality === undefined ? "Not available" : `${Math.round(finding.score_source_quality * 100)}%`}</li><li>Evidence relevance: {finding.score_evidence_relevance === undefined ? "Not available" : `${Math.round(finding.score_evidence_relevance * 100)}%`}</li><li>Source agreement: {finding.score_source_agreement === undefined ? "Not available" : `${Math.round(finding.score_source_agreement * 100)}%`}</li><li>Freshness: {finding.score_freshness === undefined ? "Not available" : `${Math.round(finding.score_freshness * 100)}%`}</li><li>Citation validity: {finding.score_citation_validity === undefined ? "Not available" : `${Math.round(finding.score_citation_validity * 100)}%`}</li><li>{finding.score_formula || "Score formula not available."}</li></ul></details>
  </article>;
}
