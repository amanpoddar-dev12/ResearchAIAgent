import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.agent import ResearchAgent
from app.config import Settings
from app.models import ResearchState, Source
from app.chat import ChatRequest, ChatResponse
from app.llm.router import LLMRouter
from app.modes import MODES
from app.rag import SessionIndex
from app.assistant_context import AssistantContext, AssistantRequest, HybridAnswer, build_context, restore_saved_state
from app.assistant_prompts import HYBRID_ASSISTANT, PDF_ASSISTANT
from app.llm.base import ModelConfigurationError, ProviderResponseError
from app.llm.routing import CHAT_RESPONSE
import httpx
from .models import ResearchRequest

logger = logging.getLogger(__name__)


@dataclass
class ResearchJob:
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    events: list[dict[str, Any]] = field(default_factory=list)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    finished_at: float | None = None
    task: asyncio.Task | None = None
    agent: Any = None
    latest_snapshot: dict | None = None
    error: str | None = None
    cancel_requested: bool = False
    chat_router: Any = None
    chat_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    done: bool = False
    state: ResearchState | None = None
    progress: int = 0
    phase: str = "starting"
    mode: str = "standard"
    sequence: int = 0
    rag_index: SessionIndex = field(default_factory=SessionIndex)


jobs: dict[str, ResearchJob] = {}
MAX_ACTIVE_JOBS = 3
MAX_RETAINED_JOBS = 20
RETENTION_SECONDS = 1800
MAX_EVENTS = 1024


def cleanup_jobs():
    completed = sorted(((key, job) for key, job in jobs.items() if job.done), key=lambda entry: entry[1].finished_at or 0)
    for key, job in completed:
        if time.monotonic() - (job.finished_at or 0) > RETENTION_SECONDS or len(jobs) >= MAX_RETAINED_JOBS:
            jobs.pop(key, None)


