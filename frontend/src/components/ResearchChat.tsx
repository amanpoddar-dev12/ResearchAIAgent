import { ResearchCompanion } from "./ResearchCompanion";
import { assistantEndpoint, libraryRequest } from '../services/api';
import { cloudEnabled } from '../services/auth';
import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, ChevronRight, MessageCircle, ArrowUp, Sparkles, Trash2, X, Paperclip, FileText, Plus } from "lucide-react";
import type { ChatCitation, ChatResponse, Evidence, Finding, ResearchEvent, ResearchSource, ResearchState } from "../types/research";
import { listSavedResearch, type SavedResearch } from "../storage/researchStorage";

import { createChat, deleteChat, loadChat, listChats, saveChat, loadPDF, savePDF } from "../storage/chatStorage";
import type { ChatMessage, ChatRecord } from "../storage/chatStorage";
import type { PDFDocument, PDFContext } from "../rag/pdfRetrieval";
import { authHeaders } from '../services/auth';
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

export function ResearchChat({ researchId, state: researchState, findings: researchFindings, evidence: researchEvidence, sources: researchSources, onPreview, embedded = false, collectionId }: {
  researchId: string; state: ResearchState | null; findings: Finding[]; evidence: Evidence[]; sources: ResearchSource[]; onPreview: (source: ResearchSource) => void; embedded?: boolean;
  collectionId?: string;
}) {
  const [conversationId, setConversationId] = useState(researchId);
  const [attachedCollection, setAttachedCollection] = useState(collectionId);
  const [contextOverride, setContextOverride] = useState<ResearchState | null | undefined>(undefined);
  const state = contextOverride === undefined ? researchState : contextOverride;
  const findings = contextOverride === undefined ? researchFindings : state?.findings || emptyFindings;
  const evidence = contextOverride === undefined ? researchEvidence : state?.evidence || emptyEvidence;
  const sources = contextOverride === undefined ? researchSources : state?.sources || emptySources;
  // Cloud collection chats retain a reference, not a duplicate of large PDFs.
  const persistedState = cloudEnabled && attachedCollection && state?.question.question.startsWith('Research collection:') ? null : state ? { ...state, findings, evidence, sources } : null;
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
  const pdfDialog = useRef<HTMLDialogElement>(null);
  const latestAnswer = [...messages].reverse().find((message) => message.role === "assistant" && message.complete !== false)?.id;
  const chatWindow = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    setHistoryReady(false); setMessages([]); setInput(""); setPdf(null); setError("");
    Promise.all([loadChat(conversationId), loadPDF(conversationId)]).then(async ([saved, document]) => {
      if (!saved && conversationId === researchId) {
        const research = (await listSavedResearch()).find((item) => item.id === researchId) as SavedResearchWithChat | undefined;
        if (research?.assistantChat) saved = { id: conversationId, title: research.question, updatedAt: research.savedAt, messages: research.assistantChat, draft: "", state: research.state };
      }
      let savedContext = saved?.state;
      if (saved?.collectionId && cloudEnabled) savedContext = await libraryRequest<ResearchState>(`library/collections/${saved.collectionId}/context`);
      if (!active) return;
      setAttachedCollection(saved?.collectionId || collectionId);
      const history = Array.isArray(saved?.messages) ? saved.messages.filter((item) => item && typeof item.content === "string" && ["user", "assistant"].includes(item.role)) : [];
      setMessages(history.map((item) => ({ ...item, citations: Array.isArray(item.citations) ? item.citations : [], limitations: Array.isArray(item.limitations) ? item.limitations : [] })));
      setInput(saved?.draft || "");
      if (saved && (conversationId !== researchId || !researchState)) setContextOverride(savedContext);
      setPdf(document || null); setHistoryReady(true);
    }).catch((error) => { if (active) { setHistoryReady(false); setError(error instanceof Error ? error.message : 'Chat history could not be loaded.'); } });
    return () => { active = false; activeRequest.current?.abort(); uploadRequest.current?.abort(); };
  }, [conversationId, researchId]);

  const persistMessages = (history: ChatMessage[]) => {
    const record: ChatRecord = { id: conversationId, title: history.find((item) => item.role === "user")?.content.slice(0,100) || "New conversation", updatedAt: new Date().toISOString(), messages: history, draft: "", pdfName: pdf?.name, collectionId: state?.question.question.startsWith("Research collection:") ? attachedCollection : undefined, state: persistedState };
    saving.current = saving.current.catch(() => {}).then(() => saveChat(record)).then(() => {
      setRecentChats((items) => [record, ...items.filter((item) => item.id !== record.id)]);
    }).catch((error) => setError(error instanceof Error ? error.message : 'Chat history could not be saved.'));
  };

  useEffect(() => { listChats().then(setRecentChats).catch(() => {}); }, []);
  useEffect(() => {
    if (!historyReady || loading) return;
    const timer = window.setTimeout(() => {
      const record: ChatRecord = { id: conversationId, title: messages.find((item) => item.role === "user")?.content.slice(0, 100) || "New conversation", updatedAt: new Date().toISOString(), messages, draft: input, pdfName: pdf?.name, collectionId: state?.question.question.startsWith("Research collection:") ? attachedCollection : undefined, state: persistedState };
      saving.current = saving.current.catch(() => {}).then(() => saveChat(record)).then(() => {
        setRecentChats((items) => [record, ...items.filter((item) => item.id !== record.id)]);
      }).catch((error) => setError(error instanceof Error ? error.message : 'Chat history could not be saved; your current chat remains open.'));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [historyReady, loading, messages, input, conversationId, state, findings, evidence, sources, pdf]);

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

  const chooseConversation = async (id: string) => {
    if (id === conversationId) return;
    setHistoryReady(false);
    try {
      await saving.current;
      await saveChat({ id: conversationId, title: messages.find((item) => item.role === 'user')?.content.slice(0, 100) || 'New conversation', updatedAt: new Date().toISOString(), messages, draft: input, pdfName: pdf?.name, collectionId: state?.question.question.startsWith("Research collection:") ? attachedCollection : undefined, state: persistedState });
    } catch (error) {
      setHistoryReady(true);
      setError(error instanceof Error ? error.message : 'Save this conversation before switching.');
      return;
    }
    if (id.startsWith("general-chat-")) { try { localStorage.setItem("research-assistant-current-chat", id); } catch { /* Optional selected-thread preference. */ } }
    activeRequest.current?.abort(); uploadRequest.current?.abort();
    setHistoryReady(false); setLoading(false); setUploading(false); setContextOverride(id === researchId ? undefined : null); setConversationId(id); setPdfExcerpt(null);
  };
  const newConversation = async (general = false) => {
    const record = createChat(general || !state ? null : { ...state, findings, evidence, sources });
    if (!general && state?.question.question.startsWith('Research collection:')) { record.collectionId = attachedCollection; if (cloudEnabled) record.state = null; }
    setHistoryReady(false); setError('');
    try {
      await saving.current;
      // Save before switching so the load effect restores this thread's exact context.
      if (!general && pdf) await savePDF(record.id, pdf);
      await saveChat(record);
      setRecentChats((items) => [record, ...items]);
      await chooseConversation(record.id);
    } catch (error) {
      setHistoryReady(true);
      setError(error instanceof Error ? error.message : 'The new conversation could not be saved.');
    }
  };
  const uploadPDF = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf") || file.size > 25 * 1024 * 1024) { setError("Choose a PDF that is 25 MB or smaller."); return; }
    const controller = new AbortController(); uploadRequest.current = controller;
    setUploading(true); setError("");
    try {
      const response = await fetch(`${apiUrl}/api/assistant/pdf?name=${encodeURIComponent(file.name.slice(0,200))}`, { method: "POST", headers: { "Content-Type": "application/pdf", ...await authHeaders() }, body: file, signal: controller.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "This PDF could not be processed.");
      if (controller.signal.aborted) return;
      const document = data as PDFDocument;
      setPdf(document);
      try { await savePDF(conversationId, document); } catch (error) { setError(error instanceof Error ? error.message : 'PDF is ready, but its conversation attachment could not be saved.'); }
    } catch (uploadError) { if (!controller.signal.aborted) setError(uploadError instanceof Error ? uploadError.message : "PDF upload failed."); }
    finally { if (!controller.signal.aborted) setUploading(false); }
  };
  const removePDF = async () => { try { await savePDF(conversationId, null); setPdf(null); setPdfExcerpt(null); } catch (error) { setError(error instanceof Error ? error.message : 'The PDF attachment could not be removed.'); } };

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

  useEffect(() => {
    if (!pdfExcerpt) return;
    const dialog = pdfDialog.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, [pdfExcerpt]);

  useEffect(() => {
    const viewport = window.visualViewport;
    const update = () => {
      if (!chatWindow.current) return;
      const available = viewport?.height ?? window.innerHeight;
      const bottom = Math.max(0, window.innerHeight - available - (viewport?.offsetTop ?? 0));
      chatWindow.current.style.setProperty("--chat-viewport-height", `${available}px`);
      chatWindow.current.style.setProperty("--chat-keyboard-offset", `${bottom}px`);
      chatWindow.current.classList.toggle("chat-keyboard-open", bottom > 100);
    };
    update(); viewport?.addEventListener("resize", update); viewport?.addEventListener("scroll", update);
    return () => { viewport?.removeEventListener("resize", update); viewport?.removeEventListener("scroll", update); };
  }, [open, embedded]);

  const suggestions = useMemo(() => {
    if (pdf) return ["Summarize the main points of this PDF.", "What conclusions are supported by this PDF?", "What limitations does this PDF mention?"];
    if (!state) return ["Explain what an API is.", "Help me understand a topic step by step.", "How can I evaluate whether a source is reliable?"];
    const title = (state.structured_report?.title || state.final_report?.match(/^#\s+(.+)$/m)?.[1] || state.question.refined_question || state.question.question).slice(0, 140);
    const chart = state.structured_report?.charts[0];
    const claim = findings[0];
    const limitation = state.structured_report?.sections.find((section) => /limitation|gap|future/i.test(section.title));
    return [
      "What were the main findings?",
      chart ? "Explain the first chart in this report." : claim ? `What evidence supports "${claim.claim.slice(0, 140)}"?` : `Which sources support the report "${title}"?`,
      limitation ? "Explain the report’s limitations and unanswered questions." : `What limitations does "${title}" identify?`,
    ];
  }, [state, findings, pdf]);

  const clearChat = () => {
    if (!window.confirm("Clear all messages in this conversation? This cannot be undone. The research context and PDF attachment will remain.")) return;
    activeRequest.current?.abort(); activeRequest.current = null;
    setMessages([]); setInput(""); setError(""); setLoading(false);
  };  const removeConversation = async () => {    if (!window.confirm('Permanently delete this conversation and its messages? Saved research and uploaded PDF files will remain.')) return;    setHistoryReady(false);    try {      await saving.current;      const record = createChat(null);      await saveChat(record);      await deleteChat(conversationId);      setRecentChats(items => items.filter(item => item.id !== conversationId));      try { localStorage.setItem('research-assistant-current-chat', record.id); } catch { /* Optional preference. */ }      setContextOverride(null); setPdf(null); setMessages([]); setInput(''); setConversationId(record.id);    } catch (error) { setHistoryReady(true); setError(error instanceof Error ? error.message : 'The conversation could not be deleted.'); }  };

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
      const selectedCollection = attachedCollection && state?.question.question.startsWith('Research collection:') && !pdfContext ? attachedCollection : undefined;
      const response = await fetch(assistantEndpoint(conversationId, selectedCollection), {
        method: "POST", headers: { "Content-Type": "application/json", ...await authHeaders() }, signal: controller.signal,
        body: JSON.stringify({ message, history, ...(selectedCollection ? { conversation_id: conversationId } : {}), ...(pdfContext ? { pdf_context: pdfContext } : {}), ...(state && !selectedCollection ? { saved_state: { ...state, findings, evidence, sources } } : {}) }),
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

  const citationSource = (citation: ChatCitation) => {
    const source = sources.find((source) => source.id === citation.source_id) || sources.find((source) => source.url === citation.url);
    return (attachedCollection || state?.question.question.startsWith('Research collection:')) && source ? { ...source, contextScope: 'collection' as const, title: citation.title, url: citation.url || '', content: citation.supporting_text || source.content } : source;
  };
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
    return <>{origin && <span className={`badge mb-2 ${origin === "From research" ? "badge-success" : origin === "General knowledge" ? "badge-indigo" : "bg-warning/10 text-warning dark:bg-warning/10 dark:text-warning"}`}>{message.pdfName && origin === "From research" ? "From PDF" : origin}</span>}<p className="whitespace-pre-wrap text-sm leading-6">{body}</p></>;
  };

  return <>{!embedded && <button ref={launcher} type="button" className="chat-launcher button-primary rounded-full    px-5 py-3 shadow-soft   " onClick={() => setOpen(true)} aria-label="Open research assistant" aria-expanded={open} aria-controls="research-chat-panel"><MessageCircle size={18} /> Ask assistant<Sparkles size={14} className="opacity-80" /></button>}
    {(embedded || open) && <div ref={chatWindow} id="research-chat-panel" className={embedded ? "card chat-workspace-panel flex min-h-[28rem] flex-col overflow-hidden" : "chat-panel card overflow-hidden border-border/70 bg-surface  dark:border-border/60 dark:bg-surface"} role={embedded ? "region" : "dialog"} aria-label="Research assistant">
      <div className="chat-header -mx-4 -mt-4 flex shrink-0 items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div><div className="flex items-center gap-2"><span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary "><Bot size={19} /></span><h2 className="font-medium">Research Assistant</h2></div><p className="mt-1 text-xs text-muted-foreground">{pdf ? `PDF: ${pdf.name}` : state ? `Research: ${state.question.refined_question || state.question.question}` : "General conversation"}</p></div>
        <div className="flex gap-1"><button type="button" className="button-secondary px-2 text-xs" onClick={() => void newConversation()} disabled={!historyReady || loading || uploading} aria-label="New chat"><Plus size={16} />New chat</button>{!embedded && <button type="button" className="icon-button" onClick={() => { setOpen(false); launcher.current?.focus(); }} aria-label="Close research assistant"><X size={17} /></button>}</div>
      </div>
      <details className="chat-context mt-2 shrink-0 rounded-lg border border-border px-3 py-2"><summary className="cursor-pointer text-xs">Using: {pdf ? 'uploaded PDF' : state ? 'research report' : 'general knowledge'}</summary><p className="mt-2 break-words text-xs text-muted-foreground">{pdf ? `${pdf.name} · ${pdf.page_count} pages. Answers use passages retrieved from this document.` : state ? state.question.refined_question || state.question.question : 'No research or document is attached to this conversation.'}</p></details>
      <details className="chat-tools mt-3 shrink-0 rounded-xl border border-border px-3 py-2"><summary className="cursor-pointer text-xs text-muted-foreground">Chats &amp; documents{pdf ? ` · ${pdf.page_count} pages` : ""}</summary>
      <div className="mt-3 flex shrink-0 items-center gap-2"><label className="sr-only" htmlFor="chat-history-select">Previous conversations</label><select id="chat-history-select" className="select min-w-0 flex-1 text-sm" value={conversationId} onChange={(event) => chooseConversation(event.target.value)} disabled={!historyReady || loading || uploading}><option value={conversationId}>{recentChats.find((chat) => chat.id === conversationId)?.title || "Current conversation"}</option>{recentChats.filter((chat) => chat.id !== conversationId && (chat.messages.length || chat.draft.trim())).map((chat) => <option key={chat.id} value={chat.id}>{chat.title} · {new Date(chat.updatedAt).toLocaleDateString()}</option>)}</select><button type="button" className="button-secondary shrink-0 px-2 text-xs" onClick={() => void newConversation(true)} disabled={!historyReady || loading || uploading}>General chat</button></div>
      <button type="button" className="button-secondary mt-3 text-xs" onClick={clearChat} disabled={!historyReady}><Trash2 size={14} />Clear messages</button>
      <p className="mt-2 text-xs text-muted-foreground">New chat keeps the selected research and PDF. General chat starts without either.</p>      <button type="button" className="button-secondary mt-3 text-xs text-destructive" disabled={loading || uploading || !historyReady} onClick={() => void removeConversation()}>Delete this conversation</button>
      {pdf && <div className="mt-3 rounded-xl border border-border bg-accent/10 p-3 text-xs dark:border-border dark:bg-primary/10"><div className="flex items-center gap-2"><FileText size={16} /><span className="min-w-0 flex-1 truncate" title={pdf.name}>{pdf.name} · {pdf.page_count} pages</span><button type="button" className="icon-button" aria-label="Remove PDF" disabled={loading || uploading} onClick={() => void removePDF()}><X size={14} /></button></div><p className="mt-1 text-muted-foreground">{pdfReady ? "PDF context active. Remove it to return to research or general chat." : "Building the document index..."}</p>{pdf.warnings.map((warning) => <p key={warning} className="mt-1 text-warning dark:text-warning">{warning}</p>)}</div>}
      </details>
      {pdf && !pdfReady && !uploading && <p role="status" className="mt-2 text-xs text-muted-foreground">Preparing the PDF index...</p>}
      {uploading && <p role="status" className="mt-3 text-xs text-muted-foreground"><span className="chat-pulse mr-2 inline-block" />Extracting PDF text... Large documents may take up to 90 seconds.</p>}
      {pdfExcerpt && <dialog ref={pdfDialog} onCancel={() => setPdfExcerpt(null)} onClose={() => { if (pdfDialog.current && !pdfDialog.current.open) setPdfExcerpt(null); }} className="pdf-excerpt-preview w-[min(94vw,42rem)] max-h-[80dvh] overflow-auto rounded-xl border border-border bg-surface p-6 text-foreground" aria-labelledby="pdf-excerpt-title"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><span className="badge badge-indigo">Page {pdfExcerpt.citation_id.slice(1)}</span><h2 id="pdf-excerpt-title" className="mt-3 break-words">{pdfExcerpt.title}</h2></div><button autoFocus type="button" className="icon-button" aria-label="Close PDF excerpt" onClick={() => setPdfExcerpt(null)}><X size={18} /></button></div><p className="mt-4 text-xs text-muted-foreground">Extracted passage used for this answer</p><blockquote className="mt-2 whitespace-pre-wrap border-l-2 border-link bg-accent/10 p-4 text-sm leading-6">{pdfExcerpt.supporting_text || "The extracted excerpt is unavailable."}</blockquote></dialog>}
      {!historyReady && !error && <p role="status" className="mt-2 text-xs text-muted-foreground">Loading conversation and context...</p>}
      <div className="chat-messages" aria-live="polite" aria-busy={loading}>
        {!messages.length && <div className="py-4"><p className="text-sm text-muted-foreground">{pdf ? "Ask a question about the uploaded PDF." : state ? "Ask about this report or any general question." : "How can I help you today?"}</p><div className="mt-4 flex flex-wrap gap-2">{suggestions.map((suggestion) => <button type="button" key={suggestion} className="chip text-left" disabled={!historyReady || uploading || Boolean(pdf && !pdfReady)} onClick={() => void submit(suggestion)}>{suggestion}<ChevronRight size={13} className="ml-1 inline" /></button>)}</div></div>}
        {messages.filter((message) => message.role === "user" || message.content).map((message) => <article key={message.id} className={message.role === "user" ? "chat-message chat-user rounded-xl rounded-br-sm    shadow-soft" : "chat-message chat-assistant rounded-xl rounded-bl-sm"}>
          {displayAnswer(message)}
          {message.citations.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{message.citations.map((citation) => { const source = citationSource(citation); return <button type="button" key={citation.citation_id} className="badge badge-indigo" title={citation.supporting_text || citation.title} onClick={() => citation.citation_id.startsWith("P") ? setPdfExcerpt(citation) : source && onPreview(source)}>[{citation.citation_id}] - {citation.title}</button>; })}</div>}
          {message.limitations.map((item) => <p key={item} className="mt-2 text-xs text-warning dark:text-warning">{item}</p>)}
          {message.role === "assistant" && message.content && !(loading && message.id === messages[messages.length - 1]?.id) && message.complete !== false && <details className="mt-3 border-t border-border pt-2" open={message.id === latestAnswer}><summary className="cursor-pointer text-xs text-muted-foreground">Explore further</summary><div className="flex flex-wrap gap-2">{followUpQuestions(message).map((suggestion) => <button key={suggestion} type="button" className="chip text-left text-[11px]" disabled={loading || uploading || Boolean(pdf && !pdfReady) || !historyReady} onClick={() => void submit(suggestion)}>{suggestion}<ChevronRight size={12} className="ml-1 inline" /></button>)}</div></details>}
        </article>)}
        {loading && <div className="chat-message chat-assistant text-sm text-muted-foreground"><span className="inline-flex items-center gap-2"><span className="inline-flex items-center gap-1" aria-hidden="true">{[0, 1, 2].map((dot) => <span key={dot} className="h-1.5 w-1.5  rounded-full bg-primary motion-reduce:animate-none" style={{ animationDelay: `${dot * 150}ms` }} />)}</span>{messages[messages.length - 1]?.content ? "Generating answer..." : "Preparing context..."}</span></div>}
        <div ref={threadEnd} />
      </div>
      {error && <div role="alert" className="mt-3 rounded-lg border border-border bg-destructive/10 p-3 text-xs text-destructive dark:border-border dark:bg-destructive/10 dark:text-destructive">{error}<button type="button" className="ml-2 underline" onClick={() => setError("")}>Dismiss</button></div>}
      <ResearchCompanion active={loading || uploading} compact />
      <form className="chat-composer mt-1 shrink-0 flex gap-2" onSubmit={(event) => { event.preventDefault(); void submit(); }}><input ref={uploadInput} type="file" accept="application/pdf,.pdf" className="hidden" aria-label="Upload PDF file" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadPDF(file); event.target.value = ""; }} /><button type="button" className="icon-button self-end" title="Upload PDF (up to 25 MB)" aria-label="Upload PDF" disabled={loading || uploading || !historyReady} onClick={() => uploadInput.current?.click()}><Paperclip size={18} /></button><label htmlFor="research-chat-input" className="sr-only">Ask the research assistant</label><textarea ref={inputBox} id="research-chat-input" rows={2} maxLength={2000} value={input} onChange={(event) => setInput(event.target.value)} placeholder={pdf ? "Ask about this PDF..." : state ? "Ask about the report or anything else..." : "Ask anything..."} className="chat-input select min-h-12 flex-1 resize-none text-sm" onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); } }} disabled={loading || uploading || Boolean(pdf && !pdfReady) || !historyReady} /><button className="button-primary self-end px-3" disabled={loading || uploading || Boolean(pdf && !pdfReady) || !historyReady || !input.trim()} aria-label="Send question" title="Send question"><ArrowUp size={18} /></button></form>
      <p className="mt-2 text-center text-[10px] text-muted-foreground">Enter to send · Shift + Enter for a new line</p>
    </div>}</>;
}
