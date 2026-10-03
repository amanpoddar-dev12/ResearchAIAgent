import { useMemo, useState } from "react";
import { Bot, ChevronRight, MessageCircle, Send, X } from "lucide-react";
import type { ChatCitation, Evidence, Finding, ResearchSource, ResearchState } from "../types/research";
import { askResearch } from "../services/api";

interface ChatMessage { id: string; role: "user" | "assistant"; content: string; citations: ChatCitation[]; limitations: string[] }

export function ResearchChat({ researchId, state, findings, evidence, sources, onPreview }: {
  researchId: string; state: ResearchState; findings: Finding[]; evidence: Evidence[]; sources: ResearchSource[]; onPreview: (source: ResearchSource) => void;
}) {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const suggestions = useMemo(() => {
    const items = ["Why is this finding supported?", "Show the strongest evidence.", "Explain this research in simple terms."];
    if (state.conflicts.length) items.push("Explain the conflicting evidence.");
    if (state.research_gaps?.length) items.push("What evidence is missing?");
    if (findings.some((finding) => finding.evidence_status === "Unverified" || finding.evidence_status === "Partially Supported")) items.push("Which claims need more verification?");
    return items.slice(0, 5);
  }, [state, findings]);
  const context = {};
  const submit = async (value = input) => {
    const message = value.trim();
    if (!message || loading) return;
    setInput(""); setError(""); setOpen(true); setLoading(true);
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", content: message, citations: [], limitations: [] };
    setMessages((current) => [...current, userMessage]);
    try {
      const response = await askResearch(researchId, message, context, [...messages, userMessage].map(({ role, content }) => ({ role, content })));
      setMessages((current) => [...current, { id: crypto.randomUUID(), role: "assistant", content: response.answer, citations: response.citations, limitations: response.limitations }]);
    } catch (chatError) {
      setError(chatError instanceof Error ? chatError.message : "The research assistant is unavailable.");
    } finally { setLoading(false); }
  };
  const citationSource = (citation: ChatCitation) => sources.find((source) => source.id === citation.source_id) || sources.find((source) => source.url === citation.url);
  return <><button type="button" className="chat-launcher button-primary" onClick={() => setOpen(true)} aria-label="Open research assistant"><MessageCircle size={17} /> Ask research</button>
    {open && <div className="chat-panel card" role="dialog" aria-label="Research assistant"><div className="flex items-start justify-between gap-3 border-b border-slate-200 pb-4 dark:border-slate-800"><div><div className="flex items-center gap-2"><Bot size={17} className="text-indigo-500" /><h2 className="font-semibold">Research Assistant</h2></div><p className="mt-1 text-xs text-slate-500">Grounded in {findings.length} claims · {evidence.length} evidence items · {sources.length} sources · {state.conflicts.length} conflicts · {state.research_gaps?.length || 0} gaps</p></div><button className="icon-button" onClick={() => setOpen(false)} aria-label="Close research assistant"><X size={17} /></button></div>
      <div className="chat-messages" aria-live="polite">{!messages.length && <div className="py-4"><p className="text-sm text-slate-500">Ask about the current research. Answers use only the claims, evidence, sources, conflicts, gaps, and report in this session.</p><div className="mt-4 flex flex-wrap gap-2">{suggestions.map((suggestion) => <button type="button" key={suggestion} className="chip text-left" onClick={() => void submit(suggestion)}>{suggestion}<ChevronRight size={13} className="ml-1 inline" /></button>)}</div></div>}{messages.map((message) => <article key={message.id} className={message.role === "user" ? "chat-message chat-user" : "chat-message chat-assistant"}><p className="whitespace-pre-wrap text-sm leading-6">{message.content}</p>{message.citations.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{message.citations.map((citation) => { const source = citationSource(citation); return <button type="button" key={citation.citation_id} className="badge badge-indigo" title={citation.supporting_text || citation.title} onClick={() => source && onPreview(source)}>{citation.citation_id} · {citation.title}</button>; })}</div>}{message.limitations.map((item) => <p key={item} className="mt-2 text-xs text-amber-700 dark:text-amber-300">{item}</p>)}</article>)}{loading && <div className="chat-message chat-assistant text-sm text-slate-500"><span className="inline-flex items-center gap-2"><span className="chat-pulse" />Analyzing research context…</span></div>}</div>
      {error && <div role="alert" className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/20 dark:text-red-300">{error}<button type="button" className="ml-2 underline" onClick={() => setError("")}>Dismiss</button></div>}
      <form className="mt-4 flex gap-2 border-t border-slate-200 pt-4 dark:border-slate-800" onSubmit={(event) => { event.preventDefault(); void submit(); }}><label htmlFor="research-chat-input" className="sr-only">Ask the research assistant</label><textarea id="research-chat-input" rows={2} value={input} onChange={(event) => setInput(event.target.value)} placeholder="Ask about this research…" className="select min-h-12 flex-1 resize-none" disabled={loading} /><button className="button-primary self-end px-3" disabled={loading || !input.trim()} aria-label="Send question"><Send size={16} /></button></form>
    </div>}</>;
}
