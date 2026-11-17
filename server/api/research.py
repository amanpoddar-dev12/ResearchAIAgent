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
from app.assistant_context import AssistantContext, AssistantRequest, HybridAnswer, build_context, restore_saved_state, review_hybrid_answer
from app.assistant_prompts import HYBRID_ASSISTANT, PDF_ASSISTANT
from app.llm.base import ModelConfigurationError, ProviderResponseError
from app.llm.routing import CHAT_RESPONSE
import httpx
from .models import ResearchRequest

logger = logging.getLogger(__name__)


@dataclass
class ResearchJob:
    review_future: asyncio.Future | None = None
    review_token: str | None = None
    review_gaps: set[str] = field(default_factory=set)
    parent_state: ResearchState | None = None
    owner_id: str | None = None
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
_start_lock = asyncio.Lock()


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


async def start_research(request: ResearchRequest, user: dict | None = None) -> str:
    # ponytail: process-wide lock across reservations; distributed execution needs a job queue.
    async with _start_lock:
        return await _start_research(request, user)


async def _start_research(request: ResearchRequest, user: dict | None = None) -> str:
    cleanup_jobs()
    if sum(not job.done for job in jobs.values()) >= MAX_ACTIVE_JOBS:
        raise RuntimeError("Research capacity reached. Wait for an active session to finish.")
    research_id = uuid4().hex
    parent_state = None
    if request.parent_research_id:
        from fastapi import HTTPException
        if user:
            from server.workspace import load
            parent = await load(user['id'], 'research', request.parent_research_id)
            if parent and parent.get('status') == 'complete' and parent.get('state'):
                parent_state = ResearchState.model_validate(parent['state'])
        else:
            parent_job = jobs.get(request.parent_research_id)
            if parent_job and parent_job.done and parent_job.owner_id is None and not parent_job.error:
                parent_state = parent_job.state
        if parent_state is None:
            raise HTTPException(404, 'Completed parent research not found in your workspace.')
    if user:
        from server.workspace import reserve, save
        await reserve(user, research_id)
        try:
            await save(user['id'], 'research', research_id, {'id': research_id, 'question': request.question,
                'mode': request.mode or request.depth, 'report': '', 'sources': [], 'status': 'running',
                'savedAt': datetime.now(timezone.utc).isoformat()})
        except Exception:
            from server.workspace import refund
            await refund(user['id'], research_id)
            raise
    jobs[research_id] = ResearchJob(owner_id=user['id'] if user else None, parent_state=parent_state)
    jobs[research_id].task = asyncio.create_task(_run_job(research_id, request))
    return research_id


