export type ResearchStatus = "idle" | "researching" | "completed" | "error";
export type Depth = "quick" | "standard" | "deep";
export type ResearchMode = "quick" | "deep" | "technical" | "academic" | "fact_check" | "compare" | "standard";
export const modes: { value: ResearchMode; label: string }[] = [{ value: "quick", label: "Quick" }, { value: "deep", label: "Deep" }, { value: "technical", label: "Technical" }, { value: "academic", label: "Academic" }, { value: "fact_check", label: "Fact Check" }, { value: "compare", label: "Compare" }];
export const sourceTypes = ["primary", "academic", "documentation", "news", "analysis", "other"] as const;
export type SourceType = typeof sourceTypes[number];
export interface SourceFilters { date_from?: string | null; date_to?: string | null; include_domains: string[]; exclude_domains: string[]; source_types: SourceType[]; prefer_primary: boolean }
export const emptyFilters = (): SourceFilters => ({ include_domains: [], exclude_domains: [], source_types: [], prefer_primary: false });
export interface SourceQuality { relevance: number; authority: number; freshness: number; source_type: number; evidence_strength: number; total: number; notes: string[] }
export interface Evidence { id: string; source_id: string; excerpt: string; relation: "supports" | "contradicts" | "context"; strength: "direct" | "partial" }
export interface CitationRejection { claim_id: string; source_id?: string; evidence_id?: string; reason: string }

export interface ResearchRequest { question: string; depth: Depth; max_sources: number; mode?: ResearchMode; filters?: SourceFilters; target_claims?: string[]; comparison_items?: string[]; budgets?: ResearchBudgets }
export interface ResearchSource { id: string; title: string; url: string; domain: string; content?: string; publication_date?: string; source_type?: string; search_query?: string; quality?: SourceQuality }
export interface Finding { claim: string; explanation: string; source_ids: string[]; confidence: number; category: string; id?: string; evidence_ids?: string[]; evidence_status?: "Supported" | "Partially Supported" | "Contradicted" | "Unverified"; comparison_item?: string; comparison_criterion?: string; depends_on?: string[]; dependency_rejected?: boolean; sub_question_ids?: string[] }
export interface Conflict { topic: string; claim_a: string; claim_b: string; source_a: string[]; source_b: string[]; explanation: string }
export interface ResearchPlan { objective: string; sub_questions: string[]; search_queries: string[]; research_areas: string[] }
export interface ResearchReport { title: string; executive_summary: string; key_findings: string[]; detailed_analysis: string[]; limitations: string[]; conclusion: string }
export interface ResearchState { question: { question: string; refined_question?: string; assumptions?: string[] }; plan?: ResearchPlan; sources: ResearchSource[]; findings: Finding[]; conflicts: Conflict[]; gaps: string[]; final_report?: string; searches_performed: number; iteration: number; status: string; llm_requests_used: number; max_llm_requests: number; max_searches: number; max_sources: number; max_iterations: number; llm_provider: string; llm_model: string; mode?: ResearchMode; filters?: SourceFilters; evidence?: Evidence[]; citation_rejections?: CitationRejection[]; filtered_sources?: { url: string; reason: string }[]; graph?: ResearchGraphData; audit_log?: AuditEntry[]; max_parallel_tasks?: number; max_wall_seconds?: number; elapsed_seconds?: number; unresolved_questions?: string[]; stop_decisions?: { stop: boolean; reason: string; coverage: number; unresolved: string[] }[] }
export interface ResearchEvent { type: string; message: string; timestamp: string; data?: unknown; progress?: number; phase?: string; mode?: ResearchMode }

export interface ResearchBudgets { max_searches?: number; max_sources?: number; max_iterations?: number; max_parallel_tasks?: number; max_wall_seconds?: number }
export interface AuditEntry { id: number; timestamp: string; action: string; message: string; details: Record<string, unknown> }
export interface ResearchGraphData { nodes: { id: string; type: string; label: string; status?: string }[]; edges: { source: string; target: string; type: string }[] }
