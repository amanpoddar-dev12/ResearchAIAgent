import type { ResearchMode, ResearchSource, ResearchState, StructuredReport } from "../types/research";
import { cloudEnabled, cloudRequest, cloudSave, cloudDelete } from '../services/cloud';
import { storageScope } from '../services/auth';

export interface SavedResearch {
  id: string;
  question: string;
  mode: ResearchMode;
  report: string;
  structuredReport?: StructuredReport;
  sources: ResearchSource[];
  state: ResearchState;
  savedAt: string;
  name?: string;
}

const DB_NAME = "research-agent";
const STORE_NAME = "saved-research";
const FALLBACK_KEY = "research-agent-saved-research";

function fallbackRead(): SavedResearch[] {
  try { return JSON.parse(localStorage.getItem(FALLBACK_KEY) || "[]") as SavedResearch[]; } catch { return []; }
}

function fallbackWrite(items: SavedResearch[]) {
  localStorage.setItem(FALLBACK_KEY, JSON.stringify(items));
}

function openDb(scope = ''): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME + scope, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE_NAME, { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore<T>(mode: IDBTransactionMode, action: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDb(await storageScope());
  return new Promise((resolve, reject) => {
    const request = action(db.transaction(STORE_NAME, mode).objectStore(STORE_NAME));
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function listSavedResearch(): Promise<SavedResearch[]> {
  if (cloudEnabled) return (await cloudRequest<SavedResearch[]>('research')).filter((item) => item.state && item.report);
  try {
    const items = await withStore<SavedResearch[]>("readonly", (store) => store.getAll());
    return items.sort((a, b) => b.savedAt.localeCompare(a.savedAt));
  } catch { return fallbackRead().sort((a, b) => b.savedAt.localeCompare(a.savedAt)); }
}

export async function saveResearch(item: SavedResearch): Promise<void> {
  if (cloudEnabled) { await cloudSave('research', item.id, item); return; }
  try { await withStore("readwrite", (store) => store.put(item)); }
  catch (error) {
    try { fallbackWrite([item, ...fallbackRead().filter((entry) => entry.id !== item.id)]); }
    catch { throw error; }
  }
}

export async function deleteSavedResearch(id: string): Promise<void> {
  if (cloudEnabled) { await cloudDelete('research', id); return; }
  try { await withStore("readwrite", (store) => store.delete(id)); }
  catch { fallbackWrite(fallbackRead().filter((item) => item.id !== id)); }
}

export async function clearSavedResearch(): Promise<void> {
  if (cloudEnabled) { for (const item of await listSavedResearch()) await cloudDelete('research', item.id); return; }
  try { await withStore("readwrite", (store) => store.clear()); }
  catch { fallbackWrite([]); }
}

export function toSavedResearch(id: string, question: string, mode: ResearchMode, report: string, state: ResearchState): SavedResearch {
  const sources = state.sources;
  const safeState = { ...state, sources };
  return { id, question, mode, report, structuredReport: state.structured_report, sources, state: safeState, savedAt: new Date().toISOString() };
}

export async function listLocalResearch(): Promise<SavedResearch[]> {
  try {
    const db = await openDb();
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE_NAME, 'readonly');
      const request = transaction.objectStore(STORE_NAME).getAll();
      transaction.oncomplete = () => { db.close(); resolve(request.result); };
      transaction.onerror = () => { db.close(); reject(transaction.error); };
    });
  } catch { return fallbackRead(); }
}
