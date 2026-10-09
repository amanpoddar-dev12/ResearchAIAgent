# Research Agent Frontend

## Run locally

From the project root:

```powershell
pip install -r requirements.txt
uvicorn server.main:app --reload --port 8001
```

In a second terminal:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

Open http://localhost:5173. The browser communicates with FastAPI only; API keys stay in the backend `.env`.

The UI uses `POST /api/research` and `GET /api/research/{id}/stream` (Server-Sent Events). The API invokes the same `ResearchAgent` used by the CLI.
## Local development

Start FastAPI from the project root in one terminal:

```powershell
python -m uvicorn server.main:app --reload --port 8001
```

Then start Vite in another:

```powershell
npm run dev
```

During `npm run dev`, fetch and SSE requests use same-origin `/api` URLs through Vite's proxy. The proxy targets `VITE_BACKEND_URL`, defaulting to local FastAPI on port 8001. Start FastAPI on that same port when using the local backend, and restart Vite after changing environment values.

`VITE_API_URL` is used only in production builds; it must point to the FastAPI backend, not the frontend website. Production builds retain `VITE_BACKEND_URL` as a fallback when `VITE_API_URL` is unset. A separately hosted backend must allow the deployed frontend origin through `CORS_ORIGINS`.

API routing regression tests (no additional dependencies): `node --test tests/api.test.mjs` from this directory.


### Vercel page routes

Deploy the frontend with Vercel Root Directory set to `frontend`, build command `npm run build`, and output directory `dist`. The `frontend/vercel.json` configuration serves the React entry document for `/app` and `/landing`, including trailing-slash URLs. This allows direct navigation and refresh without a hosting 404. API and asset URLs are not rewritten.

After deploying this configuration, verify `/`, `/app`, and `/landing` in the deployed site. Signed-in visits to `/` open the research workspace; signed-out visits show the landing page. `/app` retains guest access.
