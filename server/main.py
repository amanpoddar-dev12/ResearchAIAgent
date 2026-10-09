import os
import logging
import asyncio
import tempfile
import time
from pathlib import Path
from uuid import uuid4
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .api.models import ResearchRequest, ResearchStarted
from app.chat import ChatRequest, ChatResponse
from app.assistant_context import AssistantRequest
from .api.research import chat_research, get_public_state, jobs, start_research, stream_research, get_job_status, cancel_research, cleanup_jobs, get_chat_documents, stream_chat, assistant_job


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = __import__("app.config", fromlist=["Settings"]).Settings()
    try:
        settings.validate_configuration()
    except ValueError as exc:
        logging.getLogger(__name__).warning("Configuration incomplete: %s", exc)
    yield


app = FastAPI(title="AI Research Agent API", lifespan=lifespan)
from . import workspace


@app.middleware('http')
async def private_workspace(request: Request, call_next):
    from fastapi.responses import JSONResponse
    if request.method == 'OPTIONS' or not workspace.configured() or not (
        request.url.path.startswith('/api/research') or request.url.path.startswith('/api/workspace')
        or request.url.path == '/api/assistant/pdf'):
        return await call_next(request)
    try:
        user = await workspace.authenticate(request)
        request.state.user = user
        parts = request.url.path.split('/')
        if len(parts) > 3 and parts[2] == 'research':
            identifier = parts[3]
            job = jobs.get(identifier)
            if job and job.owner_id != user['id']:
                raise HTTPException(404, 'Research session not found.')
            if not job and not identifier.startswith('general-chat-'):
                saved = await workspace.load(user['id'], 'research', identifier)
                if not saved:
                    raise HTTPException(404, 'Research session not found.')
                if saved.get('state'):
                    from app.models import ResearchState
                    from .api.research import ResearchJob
                    cleanup_jobs()
                    restored = ResearchState.model_validate(saved['state'])
                    job = ResearchJob(owner_id=user['id'], state=restored, done=True, finished_at=time.monotonic(),
                        error=None if saved.get('status') in (None, 'complete') else saved.get('error') or 'This research was interrupted. Start a new run to continue.')
                    job.rag_index.update('research_snapshot', restored)
                    jobs[identifier] = job
        return await call_next(request)
    except HTTPException as exc:
        return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)


@app.get('/api/workspace/usage')
async def workspace_usage(request: Request):
    if not workspace.configured():
        raise HTTPException(503, 'Supabase is not configured.')
    return await workspace.usage(request.state.user)


@app.post('/api/workspace/transfer')
async def workspace_transfer(request: Request):
    if not workspace.configured():
        raise HTTPException(503, 'Supabase is not configured.')
    user = request.state.user
    import secrets
    import hashlib
    from datetime import datetime, timedelta, timezone
    if user.get('is_anonymous'):
        if any(job.owner_id == user['id'] and not job.done for job in jobs.values()):
            raise HTTPException(409, 'Wait for your research to finish before signing in to an existing account.')
        token = secrets.token_urlsafe(32)
        await workspace.remote('POST', '/rest/v1/guest_transfers', json={'token_hash': hashlib.sha256(token.encode()).hexdigest(),
            'owner_id': user['id'], 'expires_at': (datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()})
        return {'token': token}
    body = await request.body()
    if len(body) > 1024:
        raise HTTPException(400, 'Invalid transfer request.')
    import json
    try:
        token = json.loads(body)['token']
        if not isinstance(token, str) or len(token) > 100:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, 'Invalid transfer request.') from None
    claimed = await workspace.remote('POST', '/rest/v1/rpc/claim_guest_workspace', json={
        'p_token': hashlib.sha256(token.encode()).hexdigest(), 'p_target': user['id']})
    if not claimed:
        raise HTTPException(410, 'Guest transfer expired or was already used. Return to the guest session to retry.')
    # Guest jobs must not retain access to records transferred to another identity.
    for identifier, job in list(jobs.items()):
        if job.done and job.owner_id != user['id']:
            saved = await workspace.load(user['id'], 'research', identifier)
            if saved:
                jobs.pop(identifier, None)
    return {'imported': True}


