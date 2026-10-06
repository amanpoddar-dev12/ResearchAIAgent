import os
import logging
import asyncio
import tempfile
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
    allow_methods=["GET", "POST"],
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
async def create_research(request: ResearchRequest) -> ResearchStarted:
    try:
        return ResearchStarted(research_id=await start_research(request))
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
            return {"id": str(uuid4()), "name": name, **result}


@app.get("/api/assistant/research-ideas")
async def assistant_research_ideas():
    from app.research_ideas import recent_ideas
    return {"ideas": await recent_ideas()}
