import { GoogleIcon } from "./GoogleIcon";
import { useEffect, useRef, useState } from 'react';
import type { Session } from '@supabase/supabase-js';
import { cloudEnabled, googleLogin, initializeAuth, signOut, supabase } from '../services/auth';
import { cloudRequest, cloudSave, signInToWorkspace } from '../services/cloud';
import { useGuestUsage } from '../services/guestUsage';
import { listLocalResearch } from '../storage/researchStorage';
import { listLocalChats, loadLocalPDF } from '../storage/chatStorage';

export function AccountPanel() {
  const [session, setSession] = useState<Session | null>(null);
  const { usage } = useGuestUsage();
  const remaining = usage?.remaining ?? null;
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [transfer] = useState(() => sessionStorage.getItem('research-guest-transfer'));
  const owner = useRef<string | null>(null);
  useEffect(() => {
    if (!cloudEnabled) return;
    let active = true;
    void initializeAuth().then((value) => { if (active) { setSession(value); } }).catch((e) => { if (active) setError(e.message); });
    const subscription = supabase?.auth.onAuthStateChange((_event, value) => {
      if (!active) return;
      const next = value?.user.id || null;
      // Clear rendered research as well as caches when another tab changes accounts.
      if (owner.current && owner.current !== next) { window.location.reload(); return; }
      owner.current = next; setSession(value);
    });
    return () => { active = false; subscription?.data.subscription.unsubscribe(); };
  }, []);
  if (!cloudEnabled) return null;
  const action = async (operation: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await operation(); } catch (e) { setError(e instanceof Error ? e.message : 'Account action failed.'); }
    finally { setBusy(false); }
  };
  const importLocal = async () => {
    for (const item of await listLocalResearch()) await cloudSave('research', item.id, item);
    for (const chat of await listLocalChats()) {
      await cloudSave('chat', chat.id, chat);
      const pdf = await loadLocalPDF(chat.id);
      if (pdf) await cloudSave('pdf', chat.id, pdf);
    }
    window.location.reload();
  };
  return <div className="mt-4 max-h-56 shrink-0 space-y-2 overflow-y-auto border-t border-border pt-3 text-xs break-words">
    <p className="font-medium">{session?.user.is_anonymous ? 'Guest workspace' : session?.user.email || 'Cloud workspace'}</p>
    {session?.user.is_anonymous ? <><p className="text-muted-foreground">{remaining === null ? 'Loading allowance…' : remaining === 0 ? 'Your 5 free credits are used up. Sign in to continue.' : `${remaining} of 5 research runs remaining`}</p>
      <button className="button-primary w-full google-login-button" aria-label="Continue with Google" disabled={busy} onClick={() => void action(() => googleLogin())}><GoogleIcon /><span className="google-login-text">Continue with Google</span></button>
      <button className="text-muted-foreground underline" disabled={busy} onClick={() => void action(signInToWorkspace)}>Sign in to an existing account</button>
      <p className="text-muted-foreground">Continue links your guest workspace to a new Google account. For an existing account, use sign in.</p></>
      : session && <><p className="text-muted-foreground">Saved until you delete it.</p><button className="button-secondary w-full" disabled={busy} onClick={() => void action(importLocal)}>Import browser history</button><button className="button-secondary w-full" disabled={busy} onClick={() => void action(signOut)}>Sign out</button></>}
    {session && !session.user.is_anonymous && transfer && <button className="button-primary w-full" disabled={busy} onClick={() => void action(async () => {
      await cloudRequest('transfer', { method: 'POST', body: JSON.stringify({ token: transfer }) });
      sessionStorage.removeItem('research-guest-transfer'); window.location.reload();
    })}>Import guest workspace</button>}
    {error && <p role="alert" className="text-destructive break-words">{error}</p>}
  </div>;
}
