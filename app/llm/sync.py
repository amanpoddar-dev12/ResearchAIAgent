"""Small sync bridge for existing thread-based orchestration."""

import asyncio


def run_sync(awaitable):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("Synchronous LLM calls must run outside an active event loop.")
