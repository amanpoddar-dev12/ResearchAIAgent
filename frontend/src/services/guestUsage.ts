import { useEffect, useSyncExternalStore } from 'react';
import { cloudEnabled, initializeAuth } from './auth';
import { cloudRequest } from './cloud';

export interface WorkspaceUsage { guest: boolean; remaining: number | null; limit: number | null }
interface UsageState { usage: WorkspaceUsage | null; error: string }
let state: UsageState = { usage: null, error: '' };
let pending: Promise<WorkspaceUsage> | undefined;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(listener => listener());
const snapshot = () => state;
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };

/** Read the authoritative persisted allowance, never reset it in browser storage. */
export function refreshGuestUsage(): Promise<WorkspaceUsage> {
  return pending ??= cloudRequest<WorkspaceUsage>('usage').then(usage => {
    state = { usage, error: '' }; notify(); return usage;
  }).catch((error: unknown) => {
    state = { ...state, error: error instanceof Error ? error.message : 'Could not check research credits.' };
    notify(); throw error;
  }).finally(() => { pending = undefined; });
}

export function useGuestUsage(): UsageState {
  const value = useSyncExternalStore(subscribe, snapshot);
  useEffect(() => {
    if (!cloudEnabled) return;
    const refresh = () => { void refreshGuestUsage().catch(() => {}); };
    const visible = () => { if (document.visibilityState === 'visible') refresh(); };
    refresh();
    window.addEventListener('research-usage-changed', refresh);
    window.addEventListener('focus', refresh);
    document.addEventListener('visibilitychange', visible);
    return () => {
      window.removeEventListener('research-usage-changed', refresh);
      window.removeEventListener('focus', refresh);
      document.removeEventListener('visibilitychange', visible);
    };
  }, []);
  return value;
}

/** Check persisted credits before any research request or clearing existing results. */
export async function validateResearchCredits(): Promise<boolean> {
  const session = await initializeAuth();
  if (session && !session.user.is_anonymous) return true;
  const usage = await refreshGuestUsage();
  if (usage.guest && usage.remaining === 0) {
    window.dispatchEvent(new Event('research-login-required'));
    return false;
  }
  return true;
}
