# Supabase workspace setup

The existing local app remains usable when all Supabase variables are empty. This is an explicit local development mode: it does **not** enforce the guest limit. A production deployment must configure both frontend and backend. Partially configured backend credentials fail closed.

## 1. Create and configure the project

1. Create a Supabase project. Run `supabase/migrations/202610090001_workspace.sql` once in the SQL editor. Keep this migration in version control; use Supabase migrations for future changes.
2. In Authentication settings, enable **Anonymous Sign-Ins** and **Manual Identity Linking**. Do not enable anonymous-user automatic cleanup if you want to preserve guest work. Anonymous users consume Auth/storage resources.
3. Create a Google OAuth web client in Google Cloud. Enable Google in Supabase Authentication providers and enter the client ID/secret there. Use the exact Supabase callback URL shown in that panel as the Google authorized redirect URI. Never put the Google client secret in this app's frontend.
4. Configure Supabase Site URL to the deployed app origin. Allow the exact production app URL and local development URLs in the Auth redirect allowlist. Configure Google authorized JavaScript origins correspondingly. OAuth returns to the existing app page; no separate route is required.
5. Confirm the `research-pdfs` Storage bucket is private and the migration's RLS policies are applied.

## 2. Configure locally (do not commit credentials)

Backend `.env`:

```dotenv
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLIC_PUBLISHABLE_KEY
SUPABASE_SECRET_KEY=YOUR_BACKEND_SECRET_OR_SERVICE_ROLE_KEY
```

Frontend `frontend/.env`:

```dotenv
VITE_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLIC_PUBLISHABLE_KEY
```

All values must refer to the same project. Only URL/publishable key are browser-visible. The backend secret bypasses RLS; backend endpoints derive ownership exclusively from a validated Supabase user, never a submitted owner ID. Configure CORS_ORIGINS for your frontend origin, as an actual backend process environment variable. Restart FastAPI and Vite after configuration.

## 3. Behavior

- Guests receive an anonymous identity without a login screen. The database atomically reserves up to **five** research runs per identity. A provider/server failure refunds the reservation; intentional cancellation consumes it. Capacity rejection consumes no allowance.
- “Continue with Google” links a new Google identity to the current guest and preserves its user ID. If the Google account already exists, use “Sign in to an existing account.” A one-use, 15-minute transfer capability lets the signed-in account explicitly import the guest workspace. Finish active research before transferring. No email-based ownership matching is used.
- Signed-in users are exempt from the guest quota. Existing per-research budgets and global concurrency limits still apply. This is not a billing/subscription system or an account-level daily usage cap.
- Reports retain full source text, evidence, report sections, and metadata. Research snapshots checkpoint every five seconds and save on completion. Completed saved research reconstructs assistant context after backend restarts. Interrupted jobs retain available snapshots but **do not automatically resume** execution.
- Chat messages and citation references are saved after message changes. Draft typing stays local. Both assistant surfaces use the same persistence functions. PDF originals are private objects; extracted pages are saved separately and indexed in the browser on reopening.
- Existing browser history can be explicitly imported after Google sign-in. No automatic upload of old local history occurs. Pre-existing local PDFs contain extracted text only; their original files must be uploaded again to retain originals in Storage.
- Data is saved until deleted, with no application expiry. This requires an active Supabase project and ongoing storage/backup management; it is not a promise of free or guaranteed lifetime hosting. Removing a PDF attachment deletes its original only when no other conversation references it. Deleting research removes its record, not independent conversations/documents.
- Clearing cookies or using a different browser can create another anonymous identity. Deploy abuse protection/CAPTCHA and appropriate operational usage controls before exposing unlimited anonymous registration publicly.

## 4. Deployment verification

1. Create a guest; run five research sessions. The sixth must return 403 and show the Google sign-in instruction.
2. Simulate concurrent quota reservations near the limit; only available slots may succeed. Browser counters are informational only.
3. Link a new Google account and verify saved reports, chats and PDFs remain available.
4. Repeat with an existing account and the explicit guest import action.
5. Sign in on another browser/device: open saved research, ask a follow-up, inspect source and PDF page citations.
6. Restart the backend and repeat the saved report follow-up. An interrupted job must not be presented as successfully resumed.
7. With two accounts, try the other account's research ID at result, status, cancel, index and streaming endpoints: all must return 404. RLS must also deny direct record/object reads.
8. Remove a PDF, delete saved research, sign out, and verify the next guest cannot see the previous account's history.

Official references: [Anonymous authentication](https://supabase.com/docs/guides/auth/auth-anonymous), [Google OAuth](https://supabase.com/docs/guides/auth/social-login/auth-google), [RLS](https://supabase.com/docs/guides/database/postgres/row-level-security), [Storage access](https://supabase.com/docs/guides/storage/security/access-control).


### FindingsAI production domain

The production frontend is `https://findingsai.vercel.app`. In Supabase Authentication → URL Configuration, set Site URL to `https://findingsai.vercel.app/` and add that exact URL to Redirect URLs alongside the existing localhost development redirects. Google sign-in returns to the frontend root, where persisted signed-in sessions open the research workspace. An unapproved redirect can fall back to the Site URL, so a stale Site URL can send login to a retired deployment.

If the deployed backend explicitly sets `CORS_ORIGINS`, include `https://findingsai.vercel.app` in that setting; an explicit environment value overrides the code defaults.
