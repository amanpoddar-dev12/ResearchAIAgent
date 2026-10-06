import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, ChevronRight, MessageCircle, ArrowUp, Sparkles, Trash2, X, Paperclip, FileText, Plus } from "lucide-react";
import type { ChatCitation, ChatResponse, Evidence, Finding, ResearchEvent, ResearchSource, ResearchState } from "../types/research";
import { listSavedResearch, type SavedResearch } from "../storage/researchStorage";

import { loadChat, listChats, saveChat, loadPDF, savePDF } from "../storage/chatStorage";
import type { ChatMessage, ChatRecord } from "../storage/chatStorage";
import type { PDFDocument, PDFContext } from "../rag/pdfRetrieval";
const emptySources: ResearchSource[] = [];
const emptyFindings: Finding[] = [];
const emptyEvidence: Evidence[] = [];
const apiUrl = (import.meta.env.DEV ? "" : import.meta.env.VITE_API_URL || import.meta.env.VITE_BACKEND_URL || "").replace(/\/$/, "");

type AnswerOrigin = "From research" | "General knowledge" | "Mixed";
function followUpQuestions(message: ChatMessage): string[] {
  const source = message.citations[0];
  const fromResearch = /^\[(From research|Mixed)\]/.test(message.content);
  return [
    "Can you explain that in simpler terms?",
    source ? `What evidence from ${source.citation_id.startsWith("P") ? `page ${source.citation_id.slice(1)}` : source.citation_id} supports that answer?` : "Can you give a practical example of that?",
    message.pdfName ? "What does this PDF leave unanswered about that?" : fromResearch ? "What does the research leave unanswered about this?" : "What are the main limitations or tradeoffs of that?",
  ];
}

interface SavedResearchWithChat extends SavedResearch { assistantChat?: ChatMessage[] }