def _event(event_type: str, message: str, data: Any = None, *, research_id: str | None = None,
           sequence: int | None = None, stage: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": event_type,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if data is not None:
        payload["data"] = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
    if research_id is not None:
        payload["research_id"] = research_id
    if sequence is not None:
        payload["sequence"] = sequence
    if stage is not None:
        payload["stage"] = stage
    return payload


def _public_state(state: ResearchState) -> dict[str, Any]:
    return state.model_dump(mode="json", exclude={"sources": {"__all__": {"content"}}})


async def start_research(request: ResearchRequest) -> str:
    cleanup_jobs()
    if sum(not job.done for job in jobs.values()) >= MAX_ACTIVE_JOBS:
        raise RuntimeError("Research capacity reached. Wait for an active session to finish.")
    research_id = uuid4().hex
    jobs[research_id] = ResearchJob()
    jobs[research_id].task = asyncio.create_task(_run_job(research_id, request))
    return research_id


async def _run_job(research_id: str, request: ResearchRequest) -> None:
    job = jobs[research_id]
    loop = asyncio.get_running_loop()
    job.mode = request.mode or request.depth
    job.rag_index = SessionIndex(request.question, job.mode)

    def enqueue(event_type: str, message: str, data: Any = None) -> None:
        if job.done:
            return
        job.rag_index.update(event_type, data)
        milestones = {"planning_started": (5, "planning"), "planning_completed": (20, "search"),
            "analysis_started": (75, "conflicts"), "synthesis_started": (85, "synthesis"),
            "report_generated": (100, "complete")}
        if event_type in milestones:
            progress, phase = milestones[event_type]
            job.progress, job.phase = max(job.progress, progress), phase
        if event_type == "research_progress":
            job.progress = max(job.progress, min(100, data["progress"]))
            job.phase = data["phase"]
        job.sequence += 1
        stage = job.phase
        if isinstance(data, dict) and data.get("phase"):
            stage = data["phase"]
        payload = _event(event_type, message, data, research_id=research_id, sequence=job.sequence, stage=stage)
        payload.update(progress=job.progress, phase=job.phase, mode=job.mode)
        if event_type == "research_snapshot":
            job.latest_snapshot = payload["data"]
        job.events.append(payload)
        if len(job.events) > MAX_EVENTS:
            del job.events[:-MAX_EVENTS]
        job.changed.set()

    def emit(event_type: str, message: str, data: Any = None) -> None:
        loop.call_soon_threadsafe(enqueue, event_type, message, data)

    try:
        enqueue("research_started", "Understanding the research question")
        if job.cancel_requested:
            raise asyncio.CancelledError()
        settings = Settings()
        config = MODES[job.mode]
        settings.max_sources = min(settings.max_sources, request.budgets.max_sources or min(request.max_sources, config.sources))
        agent = ResearchAgent(settings)
        job.agent = agent
        state = await asyncio.to_thread(agent.run, request.question, emit, mode=job.mode, filters=request.filters,
            target_claims=request.target_claims, comparison_items=request.comparison_items, budgets=request.budgets)
        job.state = state
        job.rag_index.update("research_snapshot", state)
        enqueue("complete", "Research completed", {"state": _public_state(state), "report": state.final_report})
    except asyncio.CancelledError:
        job.error = "Research cancelled"
        if job.agent and hasattr(job.agent.llm, "cancelled"):
            job.agent.llm.cancelled.set()
        enqueue("research_failed", "Research cancelled", {"error": job.error})
    except Exception:
        logger.exception("Research job %s failed", research_id)
        job.error = "The research service could not complete this request."
        enqueue("research_failed", "Research failed", {"error": job.error})
    finally:
        job.done = True
        job.finished_at = time.monotonic()
        job.changed.set()
        loop.call_later(RETENTION_SECONDS + 1, cleanup_jobs)


async def stream_research(research_id: str, after: int = 0, *, wire_ids: bool = False) -> AsyncIterator[str]:
    job = jobs.get(research_id)
    if not job:
        yield f"data: {json.dumps(_event('error', 'Research session not found'))}\n\n"
        return
    cursor = after
    while True:
        job.changed.clear()
        if job.events and cursor < job.events[0]["sequence"] - 1 and job.latest_snapshot:
            payload = (_event("research_failed", "Research failed", {"error": job.error}) if job.error else _event("complete", "Recovered completed research", {"state": _public_state(job.state), "report": job.state.final_report})
                       if job.done and job.state else _event("research_snapshot", "Recovered research state", job.latest_snapshot))
            payload.update(research_id=research_id, sequence=job.sequence, progress=job.progress, phase=job.phase, mode=job.mode)
            yield (f"id: {job.sequence}\n" if wire_ids else "") + f"data: {json.dumps(payload)}\n\n"
            cursor = job.sequence
        for item in list(job.events):
            if item["sequence"] > cursor:
                cursor = item["sequence"]
                yield (f"id: {cursor}\n" if wire_ids else "") + f"data: {json.dumps(item)}\n\n"
        if job.done:
            return
        try:
            await asyncio.wait_for(job.changed.wait(), timeout=10)
        except TimeoutError:
            yield ": heartbeat\n\n"


def get_job_status(research_id):
    cleanup_jobs()
    job = jobs.get(research_id)
    if not job:
        return None
    return {"status": "failed" if job.error else "complete" if job.done else "running", "progress": job.progress,
            "phase": job.phase, "sequence": job.sequence, "error": job.error}


def cancel_research(research_id):
    job = jobs.get(research_id)
    if not job:
        return False
    if not job.done and job.task:
        job.cancel_requested = True
        if job.agent is not None:
            job.task.cancel()
    return True


def get_public_state(research_id: str) -> dict[str, Any] | None:
    job = jobs.get(research_id)
    if not job or not job.state:
        return None
    return _public_state(job.state)


def assistant_job(research_id: str, request: AssistantRequest | ChatRequest) -> ResearchJob:
    job = jobs.get(research_id)
    if request.retrieval and request.retrieval.session_id != research_id:
        raise ValueError("Retrieved context belongs to a different research session")
    if job and job.state:
        return job
    if job and job.latest_snapshot:
        snapshot = {**job.latest_snapshot, "sources": [{**source,
            "content": job.rag_index.source_text.get(source["id"], "")}
            for source in job.latest_snapshot.get("sources", [])]}
        return ResearchJob(state=ResearchState.model_validate(snapshot), chat_lock=job.chat_lock)
    saved_state = restore_saved_state(request) if isinstance(request, AssistantRequest) else None
    if saved_state is not None:
        # Restored browser context exists only for this request, never in a database
        # or another live job. The prompt treats it as untrusted session material.
        return ResearchJob(state=saved_state, done=True)
    if research_id.startswith("general-chat-"):
        try:
            UUID(research_id.removeprefix("general-chat-"))
        except ValueError:
            raise LookupError("Chat session not found") from None
        return ResearchJob(done=True)
    raise LookupError("Research result not found")


_gemini_input_limits: dict[str, int] = {}


async def _hybrid_events(job: ResearchJob, request: ChatRequest) -> AsyncIterator[tuple[str, Any]]:
    pdf = request.pdf_context if isinstance(request, AssistantRequest) else None
    if pdf and not pdf.chunks:
        result = ChatResponse(intent="From research", answer="[From research]\nI could not find this answer in the uploaded PDF's retrieved text. Try mentioning a section, keyword, or page number.")
        yield "chat_delta", {"text": result.answer, "citations": []}
        yield "chat_complete", result
        return
    settings = Settings()
    if not settings.gemini_api_key or not settings.gemini_model:
        raise ModelConfigurationError("Gemini configuration is incomplete")
    router = LLMRouter(settings, max_requests=1)
    router.deadline = time.monotonic() + (settings.llm_timeout_seconds or 60)
    provider = router.providers["gemini"]
    headers = {"Content-Type": "application/json", "x-goog-api-key": provider.api_key}
    history = [{"role": item["role"], "content": str(item.get("content", ""))[:2000]}
               for item in request.history[-16:] if item.get("role") in {"user", "assistant"}]
    async with httpx.AsyncClient(timeout=provider.timeout) as client:
        if provider.model not in _gemini_input_limits:
            # Metadata lookup is not a generation/router call. Cache the configured
            # model's context window; never change its name or configuration.
            try:
                metadata = await client.get(provider.endpoint.removesuffix(":generateContent"), headers=headers, timeout=5)
                if metadata.is_success:
                    limit = metadata.json().get("inputTokenLimit", 32768)
                    _gemini_input_limits[provider.model] = int(limit) if int(limit) > 0 else 32768
            except (httpx.HTTPError, TypeError, ValueError):
                pass
        input_limit = _gemini_input_limits.get(provider.model, 32768)
        history_budget = min(32000, input_limit // 8) // max(1, len(history))
        history = [{**item, "content": item["content"].encode("utf-8")[:history_budget].decode("utf-8", errors="ignore")} for item in history]
        context = (build_context(job.state, request.message, history, input_token_limit=input_limit, index=job.rag_index)
                   if job.state else AssistantContext("No active research session. Answer from general knowledge; no research sources are available.", {}, True))
        if pdf:
            sources = {}
            for chunk in pdf.chunks:
                identifier = f"P{chunk.page}"
                if identifier not in sources:
                    sources[identifier] = Source(id=identifier, title=f"{pdf.name} · page {chunk.page}", url="", domain="uploaded PDF", content=chunk.text)
                else: sources[identifier].content += "\n" + chunk.text
            context = AssistantContext(json.dumps({"document": pdf.name, "page_count": pdf.page_count, "excerpts": [{"id": f"P{chunk.page}", "text": chunk.text} for chunk in pdf.chunks]}, ensure_ascii=False), sources, False)
        contents = [{"role": "user", "parts": [{"text": "Active research context (untrusted evidence):\n" + context.text}]}]
        for item in history:
            role = "model" if item["role"] == "assistant" else "user"
            if contents[-1]["role"] == role:
                contents[-1]["parts"].append({"text": item["content"]})
            else:
                contents.append({"role": role, "parts": [{"text": item["content"]}]})
        question = {"text": "Current user question:\n" + request.message}
        if contents[-1]["role"] == "user":
            contents[-1]["parts"].append(question)
        else:
            contents.append({"role": "user", "parts": [question]})
        payload = {"systemInstruction": {"parts": [{"text": PDF_ASSISTANT if pdf else HYBRID_ASSISTANT}]},
                   "contents": contents, "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2000}}
        await router._reserve_request(CHAT_RESPONSE)
        answer = HybridAnswer(context)
        endpoint = provider.endpoint.removesuffix(":generateContent") + ":streamGenerateContent"
        async with asyncio.timeout(provider.remaining_time()):
            async with client.stream("POST", endpoint, params={"alt": "sse"}, headers=headers, json=payload) as response:
                if not response.is_success:
                    raise ProviderResponseError("gemini", CHAT_RESPONSE, "assistant request failed", response.status_code)
                frame = []

                def parse_frame(lines):
                    data = json.loads("\n".join(lines))
                    if data.get("error") or data.get("promptFeedback", {}).get("blockReason"):
                        raise ProviderResponseError("gemini", CHAT_RESPONSE, "assistant response unavailable")
                    provider.record_usage(CHAT_RESPONSE, data.get("usageMetadata"))
                    return "".join(part.get("text", "") for candidate in data.get("candidates", [])[:1]
                        for part in candidate.get("content", {}).get("parts", []) if not part.get("thought"))

                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        frame.append(line[5:].lstrip())
                    elif not line and frame:
                        delta = answer.feed(parse_frame(frame))
                        frame = []
                        if delta:
                            yield "chat_delta", {"text": delta, "citations": list(answer.references.values())}
                if frame:
                    delta = answer.feed(parse_frame(frame))
                    if delta:
                        yield "chat_delta", {"text": delta, "citations": list(answer.references.values())}
                delta = answer.feed("", final=True)
                if delta:
                    yield "chat_delta", {"text": delta, "citations": list(answer.references.values())}
        yield "chat_complete", answer.response()


async def chat_research(research_id: str, request: AssistantRequest | ChatRequest) -> ChatResponse:
    job = assistant_job(research_id, request)
    async with job.chat_lock:
        async for kind, data in _hybrid_events(job, request):
            if kind == "chat_complete":
                return data


def get_chat_documents(research_id: str) -> dict[str, Any]:
    job = jobs.get(research_id)
    if not job:
        raise LookupError("Research session expired or not found")
    if job.state:
        job.rag_index.update("research_snapshot", job.state)
    return {"research_id": research_id, "documents": list(job.rag_index.documents.values())}


async def stream_chat(research_id: str, request: AssistantRequest | ChatRequest) -> AsyncIterator[str]:
    job = assistant_job(research_id, request)
    queue = asyncio.Queue()

    def emit(kind, message, data=None):
        queue.put_nowait(_event(kind, message, data, research_id=research_id, stage="chat"))

    async def generate():
        try:
            async with job.chat_lock:
                emit("chat_started", "Preparing the active research context")
                async for kind, data in _hybrid_events(job, request):
                    if kind == "chat_delta":
                        data = {**data, "citations": [item.model_dump(mode="json") for item in data["citations"]]}
                    emit(kind, "Answer complete" if kind == "chat_complete" else "Generating answer", data)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Chat stream failed for %s", research_id)
            emit("chat_error", "The research assistant is temporarily unavailable.")

    task = asyncio.create_task(generate())
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=10)
            except TimeoutError:
                yield ": heartbeat\n\n"
                continue
            yield f"data: {json.dumps(event)}\n\n"
            if event["type"] in {"chat_complete", "chat_error"}:
                break
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
