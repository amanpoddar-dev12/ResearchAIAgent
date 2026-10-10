# Security audit — FindingsAI

Audit date: 2026-10-11 (local date). Repository: current working tree, including existing uncommitted work.
This report describes verified code paths and read-only Supabase metadata inspection, not a penetration-test certification.
Findings were reported to the user before any file edits. No credentials are included.

## Authorization and scope

The user approved applying the PDF ownership RLS correction and narrowing public share snapshots.
The user explicitly deferred request limits, chat quotas, and dependency updates. Those were not implemented.
No keys were rotated, authentication project settings changed, files deleted, or commits/remotes pushed.
Only repository source/test/report/migration files were changed. Existing unrelated changes were preserved.
The approved RLS migration was applied to Supabase project rhxlddpqpltefrmwtnmv.

## Architecture and trust-boundary map

| Entry / source | Processing | Sink / control |
| --- | --- | --- |
| Browser OAuth / session | frontend/src/services/auth.ts:1; PKCE, current-origin redirect, Supabase session | Bearer header to FastAPI; server/workspace.py:37 verifies against Auth /user, not browser claims |
| POST /api/research | ResearchRequest, owner-scoped quota reservation and job creation | app/agent.py, planner, researcher, extractor, evidence, synthesizer; Gemini/Groq and Tavily outbound calls |
| Research status, result, SSE, cancel, checkpoint | server/main.py:42 ownership middleware; server/api/research.py; server/productivity.py:27 | Owned job/state, bounded replay events, browser React text / Markdown |
| Research chat, chat/stream, chat/index | AssistantRequest, authoritative live job or owned restored state; app/assistant_context.py | Session RAG, bounded selected context, Gemini stream; citation IDs resolved against supplied sources |
| Workspace list/get/put/delete/transfer | Verified Auth user; encoded owner/id REST filters; payload validation | Supabase privileged REST RPC/row mutations; storage uploads/deletes with owned record checks |
| Library collections/context/chat, shares, alerts | Auth middleware and owner-scoped record loading; member check for alerts | Owned records, whitelisted publication snapshots, internal alert worker |
| GET /api/public/reports/{token} | Strict 43-character capability, SHA-256 lookup, expiry and source-record existence | Public whitelisted JSON, no-store and noindex; SharedReportPage / ResearchReport |
| POST /api/assistant/pdf | 25 MiB streamed cap, signature, random server paths, two extraction slots | Fixed Python subprocess argv, pypdf, 90-second timeout, extracted-text bounds; private Storage object |
| GET /api/assistant/research-ideas | Cached search under lock, fixed provider endpoint | Research suggestions as React text |
| Tavily URLs / source text | tools/web_search.py normalization; tools/webpage.py public-IP checks and DNS pinning at every redirect | Bounded HTTP(S) fetch, BeautifulSoup text extraction; source/evidence models and prompts |
| User/retrieved/model content | Pydantic JSON schemas; evidence/source-ID and verbatim-quote validation | Reports/charts/text; no model-output eval, shell execution, dynamic SQL, or file-path execution found |
| Database rows / browser history | Owned REST reads or locally scoped IndexedDB; treated as untrusted research context | React text, react-markdown without raw HTML plugin; report SVG uses textContent and XMLSerializer |
| CLI question | main.py -> ResearchAgent | Fixed timestamp report filename under operator-configured directory; report directory is not an HTTP parameter |
| Environment | app/config.py backend Settings; Vite only public config | Provider keys in outbound headers; public Supabase key frontend; privileged key server only |

API inventory includes health, research start/result/status/stream/cancel/checkpoint/chat/chat-stream/chat-index,
workspace usage/transfer and CRUD, PDF upload, suggestions, collection context/chat, share create/revoke/public-read,
and alert list/create/update. Google login redirects to window.location.origin + "/" rather than arbitrary URL parameters.

## Findings

### F01 — High: former guest retains read access to transferred PDFs