export function ResearchChat({ researchId, state: researchState, findings: researchFindings, evidence: researchEvidence, sources: researchSources, onPreview, embedded = false }: {
  researchId: string; state: ResearchState | null; findings: Finding[]; evidence: Evidence[]; sources: ResearchSource[]; onPreview: (source: ResearchSource) => void; embedded?: boolean;
}) {
  const [conversationId, setConversationId] = useState(researchId);
  const [contextOverride, setContextOverride] = useState<ResearchState | null | undefined>(undefined);
  const state = contextOverride === undefined ? researchState : contextOverride;
  const findings = contextOverride === undefined ? researchFindings : state?.findings || emptyFindings;
  const evidence = contextOverride === undefined ? researchEvidence : state?.evidence || emptyEvidence;
  const sources = contextOverride === undefined ? researchSources : state?.sources || emptySources;
  const [recentChats, setRecentChats] = useState<ChatRecord[]>([]);
  const [pdf, setPdf] = useState<PDFDocument | null>(null);
  const [pdfReady, setPdfReady] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [pdfExcerpt, setPdfExcerpt] = useState<ChatCitation | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);
  const uploadRequest = useRef<AbortController | null>(null);
  const pdfWorker = useRef<Worker | null>(null);
  const retrievalCounter = useRef(0);
  const retrievalPending = useRef(new Map<number, { resolve: (context: PDFContext) => void; reject: (error: Error) => void }>());
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [historyReady, setHistoryReady] = useState(false);
  const [error, setError] = useState("");
  const activeRequest = useRef<AbortController | null>(null);
  const saving = useRef<Promise<void>>(Promise.resolve());
  const inputBox = useRef<HTMLTextAreaElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);
  const threadEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    setHistoryReady(false); setMessages([]); setInput(""); setPdf(null); setError("");
    Promise.all([loadChat(conversationId), loadPDF(conversationId)]).then(async ([saved, document]) => {
      if (!saved && conversationId === researchId) {
        const research = (await listSavedResearch()).find((item) => item.id === researchId) as SavedResearchWithChat | undefined;
        if (research?.assistantChat) saved = { id: conversationId, title: research.question, updatedAt: research.savedAt, messages: research.assistantChat, draft: "", state: research.state };
      }
      if (!active) return;
      const history = Array.isArray(saved?.messages) ? saved.messages.filter((item) => item && typeof item.content === "string" && ["user", "assistant"].includes(item.role)) : [];
      setMessages(history.map((item) => ({ ...item, citations: Array.isArray(item.citations) ? item.citations : [], limitations: Array.isArray(item.limitations) ? item.limitations : [] })));
      setInput(saved?.draft || "");
      if (saved && conversationId !== researchId) setContextOverride(saved.state);
      setPdf(document || null); setHistoryReady(true);
    }).catch(() => { if (active) { setHistoryReady(true); setError("Local chat history could not be loaded. Browser storage may be unavailable."); } });
    return () => { active = false; activeRequest.current?.abort(); uploadRequest.current?.abort(); };
  }, [conversationId, researchId]);

  const persistMessages = (history: ChatMessage[]) => {
    const record: ChatRecord = { id: conversationId, title: history.find((item) => item.role === "user")?.content.slice(0,100) || "New conversation", updatedAt: new Date().toISOString(), messages: history, draft: "", state: state ? { ...state, sources: sources.map(({ content: _content, ...source }) => source) } : null };
    saving.current = saving.current.catch(() => {}).then(() => saveChat(record)).then(() => {
      setRecentChats((items) => [record, ...items.filter((item) => item.id !== record.id)].filter((item) => item.messages.length));
    }).catch(() => setError("Chat history could not be saved locally."));
  };

  useEffect(() => { listChats().then(setRecentChats).catch(() => {}); }, []);
  useEffect(() => {
    if (!historyReady || loading) return;
    const timer = window.setTimeout(() => {
      const record: ChatRecord = { id: conversationId, title: messages.find((item) => item.role === "user")?.content.slice(0, 100) || "New conversation", updatedAt: new Date().toISOString(), messages, draft: input, state: state ? { ...state, sources: sources.map(({ content: _content, ...source }) => source) } : null };
      saving.current = saving.current.catch(() => {}).then(() => saveChat(record)).then(() => {
        setRecentChats((items) => [record, ...items.filter((item) => item.id !== record.id)].filter((item) => item.messages.length));
      }).catch(() => setError("Chat history could not be saved. Browser storage may be full; your current chat remains open."));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [historyReady, loading, messages, input, conversationId, state, sources]);

  useEffect(() => {
    setPdfReady(false);
    if (!pdf) return;
    let worker: Worker;
    try { worker = new Worker(new URL("../rag/pdfWorker.ts", import.meta.url), { type: "module" }); }
    catch { setError("This browser could not start PDF indexing. Try another browser or remove the attachment."); return; }
    pdfWorker.current = worker;
    worker.onmessage = (event) => {
      if (event.data.type === "ready") setPdfReady(true);
      if (event.data.type === "retrieved") {
        retrievalPending.current.get(event.data.requestId)?.resolve(event.data.context);
        retrievalPending.current.delete(event.data.requestId);
      }
      if (event.data.type === "error") {
        setError(event.data.error);
        retrievalPending.current.get(event.data.requestId)?.reject(new Error(event.data.error));
        retrievalPending.current.delete(event.data.requestId);
      }
    };
    worker.onerror = () => { setError("The PDF index could not be prepared. Try a smaller document."); retrievalPending.current.forEach((pending) => pending.reject(new Error("PDF indexing failed."))); retrievalPending.current.clear(); };
    worker.postMessage({ type: "index", document: pdf });
    return () => { worker.terminate(); pdfWorker.current = null; retrievalPending.current.forEach((pending) => pending.reject(new Error("The document changed."))); retrievalPending.current.clear(); };
  }, [pdf]);

  const chooseConversation = (id: string) => {
    if (id.startsWith("general-chat-")) { try { localStorage.setItem("research-assistant-current-chat", id); } catch { /* Optional selected-thread preference. */ } }
    activeRequest.current?.abort(); uploadRequest.current?.abort();
    setLoading(false); setUploading(false); setContextOverride(id === researchId ? undefined : null); setConversationId(id); setPdfExcerpt(null);
  };
  const newConversation = () => {
    const id = `general-chat-${crypto.randomUUID()}`;
    try { localStorage.setItem("research-assistant-current-chat", id); } catch { /* Chat remains usable without localStorage. */ }
    chooseConversation(id);
  };
  const uploadPDF = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf") || file.size > 25 * 1024 * 1024) { setError("Choose a PDF that is 25 MB or smaller."); return; }
    const controller = new AbortController(); uploadRequest.current = controller;
    setUploading(true); setError("");
    try {
      const response = await fetch(`${apiUrl}/api/assistant/pdf?name=${encodeURIComponent(file.name.slice(0,200))}`, { method: "POST", headers: { "Content-Type": "application/pdf" }, body: file, signal: controller.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "This PDF could not be processed.");
      if (controller.signal.aborted) return;
      const document = data as PDFDocument;
      setPdf(document);
      try { await savePDF(conversationId, document); } catch { setError("PDF is ready, but could not be saved locally. It will need uploading again after refresh."); }
    } catch (uploadError) { if (!controller.signal.aborted) setError(uploadError instanceof Error ? uploadError.message : "PDF upload failed."); }
    finally { if (!controller.signal.aborted) setUploading(false); }
  };
  const removePDF = async () => { setPdf(null); setPdfExcerpt(null); try { await savePDF(conversationId, null); } catch { setError("The PDF attachment could not be removed from browser storage."); } };

  useEffect(() => {
    const thread = threadEnd.current?.parentElement;
    if ((open || embedded) && thread) thread.scrollTop = thread.scrollHeight;
  }, [messages, loading, open, embedded]);

  useEffect(() => {
    if (!open || embedded) return;
    inputBox.current?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector("dialog[open]")) {
        setOpen(false);
        launcher.current?.focus();
      }
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [open, embedded]);

  const suggestions = useMemo(() => {
    if (pdf) return [`Summarize the main points of "${pdf.name}".`, "What conclusions are supported by this PDF?", "What limitations does this PDF mention?"];
    if (!state) return ["Explain what an API is.", "Help me understand a topic step by step.", "How can I evaluate whether a source is reliable?"];
    const title = (state.structured_report?.title || state.final_report?.match(/^#\s+(.+)$/m)?.[1] || state.question.refined_question || state.question.question).slice(0, 140);
    const chart = state.structured_report?.charts[0];
    const claim = findings[0];
    const limitation = state.structured_report?.sections.find((section) => /limitation|gap|future/i.test(section.title));
    return [
      `What were the main findings in "${title}"?`,
      chart ? `Explain the chart "${chart.title.slice(0, 140)}".` : claim ? `What evidence supports "${claim.claim.slice(0, 140)}"?` : `Which sources support the report "${title}"?`,
      limitation ? `What does the "${limitation.title}" section say?` : `What limitations does "${title}" identify?`,
    ];
  }, [state, findings, pdf]);

  const clearChat = () => {
    activeRequest.current?.abort(); activeRequest.current = null;
    setMessages([]); setInput(""); setError(""); setLoading(false);
  };

  const submit = async (value = input) => {
    const message = value.trim();
    if (!message || loading || uploading || (pdf && !pdfReady) || !historyReady) return;
    setInput(""); setError(""); setOpen(true); setLoading(true);
    const controller = new AbortController();
    activeRequest.current = controller;
    const assistantId = crypto.randomUUID();
    const userMessage: ChatMessage = { id: crypto.randomUUID(), role: "user", content: message, citations: [], limitations: [] };
    const pendingAnswer: ChatMessage = { id: assistantId, role: "assistant", content: "", citations: [], limitations: [], pdfName: pdf?.name, complete: false };
    setMessages((current) => [...current, userMessage, pendingAnswer]);
    persistMessages([...messages, userMessage]);
    try {
      const history = messages.filter((item) => item.content).slice(-16).map(({ role, content }) => ({ role, content }));
      let pdfContext: PDFContext | undefined;
      if (pdf && pdfWorker.current) {
        const requestId = ++retrievalCounter.current;
        pdfContext = await new Promise<PDFContext>((resolve, reject) => {
          const timer = window.setTimeout(() => { retrievalPending.current.delete(requestId); reject(new Error("PDF retrieval timed out. Try a narrower question.")); }, 15000);
          retrievalPending.current.set(requestId, { resolve: (context) => { window.clearTimeout(timer); resolve(context); }, reject: (reason) => { window.clearTimeout(timer); reject(reason); } });
          pdfWorker.current!.postMessage({ type: "retrieve", requestId, question: message, history });
        });
      }
      if (controller.signal.aborted) return;
      const response = await fetch(`${apiUrl}/api/research/${conversationId}/chat/stream`, {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
        body: JSON.stringify({ message, history, ...(pdfContext ? { pdf_context: pdfContext } : {}), ...(state ? { saved_state: { ...state, findings, evidence, sources } } : {}) }),
      });
      if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || "The research assistant is unavailable.");
      if (!response.body) throw new Error("The answer stream is unavailable.");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      try {
        while (!completed) {
          const { value: bytes, done } = await reader.read();
          buffer += decoder.decode(bytes, { stream: !done });
          const frames = buffer.split(/\r?\n\r?\n/);
          buffer = frames.pop() || "";
          for (const frame of frames) {
            const data = frame.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
            if (!data) continue;
            const event = JSON.parse(data) as ResearchEvent;
            if (event.research_id !== conversationId) throw new Error("Answer stream session mismatch.");
            if (event.type === "chat_error") throw new Error(event.message);
            if (controller.signal.aborted) return;
            if (event.type === "chat_delta") {
              const delta = event.data as { text: string; citations: ChatCitation[] };
              setMessages((current) => current.map((item) => item.id === assistantId ? { ...item, content: item.content + delta.text, citations: delta.citations } : item));
            }
            if (event.type === "chat_complete") {
              const answer = event.data as ChatResponse;
              setMessages((current) => current.map((item) => item.id === assistantId ? { ...item, content: answer.answer, citations: answer.citations, limitations: answer.limitations, complete: true } : item));
              persistMessages([...messages, userMessage, { ...pendingAnswer, content: answer.answer, citations: answer.citations, limitations: answer.limitations, complete: true }]);
              completed = true;
            }
          }
          if (done) break;
        }
        if (!completed && !controller.signal.aborted) throw new Error("The answer stream ended before completion. Please retry.");
      } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    } catch (chatError) {
      if (!controller.signal.aborted) {
        setError(chatError instanceof Error ? chatError.message : "The research assistant is unavailable.");
        setMessages((current) => current.filter((item) => item.id !== assistantId || item.content));
      }
    } finally { if (!controller.signal.aborted) setLoading(false); }
  };

  const citationSource = (citation: ChatCitation) => sources.find((source) => source.id === citation.source_id) || sources.find((source) => source.url === citation.url);
  const displayAnswer = (message: ChatMessage) => {
    const match = message.role === "assistant" && message.content.match(/^\[(From research|General knowledge|Mixed)\]\s*\n/);
    const origin = match ? match[1] as AnswerOrigin : null;
    const text = match ? message.content.slice(match[0].length) : message.content;
    const body = text.split(/(\[[SP]\d+\])/g).map((part, index) => {
      const citation = message.role === "assistant" && message.citations.find((item) => `[${item.citation_id}]` === part);
      const source = citation && citationSource(citation);
      if (citation && citation.citation_id.startsWith("P")) return <button key={index} type="button" className="badge badge-indigo mx-0.5" title={citation.title} onClick={() => setPdfExcerpt(citation)}>{part}</button>;
      return source ? <button key={index} type="button" className="badge badge-indigo mx-0.5 align-baseline" title={citation.title} aria-label={`Preview source ${citation.citation_id}: ${citation.title}`} onClick={() => onPreview(source)}>{part}</button> : part;
    });
    return <>{origin && <span className={`badge mb-2 ${origin === "From research" ? "badge-success" : origin === "General knowledge" ? "badge-indigo" : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200"}`}>{message.pdfName && origin === "From research" ? "From PDF" : origin}</span>}<p className="whitespace-pre-wrap text-sm leading-6">{body}</p></>;
  };

  return <>{!embedded && <button ref={launcher} type="button" className="chat-launcher button-primary rounded-full bg-gradient-to-r from-indigo-600 to-violet-600 px-5 py-3 shadow-xl shadow-indigo-500/20 motion-safe:transition-transform motion-safe:hover:-translate-y-1" onClick={() => setOpen(true)} aria-label="Open research assistant" aria-expanded={open} aria-controls="research-chat-panel"><MessageCircle size={18} /> Ask assistant<Sparkles size={14} className="opacity-80" /></button>}
    {(embedded || open) && <div id="research-chat-panel" className={embedded ? "card flex min-h-[28rem] max-h-[42rem] flex-col overflow-hidden" : "chat-panel card overflow-hidden border-indigo-200/70 bg-white/95 backdrop-blur-xl dark:border-indigo-800/60 dark:bg-slate-900/95"} role={embedded ? "region" : "dialog"} aria-label="Research assistant">
      <div className="-mx-4 -mt-4 flex items-start justify-between gap-3 border-b border-indigo-100 bg-gradient-to-br from-indigo-50 via-white to-violet-50 px-4 py-5 dark:border-slate-800 dark:from-indigo-950/70 dark:via-slate-900 dark:to-violet-950/40">
        <div><div className="flex items-center gap-2"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-600 to-violet-500 text-white shadow-md shadow-indigo-500/20"><Bot size={19} /></span><h2 className="font-semibold">Research Assistant</h2></div><p className="mt-1 text-xs text-slate-500">{pdf ? `Answering from ${pdf.name}` : state ? "Active research context and general knowledge, clearly labeled." : "Ask any question. Answers use general knowledge until research is active."}</p></div>
        <div className="flex gap-1"><button type="button" className="icon-button" onClick={clearChat} disabled={!historyReady} aria-label="Clear chat" title="Clear chat"><Trash2 size={16} /></button>{!embedded && <button type="button" className="icon-button" onClick={() => { setOpen(false); launcher.current?.focus(); }} aria-label="Close research assistant"><X size={17} /></button>}</div>
      </div>
      <div className="mt-3 flex items-center gap-2"><label className="sr-only" htmlFor="chat-history-select">Previous conversations</label><select id="chat-history-select" className="select min-w-0 flex-1" value={conversationId} onChange={(event) => chooseConversation(event.target.value)} disabled={loading || uploading}><option value={conversationId}>Current conversation</option>{recentChats.filter((chat) => chat.id !== conversationId).slice(0,20).map((chat) => <option key={chat.id} value={chat.id}>{chat.title}</option>)}</select><button type="button" className="icon-button" onClick={newConversation} disabled={loading || uploading} title="New chat" aria-label="New chat"><Plus size={16} /></button></div>
      {pdf && <div className="mt-3 rounded-xl border border-indigo-200 bg-indigo-50/50 p-3 text-xs dark:border-indigo-900 dark:bg-indigo-950/30"><div className="flex items-center gap-2"><FileText size={16} /><span className="min-w-0 flex-1 truncate" title={pdf.name}>{pdf.name} · {pdf.page_count} pages</span><button type="button" className="icon-button" aria-label="Remove PDF" disabled={loading || uploading} onClick={() => void removePDF()}><X size={14} /></button></div><p className="mt-1 text-slate-500">{pdfReady ? "PDF context active. Remove it to return to research or general chat." : "Building the document index..."}</p>{pdf.warnings.map((warning) => <p key={warning} className="mt-1 text-amber-700 dark:text-amber-300">{warning}</p>)}</div>}
      {uploading && <p role="status" className="mt-3 text-xs text-slate-500"><span className="chat-pulse mr-2 inline-block" />Extracting PDF text... Large documents may take up to 90 seconds.</p>}
      {pdfExcerpt && <div className="mt-3 max-h-48 overflow-auto rounded-xl border border-indigo-200 p-3 text-xs dark:border-indigo-900" role="region" aria-label="PDF page excerpt"><div className="flex items-center justify-between"><strong>{pdfExcerpt.title}</strong><button type="button" className="icon-button" aria-label="Close PDF excerpt" onClick={() => setPdfExcerpt(null)}><X size={14} /></button></div><p className="mt-2 whitespace-pre-wrap">{pdfExcerpt.supporting_text || "The extracted excerpt is unavailable."}</p></div>}
      <div className="chat-messages" aria-live="polite" aria-busy={loading}>
        {!messages.length && <div className="py-4"><p className="text-sm text-slate-500">{pdf ? "Ask a question about the uploaded PDF." : state ? "Ask about this report or any general question." : "How can I help you today?"}</p><div className="mt-4 flex flex-wrap gap-2">{suggestions.map((suggestion) => <button type="button" key={suggestion} className="chip text-left" disabled={!historyReady || uploading || Boolean(pdf && !pdfReady)} onClick={() => void submit(suggestion)}>{suggestion}<ChevronRight size={13} className="ml-1 inline" /></button>)}</div></div>}
        {messages.filter((message) => message.role === "user" || message.content).map((message) => <article key={message.id} className={message.role === "user" ? "chat-message chat-user rounded-2xl rounded-br-sm bg-gradient-to-br from-indigo-600 to-violet-600 shadow-sm" : "chat-message chat-assistant rounded-2xl rounded-bl-sm"}>
          {displayAnswer(message)}
          {message.citations.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{message.citations.map((citation) => { const source = citationSource(citation); return <button type="button" key={citation.citation_id} className="badge badge-indigo" title={citation.supporting_text || citation.title} onClick={() => citation.citation_id.startsWith("P") ? setPdfExcerpt(citation) : source && onPreview(source)}>[{citation.citation_id}] - {citation.title}</button>; })}</div>}
          {message.limitations.map((item) => <p key={item} className="mt-2 text-xs text-amber-700 dark:text-amber-300">{item}</p>)}
          {message.role === "assistant" && message.content && !(loading && message.id === messages[messages.length - 1]?.id) && message.complete !== false && <div className="mt-4 border-t border-slate-200/70 pt-3 dark:border-slate-800"><p className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-slate-500"><Sparkles size={12} />Explore further</p><div className="flex flex-wrap gap-2">{followUpQuestions(message).map((suggestion) => <button key={suggestion} type="button" className="chip text-left text-[11px]" disabled={loading || uploading || Boolean(pdf && !pdfReady) || !historyReady} onClick={() => void submit(suggestion)}>{suggestion}<ChevronRight size={12} className="ml-1 inline" /></button>)}</div></div>}
        </article>)}
        {loading && <div className="chat-message chat-assistant text-sm text-slate-500"><span className="inline-flex items-center gap-2"><span className="inline-flex items-center gap-1" aria-hidden="true">{[0, 1, 2].map((dot) => <span key={dot} className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-500 motion-reduce:animate-none" style={{ animationDelay: `${dot * 150}ms` }} />)}</span>{messages[messages.length - 1]?.content ? "Generating answer..." : "Preparing context..."}</span></div>}
        <div ref={threadEnd} />
      </div>
      {error && <div role="alert" className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/20 dark:text-red-300">{error}<button type="button" className="ml-2 underline" onClick={() => setError("")}>Dismiss</button></div>}
      <form className="mt-4 flex gap-2 border-t border-slate-200 pt-4 dark:border-slate-800" onSubmit={(event) => { event.preventDefault(); void submit(); }}><input ref={uploadInput} type="file" accept="application/pdf,.pdf" className="hidden" aria-label="Upload PDF file" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadPDF(file); event.target.value = ""; }} /><button type="button" className="icon-button self-end" title="Upload PDF (up to 25 MB)" aria-label="Upload PDF" disabled={loading || uploading || !historyReady} onClick={() => uploadInput.current?.click()}><Paperclip size={18} /></button><label htmlFor="research-chat-input" className="sr-only">Ask the research assistant</label><textarea ref={inputBox} id="research-chat-input" rows={2} maxLength={2000} value={input} onChange={(event) => setInput(event.target.value)} placeholder={pdf ? "Ask about this PDF..." : state ? "Ask about the report or anything else..." : "Ask anything..."} className="select min-h-12 flex-1 resize-none rounded-xl border-slate-200 bg-white text-sm dark:bg-slate-950/60" onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); } }} disabled={loading || uploading || Boolean(pdf && !pdfReady) || !historyReady} /><button className="button-primary self-end px-3" disabled={loading || uploading || Boolean(pdf && !pdfReady) || !historyReady || !input.trim()} aria-label="Send question"><ArrowUp size={18} /></button></form>
      <p className="mt-2 text-center text-[10px] text-slate-400">Enter to send · Shift + Enter for a new line</p>
    </div>}</>;
}
