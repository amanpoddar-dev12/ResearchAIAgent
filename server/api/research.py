import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.agent import ResearchAgent
from app.config import Settings
from app.models import ResearchState
from app.chat import ChatRequest, ChatResponse, answer_chat
from app.llm.router import LLMRouter
from app.modes import MODES
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

    def enqueue(event_type: str, message: str, data: Any = None) -> None:
        if job.done:
            return
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


async def chat_research(research_id: str, request: ChatRequest) -> ChatResponse:
    job = jobs.get(research_id)
    if not job or not job.state:
        raise LookupError("Research result not found")
    async with job.chat_lock:
        if job.chat_router is None:
            job.chat_router = LLMRouter(Settings(), max_requests=12)
        job.chat_router.deadline = time.monotonic() + 30
        return await asyncio.to_thread(answer_chat, job.chat_router, request, job.state)
