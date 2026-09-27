# Research Agent Frontend

## Run locally

From the project root:

```powershell
pip install -r requirements.txt
uvicorn server.main:app --reload --port 8000
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

The local `.env` targets FastAPI on port 8001. Start FastAPI on that same port and restart Vite after changing environment values. Set `VITE_API_URL` only when the frontend and backend are deployed separately; that makes the browser call the backend directly instead of using the Vite proxy.
