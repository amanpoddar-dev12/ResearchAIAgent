import { cloudEnabled, cloudRequest, cloudSave } from '../services/cloud';
import { storageScope } from '../services/auth';
export interface Collection { id: string; name: string; researchIds: string[]; chatIds: string[]; pdfIds: string[] }
export interface ReportFeedback { id: string; researchId: string; section: string; category: 'Helpful' | 'Missing information' | 'Citation issue'; note: string; createdAt: string }
export async function listProductivity<T>(kind: 'collection' | 'feedback'): Promise<T[]> {
  if (cloudEnabled) return cloudRequest<T[]>(kind);
  const key = `findingsai-${kind}${await storageScope()}`;
  return JSON.parse(localStorage.getItem(key) || '[]') as T[];
}
export async function saveProductivity<T extends { id: string }>(kind: 'collection' | 'feedback', item: T): Promise<void> {
  if (cloudEnabled) { await cloudSave(kind, item.id, item); return; }
  const key = `findingsai-${kind}${await storageScope()}`;
  const entries = await listProductivity<T>(kind);
  localStorage.setItem(key, JSON.stringify([item, ...entries.filter(entry => entry.id !== item.id)]));
}
