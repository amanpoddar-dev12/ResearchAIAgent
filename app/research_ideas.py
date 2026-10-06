"""Recent research ideas, cached independently of research jobs."""
import asyncio
import time
from datetime import datetime, timezone
from app.config import Settings
from tools.web_search import search_web
_cached: list[str] = []
_expires = 0.0
_lock = asyncio.Lock()
async def recent_ideas() -> list[str]:
    global _cached, _expires
    async with _lock:
        if time.monotonic() < _expires: return _cached
        settings = Settings()
        ideas = []
        if settings.tavily_api_key:
            date = datetime.now(timezone.utc).strftime("%B %Y")
            results = await asyncio.to_thread(search_web, settings.tavily_api_key, f"latest research developments {date} artificial intelligence energy climate medicine science", 12, timeout=8)
            ideas = list(dict.fromkeys(f"What does the evidence say about {item.title.strip().rstrip('.?')[:170]}?" for item in results if item.title.strip()))
        _cached = ideas
        _expires = time.monotonic() + (21600 if ideas else 900)
        return ideas
