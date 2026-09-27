# AI Research Agent

A modular Python CLI that plans research with Gemini, searches Tavily, extracts evidence, checks gaps and conflicts, and writes a cited Markdown report.

## Features

- Pydantic models for plans, sources, findings, conflicts, and serializable state
- Bounded iterative search with source URL deduplication
- Separate Gemini, Tavily, and webpage adapters
- Evidence-only claim extraction with webpage content treated as untrusted data
- Markdown reports with numbered source links
- Rich terminal progress and mocked pytest coverage

## Requirements

Python 3.11+, a Gemini API key, and a Tavily API key.

## Installation

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```

Create `.env` from `.env.example`, then set `GEMINI_API_KEY`, `GEMINI_MODEL` to a model available to your Google AI Studio project and free tier, and `TAVILY_API_KEY`. Never commit `.env`.

## Configuration

Set `GEMINI_MODEL` to a Gemini model available to your Google AI Studio project and free tier. Google controls the actual quota; `MAX_LLM_REQUESTS` is only this application's safety limit. The application validates the key, model name, and Tavily configuration without logging secrets.

Evidence extraction is batched across collected sources rather than making one Gemini request per search result. A normal run therefore uses a small fixed number of model calls for planning, evidence analysis, gap assessment, conflict detection, and synthesis.

Use `python main.py --check-config` to validate local configuration without making a Gemini request.

## Usage

```powershell
python main.py
python main.py "What are the major developments in humanoid robots in 2026?"
python main.py "AI coding agents in 2026" --max-searches 8 --max-sources 12 --max-iterations 4
```

Research depth is available through the API as `quick`, `standard` (default), or `deep`. These modes bound searches, sources, iterations, and model requests; all remain subject to the global environment safety limits.

Reports are saved under `reports/` and printed to the terminal.

## Architecture

```text
Question -> Planner -> bounded Research Loop -> Tavily/Webpage
                         |-> Sources -> Findings -> Gaps
                         |-> Conflicts -> Synthesizer -> Report
```

The `LLMClient` and `search_web` function are adapters, so the orchestration does not depend on the Gemini SDK directly.

## Limitations

Search coverage and source quality vary; LLM reasoning can be wrong; citations should be checked for important work; this is not a substitute for professional research. Web pages can contain prompt injection, so their text is passed as evidence only and never as application instructions.

## Future improvements

Persistent research memory, PDF output, browser automation, scheduled runs, richer source ranking, knowledge graphs, and a UI can be added when the use case justifies them.

## Tests

```powershell
pytest -q
```

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

The Vite development server proxies `/api` to `VITE_BACKEND_URL`, configured locally as `http://127.0.0.1:8001`. Start FastAPI on port 8001 before using the frontend, and restart Vite after changing the port. If the frontend is deployed separately, set `VITE_API_URL` to the public FastAPI URL.
