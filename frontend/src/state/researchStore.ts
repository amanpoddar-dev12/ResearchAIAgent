import type {
  Conflict, Evidence, Finding, ResearchEvent, ResearchGap, ResearchSource, ResearchState, Verification,
} from "../types/research";
import type { SavedResearch } from "../storage/researchStorage";

export interface ResearchSession {
  events: ResearchEvent[];
  sources: ResearchSource[];
  findings: Finding[];
  evidence: Evidence[];
  conflicts: Conflict[];
  verifications: Verification[];
  gaps: ResearchGap[];
  report: string;
  snapshot: ResearchState | null;
  status: "idle" | "researching" | "completed" | "error";
  error: string;
}

export const initialResearchSession: ResearchSession = {
  events: [], sources: [], findings: [], evidence: [], conflicts: [], verifications: [], gaps: [],
  report: "", snapshot: null, status: "idle", error: "",
};

function upsert<T>(items: T[], item: T, key: (value: T) => string | undefined): T[] {
  const itemKey = key(item);
  if (!itemKey) return [...items, item];
  const index = items.findIndex((candidate) => key(candidate) === itemKey);
  return index < 0 ? [...items, item] : items.map((candidate, candidateIndex) => candidateIndex === index ? item : candidate);
}

export function researchReducer(state: ResearchSession, event: ResearchEvent | { type: "reset" } | { type: "error"; message: string } | { type: "restore"; session: ResearchSession }): ResearchSession {
  if (event.type === "reset") return initialResearchSession;
  if (event.type === "error") return { ...state, status: "error", error: event.message };
  if (event.type === "restore") return (event as { type: "restore"; session: ResearchSession }).session;
  const researchEvent = event as ResearchEvent;
  const sequence = researchEvent.sequence;
  if (sequence !== undefined && state.events.some((item) => item.research_id === researchEvent.research_id && item.sequence === sequence)) return state;
  if (sequence !== undefined && state.events.some((item) => item.research_id === researchEvent.research_id && item.sequence !== undefined && item.sequence > sequence)) return state;
  const next: ResearchSession = { ...state, events: [...state.events, researchEvent] };
  if (researchEvent.type === "research_started") next.status = "researching";
  if (researchEvent.type === "source_found") next.sources = upsert(state.sources, researchEvent.data as ResearchSource, (item) => item.id);
  if (researchEvent.type === "claim_extracted" || researchEvent.type === "finding_extracted") next.findings = upsert(state.findings, researchEvent.data as Finding, (item) => item.id);
  if (researchEvent.type === "finding_updated") {
    const finding = researchEvent.data as Finding;
    next.findings = upsert(state.findings, finding, (item) => item.id);
  }

  if (researchEvent.type === "evidence_found" || researchEvent.type === "evidence_linked") next.evidence = upsert(state.evidence, researchEvent.data as Evidence, (item) => item.id);
  if (researchEvent.type === "conflict_detected") next.conflicts = upsert(state.conflicts, researchEvent.data as Conflict, (item) => item.topic);
  if (researchEvent.type === "research_gap_detected") next.gaps = upsert(state.gaps, researchEvent.data as ResearchGap, (item) => item.gap_id);
  if (["claim_verified", "claim_partially_verified", "claim_contradicted", "claim_unverified"].includes(researchEvent.type)) {
    const verification = researchEvent.data as Verification;
    next.verifications = upsert(state.verifications, verification, (item) => item.claim_id);
  }
  if (researchEvent.type === "research_snapshot") {
    const snapshot = researchEvent.data as ResearchState;
    next.snapshot = snapshot;
    next.sources = snapshot.sources;
    next.findings = snapshot.findings;
    next.evidence = snapshot.evidence || [];
    next.conflicts = snapshot.conflicts;
    next.verifications = snapshot.verifications || [];
    next.gaps = snapshot.research_gaps || [];
  }
  if (researchEvent.type === "complete") {
    const payload = researchEvent.data as { state: ResearchState; report: string };
    next.snapshot = payload.state;
    next.sources = payload.state.sources;
    next.findings = payload.state.findings;
    next.evidence = payload.state.evidence || [];
    next.conflicts = payload.state.conflicts;
    next.verifications = payload.state.verifications || [];
    next.gaps = payload.state.research_gaps || [];
    next.report = payload.report;
    next.status = "completed";
  }
  if (researchEvent.type === "research_failed") {
    next.status = "error";
    next.error = "Research could not be completed. Please retry this session.";
  }
  return next;
}

export function restoreResearch(saved: SavedResearch): ResearchSession {
  return {
    events: [],
    sources: saved.sources,
    findings: saved.state.findings,
    evidence: saved.state.evidence || [],
    conflicts: saved.state.conflicts,
    verifications: saved.state.verifications || [],
    gaps: saved.state.research_gaps || [],
    report: saved.report,
    snapshot: saved.state,
    status: "completed",
    error: "",
  };
}
