# AI Research Agent — Codex repository guide

## Scope and evidence
- This guide records the inspected checkout; commands are source-verified, not execution-tested during onboarding. Paths are repository-relative. [unknown] means not established by the repository.
- Onboarding authorization: read-only inspection followed by this file only; no installs, network/database access, migrations, or other file writes were authorized. Future tasks need their own scope.
- No pre-existing AGENTS.md, `.github/`, Copilot instructions, prompt instruction files, CI, Docker, Makefile, deployment manifests, database schema, or migrations were found in the checkout. Inventory anchors: `README.md`, `requirements.txt`, `frontend/package.json`, `server/`, `app/`, `tools/`, `tests/`. External Copilot guidance is [unknown].

## Overview and inventory
- Product: AI Research Agent, a question-to-cited-Markdown research tool with CLI and web UI (`README.md`, `main.py`, `frontend/src/App.tsx`).
- Backend: Python 3.11+ documented; FastAPI/Uvicorn, Pydantic 2, pydantic-settings, google-genai, HTTPX, BeautifulSoup, Rich, pytest (`README.md`, `requirements.txt`). Python dependencies have lower bounds but no lockfile (`requirements.txt`).
- Frontend: React 18, TypeScript, Vite 6, Tailwind 3/PostCSS, Lucide, react-markdown and remark-gfm (`frontend/package.json`). Dependency resolution is in `frontend/package-lock.json`; the root `package-lock.json` has no packages and no matching root package manifest.
- Root entry/docs/config: `main.py`, `server.py`, `README.md`, `requirements.txt`, `.env.example`, `.gitignore`; frontend entry/config: `frontend/index.html`, `frontend/vite.config.ts`, `frontend/tsconfig*.json`, `frontend/tailwind.config.js`, `frontend/postcss.config.js`, `frontend/.env.example`.
- Modules: `app/` research pipeline and `app/llm/` provider interface; `tools/` search/fetch adapters; `server/api/` jobs/contracts; `frontend/src/{pages,components,services,types}/` UI; `tests/` five test modules.
- Generated artifacts: CLI writes `reports/research_YYYY_MM_DD_HHMMSS.md`; frontend builds to Vite output; `.gitignore` excludes `reports/*.md`, `frontend/dist/`, `frontend/node_modules/`, `.venv/`, Python caches and `.env`. `frontend/tsconfig.app.tsbuildinfo` is tracked (`app/reporter.py`, `.gitignore`, `frontend/package.json`).

## Architecture and data flow
- CLI: `main.py` parses a question and optional caps, loads Settings, invokes ResearchAgent, saves/prints Markdown (`app/reporter.py`). `--check-config` checks required keys/model text locally, not model access (`main.py`, `app/config.py`).
- Browser: `frontend/index.html` -> `src/main.tsx` StrictMode -> `App.tsx` -> `pages/ResearchPage.tsx`; no router or global state library. React useState owns events, findings, sources, conflicts, report, status, and theme; localStorage holds the theme.
- HTTP client: `frontend/src/services/api.ts` POSTs `{question, depth, max_sources}` to `/api/research`, then opens EventSource at `/api/research/{id}/stream`. API base priority is VITE_API_URL, then VITE_BACKEND_URL, then same origin.
- API: `server/main.py` exposes health, job creation, SSE, and result GET at `/api/research/{id}`. `server/api/models.py` requires question length >=3, depth quick/standard/deep, and max_sources 1–20.
- Jobs: `server/api/research.py` creates UUID IDs, an asyncio task, a process-local job dictionary and one queue per job; synchronous ResearchAgent runs via asyncio.to_thread. No database, durable history, user model, authentication, authorization, cancellation, or expiry is implemented here (`server/main.py`, `server/api/research.py`).
- Orchestration: `app/agent.py` shares one GeminiClient among Planner, Researcher and Synthesizer; flow is plan -> collect -> batched extraction -> gaps -> conflicts -> draft -> Markdown.
- Planner requests a structured ResearchPlan and falls back to three deterministic queries (`app/planner.py`). Researcher executes one queued query per iteration, deduplicates URLs, and uses search snippets or fetched text when snippets are empty (`app/researcher.py`).
- Tavily adapter POSTs search requests, normalizes HTTP(S) URLs, strips fragments/utm_* parameters and deduplicates results; webpage adapter follows redirects and removes common non-content HTML elements (`tools/web_search.py`, `tools/webpage.py`).
- Extraction truncates each source to 5,000 characters and the batch to 50,000; it filters unknown source IDs. Gaps are assessed after collection; follow_up_queries are not consumed (`app/extractor.py`, `app/researcher.py`, `app/models.py`).
- Gemini uses structured Pydantic schemas, request budgeting, retry/backoff and one malformed-JSON correction; prompts are centralized and treat external content as untrusted evidence (`app/llm/base.py`, `app/llm/gemini.py`, `app/prompts.py`).
- Reports map [S1] tokens to numbered citations and append source links; fallback synthesis uses collected findings (`app/synthesizer.py`). Web UI renders GFM, copies/downloads Markdown, and uses window.print for its PDF action (`frontend/src/components/ResearchReport.tsx`).
- Event contract: `{type,message,timestamp,data?}`; planning/search/source/finding/gap/conflict/report events plus terminal `complete` or `research_failed`. `_end` terminates the queue stream. Final/result state omits source content, but source_found events include it (`server/api/research.py`, `app/agent.py`, `app/researcher.py`, `frontend/src/types/research.ts`).

