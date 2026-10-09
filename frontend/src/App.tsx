import { lazy, Suspense, useEffect, useState } from "react";
import { supabase } from "./services/auth";
import { entryPage } from "./ui/entryRoute";
const ResearchPage = lazy(() => import("./pages/ResearchPage").then(module => ({ default: module.ResearchPage })));
const LandingPage = lazy(() => import("./pages/LandingPage"));
export default function App() {
  const [ready, setReady] = useState(!supabase);
  const [signedIn, setSignedIn] = useState(false);
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    if (!supabase) return;
    let active = true, revision = 0;
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      revision += 1;
      if (active) { setSignedIn(Boolean(session && !session.user.is_anonymous)); setReady(true); }
    });
    // Read the persisted session without creating an anonymous account on the landing page.
    const initialRevision = revision;
    void supabase.auth.getSession().then(({ data, error }) => {
      if (active && revision === initialRevision) { setSignedIn(Boolean(!error && data.session && !data.session.user.is_anonymous)); setReady(true); }
    }).catch(() => { if (active && revision === initialRevision) { setSignedIn(false); setReady(true); } });
    return () => { active = false; subscription.unsubscribe(); };
  }, []);
  useEffect(() => {
    if (ready && signedIn && path.replace(/\/$/, "") === "/landing") {
      window.history.replaceState(null, "", "/" + window.location.search);
      setPath("/");
    }
  }, [ready, signedIn, path]);
  const loading = <p className="p-6 text-muted-foreground" role="status">Opening workspace…</p>;
  if (!ready) return loading;
  return <Suspense fallback={loading}>{entryPage(path, signedIn) === "landing" ? <LandingPage /> : <ResearchPage />}</Suspense>;
}
