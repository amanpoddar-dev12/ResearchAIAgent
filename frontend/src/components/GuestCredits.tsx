import { useState } from 'react';
import { cloudEnabled } from '../services/auth';
import { signInToWorkspace } from '../services/cloud';
import { useGuestUsage } from '../services/guestUsage';
import { GoogleIcon } from './GoogleIcon';

export function GuestCredits() {
  const { usage, error } = useGuestUsage();
  const [busy, setBusy] = useState(false);
  const [loginError, setLoginError] = useState('');
  if (!cloudEnabled || (usage && !usage.guest)) return null;
  const exhausted = usage?.remaining === 0;
  const login = async () => {
    setBusy(true); setLoginError('');
    try { await signInToWorkspace(); }
    catch (failure) { setLoginError(failure instanceof Error ? failure.message : 'Could not sign in.'); setBusy(false); }
  };
  return <section className="card mb-6 flex flex-wrap items-center justify-between gap-3 no-print" aria-label="Guest research credits">
    <div role="status" aria-live="polite">
      <p className="text-sm font-medium">{exhausted ? 'Your 5 free research credits are used up' : usage ? `${usage.remaining} of ${usage.limit} free research credits remaining` : 'Checking your free research credits...'}</p>
      <p className="mt-1 text-xs text-muted-foreground">{exhausted ? 'Sign in with Google to continue researching. You can import your guest workspace after signing in.' : 'Your allowance is saved with this guest workspace and does not reset on refresh.'}</p>
      {error && <p role="alert" className="mt-1 text-xs text-destructive">Unable to verify credits: {error}</p>}
      {loginError && <p role="alert" className="mt-1 text-xs text-destructive">{loginError}</p>}
    </div>
    <button type="button" className="button-primary" disabled={busy} onClick={() => void login()}><GoogleIcon />{busy ? 'Opening Google...' : 'Sign in with Google'}</button>
  </section>;
}