## Environment (names only; never expose values)
- Backend names: GEMINI_API_KEY, GEMINI_MODEL, TAVILY_API_KEY, MAX_SEARCHES, MAX_SOURCES, MAX_ITERATIONS, MAX_LLM_REQUESTS, GEMINI_TIMEOUT, DEBUG (`.env.example`, `app/config.py`). Settings loads `.env`, ignores extra keys, and validates nonempty keys/model.
- CORS_ORIGINS is read directly from process environment during module import, not from Settings; listing it in `.env` alone does not populate os.environ (`.env.example`, `server/main.py`, `app/config.py`).
- Frontend names: VITE_BACKEND_URL, VITE_API_URL (`frontend/.env.example`, `frontend/src/vite-env.d.ts`, `frontend/vite.config.ts`, `frontend/src/services/api.ts`). VITE variables are browser-visible; never put provider keys there (`README.md`).
- CORS permits explicit origins with GET/POST and credentials, but is not authentication (`server/main.py`). Actual deployed origins and hosting configuration are [unknown].

## Verified workflow commands
Run backend commands from the repository root; run npm commands from `frontend/`. These are documented/script-defined commands, not evidence that the current machine has working dependencies (`README.md`, `frontend/README.md`, `frontend/package.json`).

| Task | Exact command | Source |
| --- | --- | --- |
| Create Python environment | `python -m venv .venv` | `README.md` |
| Activate in PowerShell | `.venv\Scripts\activate` | `README.md` |
| Install Python dependencies | `pip install -r requirements.txt` | `README.md`, `requirements.txt` |
| Create backend configuration | `Copy-Item .env.example .env` | `README.md` |
| Local configuration check | `python main.py --check-config` | `README.md`, `main.py` |
| Interactive CLI | `python main.py` | `README.md`, `main.py` |
| CLI with limits | `python main.py "AI coding agents in 2026" --max-searches 8 --max-sources 12 --max-iterations 4` | `README.md`, `main.py` |
| API development server | `uvicorn server.main:app --reload --port 8001` | `README.md` |
| Alternative API invocation | `python -m uvicorn server.main:app --reload --port 8001` | `frontend/README.md` |
| Enter frontend | `cd frontend` | `README.md` |
| Install frontend dependencies | `npm install` | `README.md`, `frontend/package.json` |
| Create frontend configuration | `Copy-Item .env.example .env` | `frontend/README.md` (inside frontend) |
| Frontend dev | `npm run dev` -> `vite` | `frontend/package.json` |
| Frontend build | `npm run build` -> `tsc -b && vite build` | `frontend/package.json` |
| Frontend preview | `npm run preview` -> `vite preview` | `frontend/package.json` |
| Python tests | `pytest -q` | `README.md`, `tests/` |

- Port inconsistency: root README uses 8001; frontend README also contains 8000; Vite's fallback proxy target uses 8000. Match VITE_BACKEND_URL to the backend and restart Vite after env edits (`README.md`, `frontend/README.md`, `frontend/vite.config.ts`).
- A set VITE_BACKEND_URL also makes browser requests direct, bypassing the dev proxy; README's proxy description is therefore conditional (`frontend/src/services/api.ts`, `frontend/vite.config.ts`, `README.md`).
- No frontend test/lint scripts or backend build/lint/deploy commands are defined. Deployment platform/settings, CI, and required production startup command are [unknown]; a Vercel origin in docs/CORS is not deployment configuration (`frontend/package.json`, `requirements.txt`, `README.md`, `server/main.py`).

## Conventions to preserve
- Python uses snake_case functions/files, PascalCase classes, type hints, Pydantic models, module loggers and small responsibility-specific modules; provider abstraction is LLMClient and prompts live separately (`app/models.py`, `app/llm/base.py`, `app/prompts.py`, `app/researcher.py`).
- React components/pages are PascalCase .tsx files, mostly named function exports with typed props; services and shared interfaces live separately. TS strict mode is enabled; HTTP payload fields stay snake_case (`frontend/src/components/`, `frontend/src/pages/ResearchPage.tsx`, `frontend/src/types/research.ts`, `frontend/tsconfig.app.json`).
- Styling uses Tailwind utilities, shared @apply classes, class-based dark mode, responsive rules and print styles; accessibility labels/focus states occur in the UI (`frontend/src/index.css`, `frontend/tailwind.config.js`, `frontend/src/components/ResearchInput.tsx`).
- Errors generally log and fall back: searches/fetches return empty results/text, planning/synthesis offer deterministic fallbacks, and API jobs emit research_failed; non-debug API errors are generic (`tools/`, `app/planner.py`, `app/synthesizer.py`, `server/api/research.py`).
- Tests use pytest functions, fake SDK clients and monkeypatch; no live integration tests are present (`tests/test_gemini.py`, `tests/test_researcher.py`, `tests/test_tools.py`).

