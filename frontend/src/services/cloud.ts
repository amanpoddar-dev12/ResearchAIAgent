import { authHeaders, cloudEnabled, googleLogin, supabase } from './auth';
export { cloudEnabled };
const base = (import.meta.env.DEV ? '' : import.meta.env.VITE_API_URL || import.meta.env.VITE_BACKEND_URL || '').replace(/\/$/, '');
export async function cloudRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${base}/api/workspace/${path}`, { ...init,
    headers: { 'Content-Type': 'application/json', ...await authHeaders(), ...init.headers } });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Cloud workspace could not be loaded.');
  return payload as T;
}
export function cloudSave(kind: string, id: string, payload: unknown): Promise<unknown> {
  return cloudRequest(`${kind}/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(payload) });
}
export function cloudDelete(kind: string, id: string): Promise<unknown> {
  return cloudRequest(`${kind}/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

/** Keep the existing guest-workspace transfer available after Google sign-in. */
export async function signInToWorkspace(): Promise<void> {
  const { data, error } = await supabase!.auth.getSession();
  if (error) throw error;
  if (data.session?.user.is_anonymous) {
    const result = await cloudRequest<{ token: string }>('transfer', { method: 'POST' });
    sessionStorage.setItem('research-guest-transfer', result.token);
  }
  await googleLogin(true);
}