High because ownership transfer did not revoke the old principal's Storage authorization.
References: supabase/migrations/202610090001_workspace.sql:43, :53, :70;
supabase/migrations/20261010200448_pdf_transfer_read_ownership.sql:4.
Path: guest uploads -> object name contains guest UUID -> claim_guest_workspace moves records to member but leaves object path ->
old guest token still satisfies own_pdf_read folder predicate -> Storage SELECT/download remains permitted.
Postgres permissive policies combine with OR; the new record-owner policy did not supersede the folder policy.
Fixed: approved migration drops only own_pdf_read. Existing transferred_pdf_read grants access through a currently owned PDF record,
including ordinary uploads. No object/data rows moved or deleted.
Test: live catalog check observed obsolete policy present=true before the migration; supabase/tests/pdf_transfer_security.sql
now passes and checks the remaining ownership policy. Advisors rechecked.
[uncertain] No real former-guest/new-member download was performed; catalog verification is not a complete end-to-end Storage test.
Previously downloaded copies or already issued signed URLs cannot be recalled by this policy change.

### F02 — Medium: unvalidated executable URL reaches Evidence Explorer link

Medium because this is a clickable unsafe sink; delivery into a victim's session is conditional.
Reference: frontend/src/components/EvidenceExplorer.tsx:19.
Path: imported/browser-saved research or an API snapshot -> Source.url (plain string) -> href without protocol validation.
React 18 renders javascript: URLs with a warning rather than sanitizing them.
Fixed: display Open original only for explicit HTTP(S) URLs, matching SourcePreview's existing guard.
Test: frontend/tests/security.test.mjs rejects javascript:, data:, and protocol-relative links; preserves HTTPS. Failed before, passes after.
[uncertain] A cross-account delivery path was not demonstrated. Normal Tavily sources are already normalized to HTTP(S);
this finding must not be described as proven remote account takeover.

### F03 — Medium: report Markdown automatically requests attacker-controlled images

Medium because model/source-controlled content can trigger an unsolicited external request.
References: frontend/src/components/ResearchReport.tsx:121, :128.
Path: source prompt injection or imported report -> Markdown image URL -> react-markdown img -> browser GET.
If confidential context is encoded in that URL, the request can disclose it. Ordinary tracking also reveals viewer network metadata.
Fixed: disallow Markdown img elements in both report text and interpretation notes. Existing Recharts visuals/export remain intact.
Test: frontend/tests/security.test.mjs renders hostile image Markdown in both locations and asserts no img.
Failed before the fix; passes afterward.
[uncertain] No model was induced to encode private data and no attacker endpoint was contacted. The rendering/request sink is verified,
not successful semantic prompt-injection exfiltration.

### F04 — Medium: research content and model values leak into logs

Medium because private questions, token-bearing URLs, and invalid model values can be retained in operational logs.
References: tools/web_search.py:22, :34; tools/webpage.py:103; app/llm/router.py:91;
app/extractor.py:25; app/planner.py:56; app/synthesizer.py:63; server/main.py:293;
server/api/research.py:234, :478.
Path: query/URL/model JSON -> interpolated log or Pydantic error/exception chain -> application logs.
Fixed: omit queries/URLs and arbitrary exception strings; log exception class instead.
Final model-validation failure is generic and suppresses the sensitive exception chain.
Research/chat error handlers retain session ID and exception class but do not log exception payloads/tracebacks.
Generation, fallback behavior, and public error envelopes are unchanged.
Tests: tests/test_security_audit.py reproduces query, URL, validation-value and stream-exception leakage before fixes;
all four now pass.
[uncertain] Hosting access logs, HTTPX debug/INFO logging configured outside the app, previously retained logs, and observability
integrations were not inspected. Share capability tokens in URL paths should be redacted in hosting/access logs.

### F05 — Medium: nested public share payload is not completely whitelisted

Medium because unexpected private nested fields can be included in a publication presented as report-only.
References: server/productivity.py:142, :188.
Path: imported research payload.structuredReport (unrestricted dictionary) -> share_snapshot -> persisted/public JSON.
A top-level whitelist previously passed the entire nested dictionary and arbitrary chart/table row keys.
Fixed with approval: validate StructuredReport; omit unexpected model fields; publish visual cells only for displayed columns/series
and scalar values. Invalid imported visuals become null while Markdown remains available.
Apply the same sanitizer on public reads so previously stored snapshots cannot retain unexpected nested fields in responses.
Test: tests/test_security_audit.py::test_share_snapshot_discards_nested_private_fields failed before and passes after.
Existing share/revoke/expiry/ownership tests pass.
[uncertain] Visible report prose, displayed chart cells, provenance quotes, and source URLs can themselves contain private information;
the explicit publication confirmation remains necessary. This is not automatic sensitive-content detection.

### F06 — High: JSON buffering occurs before effective request-size validation — deferred

