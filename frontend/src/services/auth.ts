import { createClient, type Session } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL;
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
export const cloudEnabled = Boolean(url || key);
export const supabase = url && key ? createClient(url, key, {
  auth: { flowType: 'pkce', detectSessionInUrl: true, persistSession: true, autoRefreshToken: true },
}) : null;
let initializing: Promise<Session | null> | undefined;

export function initializeAuth(): Promise<Session | null> {
  if (!cloudEnabled) return Promise.resolve(null);
  if (!supabase) return Promise.reject(new Error('Supabase configuration is incomplete. See the setup guide.'));
  return initializing ??= (async () => {
    const { data, error } = await supabase!.auth.getSession();
    if (error) throw error;
    if (data.session) return data.session;
    const guest = await supabase!.auth.signInAnonymously();
    if (guest.error) throw guest.error;
    return guest.data.session;
  })().catch((error) => { initializing = undefined; throw error; });
}

export async function authHeaders(): Promise<Record<string, string>> {
  if (!cloudEnabled) return {};
  await initializeAuth();
  const { data, error } = await supabase!.auth.getSession();
  if (error || !data.session) throw new Error('Your session expired. Please sign in again.');
  return { Authorization: `Bearer ${data.session.access_token}` };
}

export async function storageScope(): Promise<string> {
  if (!cloudEnabled) return '';
  await initializeAuth();
  const { data } = await supabase!.auth.getSession();
  if (!data.session) throw new Error('Sign in to access this workspace.');
  return `-${data.session.user.id}`;
}

export async function googleLogin(existing = false): Promise<void> {
  if (!supabase) throw new Error('Configure Supabase to enable Google sign-in.');
  const { data } = await supabase.auth.getSession();
  const options = { redirectTo: window.location.origin + "/" };
  const result = !existing && data.session?.user.is_anonymous
    ? await supabase.auth.linkIdentity({ provider: 'google', options })
    : await supabase.auth.signInWithOAuth({ provider: 'google', options });
  if (result.error) throw result.error;
}

export async function signOut(): Promise<void> {
  const result = await supabase?.auth.signOut();
  if (result?.error) throw result.error;
  initializing = undefined;
  window.location.reload();
}
