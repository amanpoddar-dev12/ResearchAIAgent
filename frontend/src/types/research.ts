export type ResearchStatus = "idle" | "researching" | "completed" | "error";
export type Depth = "quick" | "standard" | "deep";

export interface ResearchRequest { question: string; depth: Depth; max_sources: number }
export interface ResearchSource { id: string; title: string; url: string; domain: string; content?: string; publication_date?: string; source_type?: string; search_query?: string }
export interface Finding { claim: string; explanation: string; source_ids: string[]; confidence: number; category: string }
export interface Conflict { topic: string; claim_a: string; claim_b: string; source_a: string[]; source_b: string[]; explanation: string }
export interface ResearchPlan { objective: string; sub_questions: string[]; search_queries: string[]; research_areas: string[] }
export interface ResearchReport { title: string; executive_summary: string; key_findings: string[]; detailed_analysis: string[]; limitations: string[]; conclusion: string }
export interface ResearchState { question: { question: string }; plan?: ResearchPlan; sources: ResearchSource[]; findings: Finding[]; conflicts: Conflict[]; gaps: string[]; final_report?: string; searches_performed: number; iteration: number; status: string; llm_requests_used: number; max_llm_requests: number; max_searches: number; max_sources: number; max_iterations: number; llm_provider: string; llm_model: string }
export interface ResearchEvent { type: string; message: string; timestamp: string; data?: unknown }
