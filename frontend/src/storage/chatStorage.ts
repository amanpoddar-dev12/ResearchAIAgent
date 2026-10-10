import type { ChatCitation, ResearchState } from "../types/research";
import type { PDFDocument } from "../rag/pdfRetrieval";
import { cloudEnabled, cloudRequest, cloudSave, cloudDelete } from '../services/cloud';
import { storageScope } from '../services/auth';
export interface ChatMessage { id: string; role: "user" | "assistant"; content: string; citations: ChatCitation[]; limitations: string[]; pdfName?: string; complete?: boolean }
export interface ChatRecord { id: string; title: string; updatedAt: string; messages: ChatMessage[]; draft: string; state: ResearchState | null; pdfName?: string; collectionId?: string }
export function createChat(state: ResearchState | null): ChatRecord {
  return { id: `general-chat-${crypto.randomUUID()}`, title: 'New conversation', updatedAt: new Date().toISOString(), messages: [], draft: '', state };
}
const DB = "research-assistant-local";
export function generalChatId(): string {
  try {
    const previous = localStorage.getItem("research-assistant-current-chat");
    if (previous && /^general-chat-[a-f0-9-]{36}$/.test(previous)) return previous;
    const id = `general-chat-${crypto.randomUUID()}`;
    localStorage.setItem("research-assistant-current-chat", id); return id;
  } catch { return `general-chat-${crypto.randomUUID()}`; }
}
async function store<T>(name: string, mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>, legacy = false): Promise<T> {
  const scope = legacy ? '' : await storageScope();
  const db = await new Promise<IDBDatabase>((resolve, reject) => {
    const open = indexedDB.open(DB + scope, 1);
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
export async function loadChat(id: string): Promise<ChatRecord | undefined> {
  if (cloudEnabled) {
    const chat = await cloudRequest<ChatRecord | null>(`chat/${encodeURIComponent(id)}`);
    const local = await store<ChatRecord | undefined>('chats', 'readonly', (s) => s.get(id));
    const restored = chat ? { ...chat, draft: local?.draft || '' } : local;
    if (restored) await store('chats', 'readwrite', (s) => s.put(restored));
    return restored || undefined;
  }
  return store('chats', 'readonly', (s) => s.get(id));
}
export async function listChats(): Promise<ChatRecord[]> {
  const chats = cloudEnabled ? await cloudRequest<ChatRecord[]>('chat') : await store<ChatRecord[]>('chats', 'readonly', (s) => s.getAll());
  return chats.filter(chat => chat.messages.length || chat.draft.trim()).sort((a,b) => b.updatedAt.localeCompare(a.updatedAt));
}
export async function saveChat(chat: ChatRecord): Promise<void> {
  if (cloudEnabled) {
    const previous = await store<ChatRecord | undefined>('chats', 'readonly', (s) => s.get(chat.id));
    // Draft keystrokes stay local; cloud writes occur only when messages change.
    if (!previous || JSON.stringify(previous.messages) !== JSON.stringify(chat.messages) || previous.pdfName !== chat.pdfName || previous.state?.final_report !== chat.state?.final_report) await cloudSave('chat', chat.id, { ...chat, draft: '' });
  }
  await store('chats', 'readwrite', (s) => s.put(chat));
}
export async function loadPDF(id: string): Promise<PDFDocument | undefined> {
  if (cloudEnabled) return (await cloudRequest<PDFDocument | null>(`pdf/${encodeURIComponent(id)}`)) || undefined;
  return store('pdfs', 'readonly', (s) => s.get(id));
}
export async function savePDF(id: string, pdf: PDFDocument | null): Promise<void> {
  if (cloudEnabled) { if (pdf) await cloudSave('pdf', id, pdf); else await cloudDelete('pdf', id); }
  if (pdf) await store('pdfs', 'readwrite', (s) => s.put(pdf, id)); else await store('pdfs', 'readwrite', (s) => s.delete(id));
}
export async function listLocalChats(): Promise<ChatRecord[]> { return store('chats', 'readonly', (s) => s.getAll(), true); }export async function deleteChat(id: string): Promise<void> {  if (cloudEnabled) await cloudDelete('chat', id);  await store('chats', 'readwrite', (s) => s.delete(id));}
export async function loadLocalPDF(id: string): Promise<PDFDocument | undefined> { return store('pdfs', 'readonly', (s) => s.get(id), true); }
