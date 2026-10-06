# AI Research Agent

A modular Python CLI that routes research tasks across Gemini and Groq, searches Tavily, extracts evidence, checks gaps and conflicts, and writes a cited Markdown report.

## Features

- Pydantic models for plans, sources, findings, conflicts, and serializable state
- Bounded iterative search with source URL deduplication
- Provider-agnostic Gemini and Groq HTTP adapters with task routing
- Evidence-only claim extraction with webpage content treated as untrusted data
- Markdown reports with numbered source links
- Rich terminal progress and mocked pytest coverage

## Requirements

Python 3.11+, Gemini/Groq API keys and model names, and a Tavily API key.

## Installation

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```

Create `.env` from `.env.example`, then set all provider keys and model names. Use a Gemini model available to your Google AI Studio project and Groq model names available to your account. `GROQ_REVIEW_MODEL` defaults to `qwen/qwen3.8-27b` and reuses `GROQ_API_KEY`. Set `LLM_TIMEOUT_SECONDS` and `LLM_MAX_RETRIES` for request resilience. Never commit `.env`.

## Configuration

The routing table is centralized in `app/llm/routing.py`: planning and synthesis use Gemini; source extraction uses Groq; gap analysis uses Gemini; selected claim review uses Groq outside Quick mode; report and chat block review use Groq in every mode. Each task goes to exactly one provider. `MAX_LLM_REQUESTS` is this application's safety limit. The application validates all provider keys/model names, Tavily, timeout, and retry settings without logging secrets.

Evidence extraction is batched across collected sources rather than making one request per search result. A normal run uses a small fixed number of routed model calls for planning, evidence analysis, gap assessment, conflict detection, synthesis, and independent review.

Use `python main.py --check-config` to validate local configuration without making a Gemini request.

## Usage

```powershell
python main.py
python main.py "What are the major developments in humanoid robots in 2026?"
python main.py "AI coding agents in 2026" --max-searches 8 --max-sources 12 --max-iterations 4
```

Research modes are available through the API as `quick`, `standard` (legacy default), `deep`, `technical`, `academic`, `fact_check`, and `compare`. Session budget overrides remain capped by the configured environment limits (`app/agent.py`, `app/researcher.py`).

Reports are saved under `reports/` and printed to the terminal.

## Architecture

```text
Question -> Planner -> bounded Research Loop -> Tavily/Webpage
                         |-> Sources -> Findings -> Gaps
                         |-> Conflicts -> Synthesizer -> Report
