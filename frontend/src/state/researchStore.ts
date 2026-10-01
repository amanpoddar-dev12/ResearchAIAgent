import type {
  Conflict, Evidence, Finding, ResearchEvent, ResearchSource, ResearchState,
} from "../types/research";

export interface ResearchSession {
  events: ResearchEvent[];
  sources: ResearchSource[];
  findings: Finding[];
  evidence: Evidence[];
  conflicts: Conflict[];
  report: string;
  snapshot: ResearchState | null;
  status: "idle" | "researching" | "completed" | "error";
  error: string;
}

export const initialResearchSession: ResearchSession = {
  events: [], sources: [], findings: [], evidence: [], conflicts: [],
  report: "", snapshot: null, status: "idle", error: "",
};

export function researchReducer(state: ResearchSession, event: ResearchEvent | { type: "reset" } | { type: "error"; message: string }): ResearchSession {
  if (event.type === "reset") return initialResearchSession;
  if (event.type === "error") return { ...state, status: "error", error: event.message };
  const researchEvent = event as ResearchEvent;
  const next: ResearchSession = { ...state, events: [...state.events, researchEvent] };
  if (researchEvent.type === "research_started") next.status = "researching";
  if (researchEvent.type === "source_found") next.sources = [...state.sources, researchEvent.data as ResearchSource];
  if (researchEvent.type === "finding_extracted") next.findings = [...state.findings, researchEvent.data as Finding];
  if (researchEvent.type === "finding_updated") {
    const finding = researchEvent.data as Finding;
    next.findings = state.findings.map((item) => item.id === finding.id ? finding : item);
  }
  if (researchEvent.type === "evidence_linked") next.evidence = [...state.evidence, researchEvent.data as Evidence];
  if (researchEvent.type === "conflict_detected") next.conflicts = [...state.conflicts, researchEvent.data as Conflict];
  if (researchEvent.type === "research_snapshot") {
    const snapshot = researchEvent.data as ResearchState;
    next.snapshot = snapshot;
    next.sources = snapshot.sources;
    next.findings = snapshot.findings;
    next.evidence = snapshot.evidence || [];
    next.conflicts = snapshot.conflicts;
  }
  if (researchEvent.type === "complete") {
    const payload = researchEvent.data as { state: ResearchState; report: string };
    next.snapshot = payload.state;
    next.sources = payload.state.sources;
    next.findings = payload.state.findings;
    next.evidence = payload.state.evidence || [];
    next.conflicts = payload.state.conflicts;
    next.report = payload.report;
    next.status = "completed";
  }
  if (researchEvent.type === "research_failed") {
    next.status = "error";
    next.error = "Research could not be completed. Please retry this session.";
  }
  return next;
}
