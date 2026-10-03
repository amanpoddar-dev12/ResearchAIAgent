"""Small deterministic controls operating on the existing session state."""

import asyncio
from datetime import datetime, timezone
from functools import partial
import time

from app.models import AuditEntry, StopDecision


def audit(state, action: str, message: str, **details):
    entry = AuditEntry(id=len(state.audit_log) + 1, timestamp=datetime.now(timezone.utc).isoformat(),
        action=action, message=message, details=details)
    state.audit_log.append(entry)
    return entry


def decide_stop(*, coverage: float, unresolved: list[str], gains: list[int], searches: int, sources: int,
                iterations: int, elapsed: float, max_searches: int, max_sources: int,
                max_iterations: int, max_wall_seconds: float, plateau_window: int = 4) -> StopDecision:
    """Pure: never consumes budgets, changes state, or reads the clock."""
    reason = "Unresolved evidence gaps remain"
    stop = False
    for used, limit, name in [(elapsed, max_wall_seconds, "wall-clock"), (searches, max_searches, "search"),
                              (sources, max_sources, "source"), (iterations, max_iterations, "iteration")]:
        if used >= limit:
            stop, reason = True, f"{name} budget exhausted"
            break
    if not stop and coverage >= .9 and not unresolved:
        stop, reason = True, "Evidence coverage reached"
    if not stop and len(gains) >= plateau_window and all(gain == 0 for gain in gains[-plateau_window:]):
        stop, reason = True, "New-evidence gain plateau"
    return StopDecision(stop=stop, reason=reason, coverage=round(coverage, 4), unresolved=list(unresolved))


async def bounded_call(executor, deadline, function, *args, **kwargs):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Wall-clock budget exhausted")
    # Workers return values only. The coordinator owns all state writes and SSE emission.
    future = asyncio.get_running_loop().run_in_executor(executor, partial(function, *args, **kwargs))
    return await asyncio.wait_for(future, timeout=remaining)


def coverage_gaps(state):
    covered = set()
    gaps = []
    sources = {source.id: source for source in state.sources}
    for claim in state.findings:
        domains = {sources[sid].domain for sid in claim.source_ids if sid in sources}
        independent = len(domains) >= (2 if state.semantic_validation_required and state.mode != "quick" else 1)
        if claim.evidence_status in {"Supported", "Contradicted"} and independent:
            covered.update(claim.sub_question_ids)
        if claim.evidence_status in {"Unverified", "Partially Supported"}:
            gaps.append((claim.claim + " evidence corroboration contradiction", f"{claim.id}: {claim.evidence_status}", claim.sub_question_ids))
        elif not independent:
            gaps.append((claim.claim + " independent replication evidence", f"{claim.id}: lacks independent corroboration", claim.sub_question_ids))
        elif not any(sources[sid].source_type in {"primary", "academic", "documentation"} for sid in claim.source_ids if sid in sources):
            gaps.append((claim.claim + " original primary source", f"{claim.id}: lacks a primary source", claim.sub_question_ids))
    tasks = state.plan.sub_question_tasks if state.plan else []
    question_gaps = []
    for task in tasks:
        if task.id not in covered:
            variants = [task.query, task.query + " primary source evidence", task.query + " original study methods limitations", task.query + " conflicting evidence replication", task.query + " official dataset measurements"]
            query = next((query for query in variants if query.casefold() not in state.searched_queries), variants[-1])
            question_gaps.append((query, f"{task.id}: sub-question has no verified evidence", [task.id]))
    coverage = len(covered.intersection(task.id for task in tasks)) / len(tasks) if tasks else 0
    if not tasks and not state.findings:
        gaps.append((state.question.question, "Question has no evidence", []))
    return coverage, question_gaps + gaps