```

The routed `LLMClient` and `search_web` function are adapters, so orchestration does not depend on any provider SDK. Tavily remains the only web search provider.

The production pipeline refines and plans with Gemini, batches document extraction with Groq, evaluates individual claim/evidence relationships with Gemini, and independently challenges selected claims with Groq Qwen outside Quick mode. Review disagreement leaves the relationship unverified. Gemini drafts analytical report blocks; Groq Qwen reviews those blocks before publication. Numeric observations require verbatim quoted provenance; charts never fill missing measurements (`app/agent.py`, `app/extractor.py`, `app/evidence.py`, `app/synthesizer.py`).

Search waves rank candidates before spending the source cap. Document retrieval prioritizes the strongest candidates, reuses session documents, and can follow links from reference sections to close measured gaps. Collection stops on coverage, useful-evidence plateau, time/search/source/iteration limits, or the collection LLM budget; final review and synthesis receive reserved requests. Every HTTP retry and JSON repair consumes the same physical-request budget. Provider-reported token usage is recorded when available (`app/researcher.py`, `tools/webpage.py`, `app/llm/router.py`).

Source-quality scores are transparent heuristics, not verified authority or probabilities of truth. Distinct domains are a proxy for corroboration, not proof of publisher independence. Unsupported or incomplete research remains labelled partial; the model cannot assign the final evidence status directly (`app/source_quality.py`, `app/scoring.py`, `app/research_control.py`).

## Limitations

Search coverage and source quality vary; LLM reasoning can be wrong; citations should be checked for important work; this is not a substitute for professional research. Web pages can contain prompt injection, so their text is passed as evidence only and never as application instructions.

Backend jobs, documents, evidence, replay buffers, and chat budgets are process-local and temporary. The service admits up to three active jobs and retains at most twenty sessions, with completed sessions expiring after thirty minutes. A restart loses sessions; independent workers do not share them. Webpage extraction supports bounded HTML/plain text; the separate assistant upload supports searchable PDFs (`server/api/research.py`, `tools/webpage.py`).

## Assistant PDFs and local conversations

The main-page chatbot and sidebar assistant share the same chat. Use the paperclip to upload a searchable PDF (up to 25 MB, 2,000 pages, or 8 million extracted characters). Extraction runs in a disposable process with a 90-second limit. Scanned/image-only and encrypted PDFs require a searchable, unencrypted copy. The browser indexes the extracted text in a worker and sends at most eight relevant chunks per question to the existing Gemini integration. Page citations open extracted evidence; summaries describe retrieved excerpts rather than claiming full-document coverage.

Chat history, drafts, research snapshots, and extracted PDF text are stored locally in browser IndexedDB. Previous conversations can be reopened without API calls. New chat starts with no document attached; removing a PDF restores normal research/general chat. Clearing browser site data removes these local conversations and attachments. Uploaded source files are temporary on the server; extracted excerpts are sent to Gemini when answering.

Main-page ideas rotate every five minutes and on page opening. Recent Tavily search titles are cached for six hours; when search is unavailable, dated research prompts are composed locally. No LLM call is used for suggestions or loading local chat history.

## Tests

```powershell
pytest -q
```

Frontend regression tests and type-checking (from `frontend/`):

```powershell
node --test tests/*.test.mjs
./node_modules/.bin/tsc.cmd --noEmit -p tsconfig.app.json
npm run build
```

The offline tests use explicitly synthetic sources and no paid provider calls. No lint script is configured in `frontend/package.json`.

## Web frontend

The React/Vite frontend uses the same `ResearchAgent` through FastAPI and Server-Sent Events:

```powershell
# Terminal 1, from the project root
uvicorn server.main:app --reload --port 8001

# Terminal 2
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open http://localhost:5173. The browser never receives Gemini or Tavily credentials. `POST /api/research` starts a job and `GET /api/research/{research_id}/stream` streams real planning, search, source, finding, gap, and completion events.

SSE subscriptions independently replay retained events using `Last-Event-ID` or `?after=<sequence>`. An older cursor recovers the latest snapshot or terminal outcome. `GET /api/research/{research_id}/status` distinguishes running, complete, and failed sessions; `POST /api/research/{research_id}/cancel` cancels the session. The frontend reconnects to the existing job without starting another research run. Original event names and payloads remain compatible; sequence/progress metadata and new state fields are additive (`server/main.py`, `server/api/research.py`, `frontend/src/services/api.ts`).

During local development, browser requests use same-origin `/api` URLs and Vite proxies them to `VITE_BACKEND_URL` (default `http://127.0.0.1:8001`). Start FastAPI on port 8001 when using the local backend, and restart Vite after changing the port. `VITE_API_URL` applies to production builds only: set it to the public FastAPI backend URL, not the frontend website URL, when deploying separately.
Set the backend's `CORS_ORIGINS` environment variable to the exact deployed frontend
origin (for example, `https://research-ai-agent-4rpb-ruby.vercel.app`), using commas
to separate multiple origins.

### Groq review model and free-plan limits

Verified 2026-10-06 against [Groq free-plan limits](https://console.groq.com/docs/rate-limits) and [supported models](https://console.groq.com/docs/models): `qwen/qwen3.8-27b` has free-plan limits of 30 RPM, 1,000 RPD, 8,000 TPM, and 200,000 TPD. It is a preview model and may change. Llama 3.1/3.3 are currently Enterprise models. Free usage requires a Free-plan organization; the same model is billed on paid plans. The application does not determine account billing status. Large evidence batches can exceed free-plan token limits; existing bounded retry and evidence-only fallbacks remain active. Set `GROQ_REVIEW_MODEL` to change the reviewer without changing extraction via `GROQ_MODEL`. Mistral configuration is no longer required.
