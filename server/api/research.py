import asyncio
import json
import logging
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
    done: bool = False
    state: ResearchState | None = None
    progress: int = 0
    phase: str = "starting"
    mode: str = "standard"
    sequence: int = 0


jobs: dict[str, ResearchJob] = {}


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
    payload = state.model_dump(mode="json")
    payload["sources"] = [
        {key: value for key, value in source.items() if key != "content"}
        for source in payload["sources"]
    ]
    return payload


async def start_research(request: ResearchRequest) -> str:
    research_id = uuid4().hex
    jobs[research_id] = ResearchJob()
    asyncio.create_task(_run_job(research_id, request))
    return research_id


async def _run_job(research_id: str, request: ResearchRequest) -> None:
    job = jobs[research_id]
    loop = asyncio.get_running_loop()
    job.mode = request.mode or request.depth

    def enqueue(event_type: str, message: str, data: Any = None) -> None:
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
        job.queue.put_nowait(payload)

    def emit(event_type: str, message: str, data: Any = None) -> None:
        loop.call_soon_threadsafe(enqueue, event_type, message, data)

    try:
        enqueue("research_started", "Understanding the research question")
        settings = Settings()
        config = MODES[job.mode]
        settings.max_sources = request.budgets.max_sources or min(settings.max_sources, request.max_sources, config.sources)
        agent = ResearchAgent(settings)
        state = await asyncio.to_thread(agent.run, request.question, emit, mode=job.mode, filters=request.filters,
            target_claims=request.target_claims, comparison_items=request.comparison_items, budgets=request.budgets)
        job.state = state
        enqueue("complete", "Research completed", {"state": _public_state(state), "report": state.final_report})
    except Exception:
        logger.exception("Research job %s failed", research_id)
        enqueue("research_failed", "Research failed", {"error": "The research service could not complete this request."})
    finally:
        job.done = True
        await job.queue.put({"type": "_end"})


async def stream_research(research_id: str) -> AsyncIterator[str]:
    job = jobs.get(research_id)
    if not job:
        yield f"data: {json.dumps(_event('error', 'Research session not found'))}\n\n"
        return
    while True:
        item = await job.queue.get()
        if item["type"] == "_end":
            break
        yield f"data: {json.dumps(item)}\n\n"


def get_public_state(research_id: str) -> dict[str, Any] | None:
    job = jobs.get(research_id)
    if not job or not job.state:
        return None
    return _public_state(job.state)


async def chat_research(research_id: str, request: ChatRequest) -> ChatResponse:
    job = jobs.get(research_id)
    if not job or not job.state:
        raise LookupError("Research result not found")
    settings = Settings()
    router = LLMRouter(settings, max_requests=4)
    return await asyncio.to_thread(answer_chat, router, request, job.state)
