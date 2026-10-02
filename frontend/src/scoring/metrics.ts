import type { ResearchSource, ResearchState } from "../types/research";

export interface MetricFactor { label: string; value: string }
export interface DerivedMetric { value: number | null; factors: MetricFactor[]; formula: string }

const RELEVANCE_THRESHOLD = 0.5;
const QUALITY_THRESHOLD = 0.7;

function countMetric(value: number, factors: MetricFactor[], formula: string): DerivedMetric {
  return { value, factors, formula };
}

export function relevantSources(sources: ResearchSource[]): DerivedMetric {
  const scored = sources.filter((source) => source.quality?.relevance !== undefined);
  if (!scored.length) return { value: null, factors: [], formula: "Not available: source relevance scores are missing." };
  const value = scored.filter((source) => source.quality!.relevance >= RELEVANCE_THRESHOLD).length;
  return countMetric(value, [
    { label: "Scored sources", value: String(scored.length) },
    { label: "Threshold", value: `relevance ≥ ${RELEVANCE_THRESHOLD}` },
  ], "Count sources with a reported relevance score at or above 0.5.");
}

export function highQualitySources(sources: ResearchSource[]): DerivedMetric {
  const scored = sources.filter((source) => source.quality?.total !== undefined);
  if (!scored.length) return { value: null, factors: [], formula: "Not available: source quality scores are missing." };
  const value = scored.filter((source) => source.quality!.total >= QUALITY_THRESHOLD).length;
  return countMetric(value, [
    { label: "Scored sources", value: String(scored.length) },
    { label: "Threshold", value: `overall quality ≥ ${QUALITY_THRESHOLD}` },
  ], "Count sources with a reported overall quality score at or above 0.7.");
}

export function verifiedClaims(state: ResearchState): DerivedMetric {
  if (!state.findings.length) return { value: 0, factors: [{ label: "Findings", value: "0" }], formula: "Count findings with Supported status." };
  const value = state.findings.filter((finding) => finding.evidence_status === "Supported").length;
  return countMetric(value, [
    { label: "Findings", value: String(state.findings.length) },
    { label: "Included status", value: "Supported" },
  ], "Count findings whose reported evidence status is Supported.");
}

export function researchCoverage(state: ResearchState): DerivedMetric {
  const decision = state.stop_decisions?.slice(-1)[0];
  if (!decision || typeof decision.coverage !== "number") return { value: null, factors: [], formula: "Not available: no stop-decision coverage was reported." };
  return { value: decision.coverage, factors: [{ label: "Stop decision", value: decision.reason }], formula: "Use the latest backend-reported stop-decision coverage." };
}

export function evidenceCount(state: ResearchState): DerivedMetric {
  const value = state.evidence?.length;
  if (value === undefined) return { value: null, factors: [], formula: "Not available: evidence is not present in the research state." };
  return countMetric(value, [{ label: "Evidence items", value: String(value) }], "Count evidence items reported in the research state.");
}

export function citationCoverage(state: ResearchState): DerivedMetric {
  if (!state.findings.length) return { value: 0, factors: [{ label: "Findings", value: "0" }], formula: "No findings were reported, so citation coverage is 0%." };
  const cited = state.findings.filter((finding) => finding.source_ids.length > 0 && (finding.evidence_ids?.length || finding.supporting_evidence_ids?.length || finding.contradicting_evidence_ids?.length)).length;
  return {
    value: cited / state.findings.length,
    factors: [{ label: "Cited findings", value: `${cited}/${state.findings.length}` }],
    formula: "Cited findings divided by total findings; a cited finding still requires evidence validation.",
  };
}

function average(values: number[]): number | null {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

export function evidenceCoverage(state: ResearchState): DerivedMetric {
  if (!state.findings.length) return { value: 0, factors: [{ label: "Findings", value: "0" }], formula: "No findings were reported, so evidence coverage is 0%." };
  const covered = state.findings.filter((finding) => Math.max(finding.evidence_ids?.length ?? 0, finding.supporting_evidence_ids?.length ?? 0, finding.contradicting_evidence_ids?.length ?? 0) > 0).length;
  return { value: covered / state.findings.length, factors: [{ label: "Findings with linked evidence", value: `${covered}/${state.findings.length}` }], formula: "Findings with at least one linked evidence item divided by total findings." };
}

export function averageSourceQuality(sources: ResearchSource[]): DerivedMetric {
  const values = sources.map((source) => source.quality?.total).filter((value): value is number => typeof value === "number");
  const value = average(values);
  return { value, factors: [{ label: "Scored sources", value: String(values.length) }], formula: "Average of reported source quality scores; unscored sources are excluded." };
}

export function sourceDiversity(sources: ResearchSource[]): DerivedMetric {
  if (!sources.length) return { value: 0, factors: [{ label: "Sources", value: "0" }], formula: "No sources were reported." };
  const domains = new Set(sources.map((source) => source.domain).filter(Boolean)).size;
  const types = new Set(sources.map((source) => source.source_type).filter(Boolean)).size;
  const value = Math.min(1, (domains / sources.length + types / sources.length) / 2);
  return { value, factors: [{ label: "Unique domains", value: String(domains) }, { label: "Source types", value: String(types) }], formula: "Estimated diversity = average of unique-domain ratio and unique-source-type ratio. It is not a correctness score." };
}

export function freshness(sources: ResearchSource[]): DerivedMetric {
  const values = sources.map((source) => source.quality?.freshness).filter((value): value is number => typeof value === "number");
  return { value: average(values), factors: [{ label: "Scored sources", value: String(values.length) }], formula: "Average of reported source freshness scores; sources without freshness scores are excluded." };
}