async def _run_job(research_id: str, request: ResearchRequest) -> None:
    job = jobs[research_id]
    loop = asyncio.get_running_loop()
    job.mode = request.mode or request.depth
    job.rag_index = SessionIndex(request.question, job.mode)
    async def checkpoint():
        # Persist bounded snapshots, never every streamed event/token.
        from server.workspace import save
        while True:
            await asyncio.sleep(5)
            if job.owner_id and job.latest_snapshot:
                snapshot = {**job.latest_snapshot, 'sources': [{**source,
                    'content': job.rag_index.source_text.get(source['id'], source.get('content', ''))}
                    for source in job.latest_snapshot.get('sources', [])]}
                try:
                    await save(job.owner_id, 'research', research_id, {'id': research_id, 'question': request.question,
                        'mode': job.mode, 'report': '', 'state': snapshot, 'sources': snapshot.get('sources', []),
                        'status': 'running', 'savedAt': datetime.now(timezone.utc).isoformat()})
                except Exception:
                    logger.warning('Cloud checkpoint unavailable for %s', research_id)
    checkpoint_task = asyncio.create_task(checkpoint()) if job.owner_id else None

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
        continuation = {'parent_state': job.parent_state, 'parent_research_id': request.parent_research_id} if job.parent_state else {}
        if request.brief:
            continuation['brief'] = request.brief
        if request.review_checkpoint:
            def review(state):
                async def wait_review():
                    job.review_token = uuid4().hex
                    job.review_gaps = {gap.gap_id for gap in state.research_gaps}
                    job.review_future = loop.create_future()
                    enqueue('research_checkpoint', 'Review sources before the report is written', {
                        'token': job.review_token, 'sources': [source.model_dump(exclude={'content'}) for source in state.sources],
                        'gaps': [gap.model_dump() for gap in state.research_gaps],
                        'canInvestigate': state.iteration < state.max_iterations and state.searches_performed < state.max_searches and len(state.sources) < state.max_sources and state.llm_requests_used < state.max_llm_requests - 2,
                        'expiresInSeconds': 900})
                    try:
                        choices = await asyncio.wait_for(job.review_future, timeout=900)
                        enqueue('checkpoint_resumed', 'Source review complete; research is continuing')
                        return choices
                    except asyncio.TimeoutError:
                        enqueue('checkpoint_resumed', 'Review timed out; continuing with collected evidence')
                        return []
                    finally:
                        job.review_future = None
                        job.review_token = None
                future = asyncio.run_coroutine_threadsafe(wait_review(), loop)
                try:
                    return future.result(timeout=920)
                finally:
                    if not future.done():
                        future.cancel()
            continuation['review_checkpoint'] = review
        state = await asyncio.to_thread(agent.run, request.question, emit, mode=job.mode, filters=request.filters,
            target_claims=request.target_claims, comparison_items=request.comparison_items, budgets=request.budgets, **continuation)
        job.state = state
        job.rag_index.update("research_snapshot", state)
    except asyncio.CancelledError:
        job.error = "Research cancelled"
        if job.agent and hasattr(job.agent.llm, "cancelled"):
            job.agent.llm.cancelled.set()
        enqueue("research_failed", "Research cancelled", {"error": job.error})
    except Exception as exc:
        logger.error("Research job %s failed (%s)", research_id, type(exc).__name__)
        job.error = "The research service could not complete this request."
        enqueue("research_failed", "Research failed", {"error": job.error})
    finally:
        if checkpoint_task:
            checkpoint_task.cancel()
            await asyncio.gather(checkpoint_task, return_exceptions=True)
        if job.owner_id:
            from server.workspace import save, refund
            try:
                full = job.state.model_dump(mode='json') if job.state else job.latest_snapshot
                if full:
                    full = {**full, 'sources': [{**source, 'content': job.rag_index.source_text.get(source['id'], source.get('content', ''))}
                        for source in full.get('sources', [])]}
                await save(job.owner_id, 'research', research_id, {'id': research_id, 'question': request.question,
                    'mode': job.mode, 'report': job.state.final_report if job.state else '', 'state': full,
                    'sources': full.get('sources', []) if full else [], 'status': 'failed' if job.error else 'complete',
                    'savedAt': datetime.now(timezone.utc).isoformat(), 'error': job.error})
            except Exception:
                logger.error('Could not persist research %s; its in-memory result remains available', research_id)
                enqueue('cloud_save_failed', 'Cloud save failed. Export this research or retry saving before leaving.')
            if job.error and not job.cancel_requested:
                try:
                    await refund(job.owner_id, research_id)
                except Exception:
                    logger.error('Guest allowance refund needs retry for research %s', research_id)
                    enqueue('cloud_save_failed', 'The failed run could not be refunded because cloud storage is unavailable. Contact support with this research ID.')
        if job.state and not job.error:
            enqueue("complete", "Research completed", {"state": _public_state(job.state), "report": job.state.final_report})
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
        if job.review_future and not job.review_future.done():
            job.review_future.set_exception(RuntimeError('Research cancelled during source review'))
        if job.agent is not None:
            job.task.cancel()
    return True


def get_public_state(research_id: str) -> dict[str, Any] | None:
    job = jobs.get(research_id)
    if not job or not job.state:
        return None
    if job.owner_id and not job.done:
        return None  # Do not race research_completed against the final cloud save.
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
    router = LLMRouter(settings, max_requests=2)
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
                    if any(candidate.get('finishReason') == 'MAX_TOKENS' for candidate in data.get('candidates', [])[:1]):
                        raise ProviderResponseError('gemini', CHAT_RESPONSE, 'assistant output token limit reached')
                    provider.record_usage(CHAT_RESPONSE, data.get("usageMetadata"))
                    return "".join(part.get("text", "") for candidate in data.get("candidates", [])[:1]
                        for part in candidate.get("content", {}).get("parts", []) if not part.get("thought"))

                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        frame.append(line[5:].lstrip())
                    elif not line and frame:
                        delta = answer.feed(parse_frame(frame))
                        frame = []
                        if delta and answer.tag == "General knowledge":
                            yield "chat_delta", {"text": delta, "citations": list(answer.references.values())}
                if frame:
                    delta = answer.feed(parse_frame(frame))
                    if delta and answer.tag == "General knowledge":
                        yield "chat_delta", {"text": delta, "citations": list(answer.references.values())}
                delta = answer.feed("", final=True)
                if delta and answer.tag == "General knowledge":
                    yield "chat_delta", {"text": delta, "citations": list(answer.references.values())}
        result = answer.response()
        if result.intent != 'General knowledge':
            result = await review_hybrid_answer(router, context, request.message, result)
            # Keep the existing SSE contract; publish reviewed text in small increments.
            for start in range(0, len(result.answer), 48):
                yield 'chat_delta', {'text':result.answer[start:start+48], 'citations': result.citations}
        yield "chat_complete", result


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


async def stream_chat(research_id: str, request: AssistantRequest | ChatRequest, *, response_id: str | None = None) -> AsyncIterator[str]:
    job = assistant_job(research_id, request)
    queue = asyncio.Queue()

    def emit(kind, message, data=None):
        queue.put_nowait(_event(kind, message, data, research_id=response_id or research_id, stage="chat"))

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
        except Exception as exc:
            logger.error("Chat stream failed for %s (%s)", research_id, type(exc).__name__)
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
