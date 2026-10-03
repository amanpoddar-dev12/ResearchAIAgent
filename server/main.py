import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .api.models import ResearchRequest, ResearchStarted
from app.chat import ChatRequest, ChatResponse
from .api.research import chat_research, get_public_state, jobs, start_research, stream_research, get_job_status, cancel_research, cleanup_jobs


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
async def research_chat(research_id: str, request: ChatRequest) -> ChatResponse:
    try:
        return await chat_research(research_id, request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logging.getLogger(__name__).exception("Research chat failed for %s", research_id)
        raise HTTPException(status_code=503, detail="The research assistant is temporarily unavailable.") from None