High because anonymous authenticated users can submit oversized bodies and exhaust worker memory before model/context bounds run.
References: server/api/models.py:11; app/chat.py:31; app/assistant_context.py:18, :28; server/main.py:100.
Path: research/chat JSON or member transfer body -> framework/request.body buffering -> JSON parsing ->
later model/context length checks. Research question has no max length; history dictionary string values are not individually bounded.
Existing streaming caps on workspace PUT (48 MiB) and PDF upload (25 MiB) do not cover typed JSON endpoints.
Not fixed: user chose recommendations for now; changing accepted API traffic requires approval.
Recommended: enforce body limits before JSON parsing, per-field/history bounds, upstream timeout/body limits and bounded collection loading.
No new regression test because the public API change was deferred.
[uncertain] Reverse-proxy ingress limits may mitigate this; deployed settings were not examined.

### F07 — High: general assistant has no aggregate concurrency/usage cap — deferred

High because many simultaneous requests can spend provider quota and occupy workers.
References: server/api/research.py:320, :358, :457; server/productivity.py:124.
Path: valid guest bearer -> arbitrary new general-chat UUID -> a new request-local ResearchJob/chat_lock ->
independent Gemini generation. Per-job locks and max_requests=1 do not impose per-user/process aggregate limits.
Research jobs have MAX_ACTIVE_JOBS=3; this does not govern standalone chats.
Not fixed: user deferred limits. Add process-wide/per-owner concurrency and deliberate rate/usage policy before public scale.
No new test for deferred behavior.
[uncertain] Upstream provider/proxy enforcement and abuse controls are not established.

### F08 — Medium: PDF subprocess lacks a hard aggregate memory ceiling — deferred

Medium because upload/time/text limits do not guarantee bounded parser memory on adversarial PDFs.
References: app/pdf_documents.py:27, :58; server/main.py:317.
Path: uploaded PDF -> disposable pypdf process -> object/decompression/text allocations before final text-size checks.
Existing controls: 25 MiB input, 2,000 pages, decompression/output limits, 8M extracted chars, two slots, 90-second timeout.
No confirmed parser exploit or successful OOM was run. This is a verified missing resource boundary, not an RCE claim.
Not fixed: a cross-platform process/container memory policy needs a deployment budget decision; dependency updates were deferred.
Existing PDF processing tests pass. No malicious resource-exhaustion PDF was executed.
Recommended: container/OS process memory limit plus bounded extraction output and queue admission.

### F09 — Medium: frontend dependency advisories — deferred

Medium repository impact: the reported affected paths are developer/build tooling; upstream advisories include High severity.
Reference: frontend/package-lock.json:1681 (braces), :3812 (postcss-selector-parser), :4215 (source-map-js);
frontend/package.json: devDependencies.
npm audit reports 8 affected dependency entries (6 High, 2 Moderate), not 8 independent vulnerabilities:
- braces / chokidar / micromatch / fast-glob / tailwindcss:
  https://github.com/advisories/GHSA-vfj7-8cjw-p6xm
- postcss-selector-parser / postcss-nested / tailwindcss:
  https://github.com/advisories/GHSA-rj75-hqrm-r3gf
- source-map-js:
  https://github.com/advisories/GHSA-68fv-2mgg-jv7q
Path: malicious nested glob, selector, or source-map inputs -> build/watch parser -> CPU/stack exhaustion.
[uncertain] App end users do not submit build configuration; production exploitability was not demonstrated.
Not fixed: user deferred dependency updates. npm suggests a Tailwind major upgrade for parts of the chain;
do not run npm audit fix --force without a separate compatibility review.
Test/result: npm audit --json exit 1, 8 alerts. npm audit --omit=dev --json exit 0, zero production dependency alerts.
Build succeeds; this does not resolve development/build advisories.

### F10 — Low: installed Python packages have advisories; constraints are not locked — deferred

Low demonstrated app exposure because affected APIs are not used, while dependency hygiene still needs attention.
References: requirements.txt:3, :8, :9; app/config.py:35; app/pdf_documents.py:58.
Read-only PyPI release metadata scan examined the installed dependency closure rooted at requirements (38 visits, including
optional dependencies selected by installed extras). No package was installed or upgraded.
- python-dotenv 1.0.1: GHSA-mf9w-mj56-hr94 / CVE-2026-28684, fixed 1.2.2.
  https://github.com/advisories/GHSA-mf9w-mj56-hr94
  Path requires attacker-controlled symlink + set_key/unset_key write; app only reads env and does not call those functions.
