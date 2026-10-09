import { GoogleIcon } from "../components/GoogleIcon";
import { useState } from "react";
import { googleLogin, supabase } from "../services/auth";
import { cloudRequest } from "../services/cloud";
export function LandingLogin() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function login() {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const { data } = await supabase!.auth.getSession();
      // Reuse the existing account sign-in transfer flow for a previous guest workspace.
      if (data.session?.user.is_anonymous) {
        const transfer = await cloudRequest<{ token: string }>("transfer", { method: "POST" });
        sessionStorage.setItem("research-guest-transfer", transfer.token);
      }
      await googleLogin(true);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Could not sign in. Please try again."); setBusy(false); }
  }
  if (!supabase) return null;
  return <div className="landing-login"><button type="button" className="landing-secondary google-login-button" aria-label={busy ? "Opening Google sign-in" : "Sign in with Google"} title="Sign in with Google" disabled={busy} onClick={() => void login()}><GoogleIcon /><span className="google-login-text">{busy ? "Opening Google…" : "Sign in with Google"}</span></button>{error && <p role="alert" className="landing-login-error">{error}</p>}</div>;
}