@app.get('/api/workspace/{kind}')
async def workspace_list(kind: str, request: Request):
    workspace.validate_record(kind, 'list')
    if not workspace.configured():
        raise HTTPException(503, 'Supabase is not configured.')
    rows = await workspace.remote('GET', workspace.record_path(request.state.user['id'], kind) + '&order=updated_at.desc')
    return [row['payload'] for row in rows]


@app.get('/api/workspace/{kind}/{identifier}')
async def workspace_get(kind: str, identifier: str, request: Request):
    workspace.validate_record(kind, identifier)
    if not workspace.configured():
        raise HTTPException(503, 'Supabase is not configured.')
    return await workspace.load(request.state.user['id'], kind, identifier)


@app.put('/api/workspace/{kind}/{identifier}')
async def workspace_put(kind: str, identifier: str, request: Request):
    if not workspace.configured():
        raise HTTPException(503, 'Supabase is not configured.')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 48 * 1024 * 1024:
            raise HTTPException(413, 'This workspace record is too large.')
    import json
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError()
    except ValueError:
        raise HTTPException(400, 'Invalid workspace record.') from None
    workspace.validate_record(kind, identifier, payload)
    owner = request.state.user['id']
    if kind == 'chat':
        research = await workspace.load(owner, 'research', identifier)
        if research and research.get('state'):
            payload['state'] = research['state']
    if kind == 'research':
        # Client changes may rename a report, but cannot replace collected evidence.
        existing = await workspace.load(owner, kind, identifier)
        job = jobs.get(identifier)
        if existing and job and job.owner_id == owner and job.done and job.state:
            full = job.state.model_dump(mode='json')
            existing = {**existing, 'state': full, 'sources': full.get('sources', []),
                'report': job.state.final_report, 'status': 'failed' if job.error else 'complete'}
        if existing:
            payload = {**existing, **({'name': str(payload['name'])[:200]} if 'name' in payload else {})}
        elif payload.get('state'):
            from app.models import ResearchState
            try:
                ResearchState.model_validate(payload['state'])
            except ValueError:
                raise HTTPException(400, 'This saved research context could not be imported.') from None
    if kind == 'pdf' and payload.get('storage_path'):
        document = await workspace.load(owner, 'pdf', str(payload.get('id', '')))
        if not document or document.get('storage_path') != payload['storage_path']:
            raise HTTPException(403, 'Document ownership mismatch.')
    await workspace.save(owner, kind, identifier, payload)
    return {'saved': True}


@app.delete('/api/workspace/{kind}/{identifier}')
async def workspace_delete(kind: str, identifier: str, request: Request):
    workspace.validate_record(kind, identifier)
    if not workspace.configured():
        raise HTTPException(503, 'Supabase is not configured.')
    owner = request.state.user['id']
    if kind == 'research':
        job = jobs.get(identifier)
        if job and not job.done:
            raise HTTPException(409, 'Cancel running research before deleting it.')
    payload = await workspace.load(owner, kind, identifier)
    if kind == 'pdf' and payload and payload.get('storage_path'):
        rows = await workspace.remote('GET', workspace.record_path(owner, 'pdf'))
        references = [row for row in rows if row['payload'].get('id') == payload.get('id')
            and row['record_id'] not in {identifier, payload.get('id')}]
        if not references:
            await workspace.remote('DELETE', '/storage/v1/object/research-pdfs', json={'prefixes': [payload['storage_path']]})
            await workspace.remote('DELETE', workspace.record_path(owner, 'pdf', str(payload.get('id'))))
    await workspace.remote('DELETE', workspace.record_path(owner, kind, identifier))
    if kind == 'research':
        job = jobs.get(identifier)
        jobs.pop(identifier, None)
    return {'deleted': True}
origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:5174,https://research-ai-agent-4rpb-ruby.vercel.app",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    settings = __import__("app.config", fromlist=["Settings"]).Settings()
    return {
        "status": "ok",
        "llm_provider": "gemini",
        "model": settings.gemini_model,
        "tavily_configured": str(bool(settings.tavily_api_key)).lower(),
    }


@app.post("/api/research", response_model=ResearchStarted)
async def create_research(request: ResearchRequest, http_request: Request) -> ResearchStarted:
    try:
        return ResearchStarted(research_id=await start_research(request, getattr(http_request.state, 'user', None)))
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@app.get("/api/research/{research_id}/stream")
async def research_stream(research_id: str, request: Request, after: int = Query(default=0, ge=0)) -> StreamingResponse:
    if research_id not in jobs:
        raise HTTPException(status_code=404, detail="Research session not found")
    try:
        cursor = max(after, int(request.headers.get("Last-Event-ID", "0")))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event cursor") from None
    return StreamingResponse(stream_research(research_id, cursor, wire_ids=True), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@app.get("/api/research/{research_id}/status")
async def research_status(research_id: str):
    status = get_job_status(research_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Research session expired or not found")
    return status


@app.post("/api/research/{research_id}/cancel")
async def research_cancel(research_id: str):
    if not cancel_research(research_id):
        raise HTTPException(status_code=404, detail="Research session not found")
    return {"status": "cancelling"}


@app.get("/api/research/{research_id}")
async def research_result(research_id: str) -> dict:
    result = get_public_state(research_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Research result not found")
    return result


@app.post("/api/research/{research_id}/chat", response_model=ChatResponse)
async def research_chat(research_id: str, request: AssistantRequest) -> ChatResponse:
    try:
        return await chat_research(research_id, request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        logging.getLogger(__name__).exception("Research chat failed for %s", research_id)
        raise HTTPException(status_code=503, detail="The research assistant is temporarily unavailable.") from None


@app.get("/api/research/{research_id}/chat/index")
async def research_chat_index(research_id: str):
    try:
        return get_chat_documents(research_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/research/{research_id}/chat/stream")
async def research_chat_stream(research_id: str, request: AssistantRequest) -> StreamingResponse:
    try:
        assistant_job(research_id, request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(stream_chat(research_id, request), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


_pdf_upload_slots = asyncio.Semaphore(2)
@app.post("/api/assistant/pdf")
async def upload_assistant_pdf(request: Request, name: str = Query(default="document.pdf", min_length=1, max_length=200)):
    from app.pdf_documents import MAX_UPLOAD_BYTES, process_pdf
    if not name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a PDF file.")
    async with _pdf_upload_slots:
        with tempfile.TemporaryDirectory(prefix="research-pdf-") as folder:
            path = Path(folder) / "upload.pdf"
            size = 0
            with path.open("wb") as target:
                async for data in request.stream():
                    size += len(data)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="PDFs must be 25 MB or smaller. Split the document and try again.")
                    target.write(data)
            with path.open("rb") as source:
                if not source.read(1024).lstrip().startswith(b"%PDF-"):
                    raise HTTPException(status_code=400, detail="This file is not a valid PDF.")
            try:
                result = await asyncio.to_thread(process_pdf, str(path), str(Path(folder) / "result.json"))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            identifier = str(uuid4())
            document = {"id": identifier, "name": name, **result}
            user = getattr(request.state, 'user', None)
            if user:
                storage_path = f"{user['id']}/{identifier}.pdf"
                await workspace.remote('POST', '/storage/v1/object/research-pdfs/' + storage_path,
                    headers={'Content-Type': 'application/pdf'}, content=path.read_bytes())
                document['storage_path'] = storage_path
                # Keep extraction even if the browser closes before attaching it to a chat.
                await workspace.save(user['id'], 'pdf', identifier, document)
            return document


@app.get("/api/assistant/research-ideas")
async def assistant_research_ideas():
    from app.research_ideas import recent_ideas
    return {"ideas": await recent_ideas()}