- python-multipart 0.0.9, installed in this machine, has several parser advisories:
  GHSA-59g5-xgcq-4qw3, GHSA-wp53-j4wj-2cfg, GHSA-mj87-hwqh-73pj, GHSA-pp6c-gr5w-3c5g,
  GHSA-v9pg-7xvm-68hf, GHSA-5rvq-cxj2-64vf, GHSA-6jv3-5f52-599m.
  Advisory fixes extend through 0.0.31. It is not explicitly required by this repository;
  PDF endpoint consumes raw request streams, not multipart/form parsing.
[uncertain] These are local installed-version results, not Render's installed versions. Python uses lower bounds without a lockfile,
so neither local nor newly resolved versions certify all deployments.
Not fixed: dependency updates explicitly deferred. No app exploit test applicable to unused APIs.
Recommended: compatible patched bounds and a reviewed reproducible lock, then audit the exact deployed environment.

### F11 — Medium (conditional): missing Supabase config enables public local mode — decision

Reference: server/main.py:47; server/workspace.py:12.
Path: production environment omits all three Supabase variables -> configured=false -> ownership middleware skipped ->
public research/chat/PDF local-mode routes. Partial Supabase configuration does not take this bypass.
This preserves the intentional no-cloud development mode; changing it unilaterally would break supported behavior.
Not fixed; recommend explicit deployment-mode enforcement that fails closed in production.
[uncertain] Current production environment was not inspected. This is a configuration hazard, not proof of a current auth bypass.
Existing authenticated missing-session and cross-owner route tests pass.

### F12 — Low: browser-readable session tokens and capability tokens — architecture decision

References: frontend/src/services/auth.ts:7; frontend/src/components/AccountPanel.tsx:47;
frontend/src/storage/chatStorage.ts:22.
Path: same-origin injected script, if present -> Supabase persisted session in localStorage / transfer token in sessionStorage ->
Bearer/capability reuse. Local research and drafts are also readable by same-origin scripts.
No raw HTML or proven script-injection exploit was found. Browser storage is expected for this client-only PKCE architecture,
not itself proof of a token leak.
Not changed: HttpOnly server-session/BFF migration would require architectural and API decisions.
Recommended: strict reviewed CSP, minimize third-party scripts, redact capabilities from logs, assess retention/shared-device policy.
[uncertain] Deployed CSP and browser-extension/shared-device access were not assessed.

### F13 — Low (conditional): CORS permits an unsafe wildcard configuration — decision

References: server/main.py:215, :223.
Default origins are explicit; credentials=True. An operator can set CORS_ORIGINS=* without rejection.
No cookie-authenticated app API or verified deployed wildcard exposure was found; Bearer tokens are explicitly attached.
Not changed: recommend validating explicit production origins and rejecting wildcard with credentials.
[uncertain] Render's CORS_ORIGINS value was not read. CORS does not replace authentication.

### F14 — Low: leaked-password protection disabled — project decision

Supabase security advisor reports auth_leaked_password_protection.
Path would require an enabled password signup/login provider -> compromised password accepted -> account risk.
Frontend uses Google and anonymous sign-in only. [uncertain] Other Auth providers/project signup policy were not inspected.
No setting changed. Consider enabling if passwords are supported.
Remediation: https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection

## Required-area checks with no confirmed issue

- Live public tables: workspace_records, research_allowances, guest_transfers, report_shares, research_alerts all have RLS.
  No public views found. No using(true) public/storage policy found.
- workspace_records/research_allowances SELECT compares owner_id to auth.uid(). Client mutations lack permissive policies;
  writes are mediated by verified server Auth and owner-scoped service requests.
- research-pdfs bucket is public=false; no INSERT/UPDATE/DELETE client Storage policies found.
- reserve_research and claim_guest_workspace are SECURITY DEFINER with empty search_path and revoked anon/authenticated execute.
  Alert RPCs are invoker functions, also not client-executable. Live privilege metadata checked.
- RLS-without-policy advisor notices on guest_transfers/report_shares/research_alerts represent intentional deny-by-default client access.
  Anonymous-access advisor warnings reflect owned guest workspaces; they do not establish unrestricted public reads.
