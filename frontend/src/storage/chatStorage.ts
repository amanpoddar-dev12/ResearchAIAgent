import type { ChatCitation, ResearchState } from "../types/research";
import type { PDFDocument } from "../rag/pdfRetrieval";
export interface ChatMessage { id: string; role: "user" | "assistant"; content: string; citations: ChatCitation[]; limitations: string[]; pdfName?: string; complete?: boolean }
export interface ChatRecord { id: string; title: string; updatedAt: string; messages: ChatMessage[]; draft: string; state: ResearchState | null }
const DB = "research-assistant-local";
export function generalChatId(): string {
  try {
    const previous = localStorage.getItem("research-assistant-current-chat");
    if (previous && /^general-chat-[a-f0-9-]{36}$/.test(previous)) return previous;
    const id = `general-chat-${crypto.randomUUID()}`;
    localStorage.setItem("research-assistant-current-chat", id); return id;
  } catch { return `general-chat-${crypto.randomUUID()}`; }
}
async function store<T>(name: string, mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const open = indexedDB.open(DB, 1);
    open.onupgradeneeded = () => { open.result.createObjectStore("chats", { keyPath: "id" }); open.result.createObjectStore("pdfs"); };
    open.onsuccess = () => resolve(open.result); open.onerror = () => reject(open.error);
  });
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(name, mode);
    const request = action(transaction.objectStore(name));
    transaction.oncomplete = () => { db.close(); resolve(request.result); };
    transaction.onerror = transaction.onabort = () => { db.close(); reject(transaction.error || new Error("Browser storage is unavailable.")); };
  });
}
export async function loadChat(id: string): Promise<ChatRecord | undefined> { return store("chats", "readonly", (s) => s.get(id)); }
export async function listChats(): Promise<ChatRecord[]> { const chats = await store<ChatRecord[]>("chats", "readonly", (s) => s.getAll()); return chats.filter((chat) => chat.messages.length).sort((a,b) => b.updatedAt.localeCompare(a.updatedAt)); }
export async function saveChat(chat: ChatRecord): Promise<void> { await store("chats", "readwrite", (s) => s.put(chat)); }
export async function loadPDF(id: string): Promise<PDFDocument | undefined> { return store("pdfs", "readonly", (s) => s.get(id)); }
export async function savePDF(id: string, pdf: PDFDocument | null): Promise<void> { if (pdf) await store("pdfs", "readwrite", (s) => s.put(pdf, id)); else await store("pdfs", "readwrite", (s) => s.delete(id)); }
