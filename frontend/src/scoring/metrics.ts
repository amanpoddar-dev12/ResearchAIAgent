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