## Do-not-touch and safety boundaries
- Do not expose/commit `.env` or provider credentials; keep secrets backend-only (`README.md`, `.gitignore`). Do not hand-edit generated caches, build output or dependency directories (`.gitignore`, `frontend/tsconfig.app.tsbuildinfo`).
- Preserve evidence-only/untrusted-content prompt rules and bounded research behavior (`app/prompts.py`, `app/researcher.py`, `app/llm/gemini.py`). Preserve API/event contracts across Python and TS together (`server/api/models.py`, `server/api/research.py`, `frontend/src/types/research.ts`, `frontend/src/services/api.ts`).
- No additional repository-specific protected areas were found; production/database access rules and external Copilot conventions are [unknown] (`README.md`; checkout instruction/config inventory).

## Health check — verified code findings, not runtime-tested
1. **Unrestricted jobs/resource growth:** no API auth/rate limit/concurrency cap; jobs and queues are retained indefinitely; restart loses results and separate workers have separate dictionaries (`server/main.py`, `server/api/research.py`).
2. **SSE lifecycle:** a single destructive queue cannot replay or broadcast to multiple subscribers; reconnect can wait forever after _end is consumed. EventSource is not closed on terminal events or component unmount; its onerror ignores CONNECTING failures. Settings construction outside try can leave a job without termination on configuration error (`server/api/research.py`, `frontend/src/services/api.ts`, `frontend/src/pages/ResearchPage.tsx`).
3. **Limits/accounting mismatch:** API presets override environment search/iteration/source caps, unlike README's stated global limits; depth does not set an LLM budget. One query per iteration further limits search depth. Gemini transport retries share one reserved request, and state.llm_requests_used is captured before conflict/synthesis calls (`server/api/research.py`, `app/researcher.py`, `app/llm/gemini.py`, `app/agent.py`, `README.md`).
4. **Fetch/security/performance:** HTTP(S) normalization does not block private hosts; fetch follows redirects without destination restrictions and downloads the full response before truncating. This permits SSRF/resource-exhaustion risk from returned source URLs. Synthesis includes full source models without an aggregate content cap (`tools/web_search.py`, `tools/webpage.py`, `app/synthesizer.py`).
5. **Incomplete research feedback:** follow_up_queries are modeled/requested but discarded, so detected gaps never trigger more research (`app/models.py`, `app/prompts.py`, `app/researcher.py`).
- **Evidence/report quality:** empty source_ids pass extraction's subset check; conflict source IDs are not checked; citation replacement only covers key findings/detailed analysis, and Evidence repeats Detailed Analysis (`app/extractor.py`, `app/synthesizer.py`).
- **Test gaps:** nine test functions cover models, Gemini basics, URL normalization, report citations, and one loop budget. The deduplication-named test overwrites its duplicate-result mock with an empty list and never asserts deduplication; no API/SSE/frontend or full-pipeline tests are present (`tests/test_*.py`, `frontend/package.json`).
- **Unused code candidates:** Citation has no importer; get_settings, validate_model_access, and agenerate_text have no repository callers; agenerate_text bypasses budgeting/retry logic. app/reporter.py imports unused ResearchState (`frontend/src/components/Citation.tsx`, `app/config.py`, `app/llm/gemini.py`, `app/reporter.py`). Public adapter methods may be intentional; removal intent is [unknown].
- **UI issues:** saved dark preference does not apply the initial document class; stream cleanup only occurs on reset; PDF button opens print, and print CSS targets main > form although input renders a section (`frontend/src/pages/ResearchPage.tsx`, `frontend/src/components/ResearchInput.tsx`, `frontend/src/components/ResearchReport.tsx`, `frontend/src/index.css`).
- **Duplication/drift:** Settings is instantiated repeatedly per job; backend/frontend contracts are manually duplicated; README lists UI/PDF as future work despite implemented UI/print action (`server/api/research.py`, `app/models.py`, `frontend/src/types/research.ts`, `README.md`, `frontend/src/components/ResearchReport.tsx`).
- No literal TODO/FIXME/HACK/XXX markers were found in inspected source. README future items include persistent memory, browser automation, scheduled runs, richer ranking and knowledge graphs; implementations were not found (`README.md`, `app/`, `tools/`, `server/`).

## Confirm with the developer when relevant
- [unknown] Actual hosting/release workflow, deployed backend URL, intended local port and process-level CORS configuration (`README.md`, `frontend/README.md`, `frontend/vite.config.ts`, `server/main.py`).
- [unknown] Intended public/private access policy, job retention/concurrency requirements, and whether global limits must override API depth/source choices (`server/main.py`, `server/api/research.py`, `README.md`).
- [unknown] Active provider model/quota and local runtime readiness; config validation cannot establish remote access (`app/config.py`, `app/llm/gemini.py`, `main.py`).
- [unknown] Copilot instructions or development conventions stored outside this checkout; no such files were found in the repository inventory.