- No runtime raw SQL construction, pickle, unsafe yaml.load, shell=True, or eval/exec of LLM output found.
  SQL migrations use parameters/static statements; PostgREST filters encode variable identifiers.
- Upload filename is metadata only. Server chooses random temporary and Storage paths; subprocess argv is fixed and shell-free.
- Web fetching rejects nonpublic DNS answers and URL credentials, pins the checked IP, rechecks redirects,
  disables proxy environment trust, limits redirects/time/content bytes and allowed MIME types. Existing SSRF tests pass.
- React renders text via escaped JSX. Markdown uses react-markdown without rehype-raw;
  its URL transform remains enabled. SVG export labels use textContent, not raw XML interpolation.
- Chart CSV already escapes formula-prefix strings; CSV/SVG/PNG existing tests pass.
- Citation/claim/evidence IDs and source quotes are validated rather than model output being executed.
  Prompt-injection resistance remains probabilistic: app/assistant_prompts.py explicitly treats PDF/research/history as data;
  extraction/planning prompts warn about external instructions. No agent tool execution capability is granted to model text.
- All configured backend secret values were compared in memory against the current frontend/dist build:
  Gemini, Groq, Tavily and Supabase secret key were not found. Public frontend env key checked for secret/service-role form:
  none found; no values printed. [uncertain] This does not certify historical bundles/Git history or deployed artifacts.
- OAuth redirect is current origin "/", not a user-provided return URL; public share token has strict format and expiry/hash handling.

## Verification

- Initial regression run: 3 Python logging/value tests failed and 2 frontend rendering tests failed.
- Additional share whitelist and exception-log tests each failed before their respective fixes.
- Final backend: python -m pytest -q -o faulthandler_timeout=20 — 196 passed.
- Frontend: node --test tests/*.test.mjs — 44 passed. Updated image-notes regression also passed on focused rerun.
- npm run build — TypeScript and Vite production build passed; existing >500 kB chunk warning remains.
- Linter: no repository frontend/backend lint command/config established; no lint suite claimed or installed.
- npm audit --json — 8 unresolved alerts; updates deferred by user.
- npm audit --omit=dev --json — zero reported production dependency vulnerabilities.
- Python advisory check: PyPI installed-release metadata, not pip-audit installation/upgrade or a production lock audit.
- Supabase: approved migration successful; post-migration SQL regression successful; security advisors reread.
  No live account/data writes or adversarial uploads were used for testing.
- No manual browser visual/security test, external penetration test, prompt-injection red-team run, OOM test,
  historical secret scan, or deployed-service verification performed.

## Files changed for this audit

- tools/web_search.py, tools/webpage.py: remove sensitive search/URL/exception log values.
- app/llm/router.py: generic final validation error without sensitive chain.
- app/extractor.py, app/planner.py, app/synthesizer.py: log exception type rather than private details.
- server/main.py, server/api/research.py: sanitize failure logging, preserve API errors/events.
- server/productivity.py: validated nested public share whitelist, including reads of existing snapshots.
- frontend/src/components/EvidenceExplorer.tsx: HTTP(S)-only external links.
- frontend/src/components/ResearchReport.tsx: block automatic Markdown image loads.
- tests/test_security_audit.py, frontend/tests/security.test.mjs: reproduced security regressions.
- supabase/migrations/20261010200448_pdf_transfer_read_ownership.sql: approved minimal policy removal, applied.
- supabase/tests/pdf_transfer_security.sql: read-only live catalog regression.
- SECURITY_REPORT.md: this report.

## Human decisions still needed

1. Request/body/field limits and chat concurrency/usage budgets (explicitly deferred).
2. Compatible dependency updates, Python lock strategy and audit of actual deployment versions (explicitly deferred).
3. PDF process/container memory ceilings and admission limits appropriate to the hosting plan.
4. Production fail-closed config validation, precise CORS origins and guest-abuse controls.
5. CSP/token-storage/retention policy; log redaction and password protection if relevant.

References: current Supabase RLS documentation https://supabase.com/docs/guides/database/postgres/row-level-security
and advisor remediation pages https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy
and https://supabase.com/docs/guides/database/database-advisors?queryGroups=lint&lint=0012_auth_allow_anonymous_sign_ins.
Supabase changelog markdown fetch through the web reader failed with unsupported content type; a read-only HTTP fetch subsequently
succeeded and the breaking-change index was inspected. No Supabase SDK/config changes were made.

