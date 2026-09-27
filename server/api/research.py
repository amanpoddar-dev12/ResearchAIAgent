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
from .models import ResearchRequest

logger = logging.getLogger(__name__)


@dataclass
class ResearchJob:
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    done: bool = False
    state: ResearchState | None = None


jobs: dict[str, ResearchJob] = {}


def _event(event_type: str, message: str, data: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": event_type,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if data is not None:
        payload["data"] = data.model_dump(mode="json") if hasattr(data, "model_dump") else data
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
    settings = Settings(
        gemini_api_key=Settings().gemini_api_key,
        gemini_model=Settings().gemini_model,
        tavily_api_key=Settings().tavily_api_key,
        max_llm_requests=Settings().max_llm_requests,
        gemini_timeout=Settings().gemini_timeout,
        max_sources=request.max_sources,
        max_searches={"quick": 3, "standard": 6, "deep": 10}[request.depth],
        max_iterations={"quick": 1, "standard": 3, "deep": 5}[request.depth],
    )

    def emit(event_type: str, message: str, data: Any = None) -> None:
        asyncio.run_coroutine_threadsafe(job.queue.put(_event(event_type, message, data)), loop)

    try:
        emit("research_started", "Understanding the research question")
        agent = ResearchAgent(settings)
        state = await asyncio.to_thread(agent.run, request.question, emit)
        job.state = state
        emit("complete", "Research completed", {"state": _public_state(state), "report": state.final_report})
    except Exception as exc:
        logger.exception("Research job %s failed", research_id)
        emit("research_failed", "Research failed", {"error": str(exc) if settings.debug else "The research service could not complete this request."})
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
