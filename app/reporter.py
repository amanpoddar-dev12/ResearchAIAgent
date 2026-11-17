"""Markdown report and research trace persistence."""

from datetime import datetime
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from app.models import ResearchState


def save_report(report: str, directory: str = "reports") -> Path:
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    filename = datetime.now().strftime("research_%Y_%m_%d_%H%M%S.md")
    target = path / filename
    target.write_text(report, encoding="utf-8")
    return target


_REDACT_KEYS = {"content", "excerpt", "final_report", "previous_context", "report"}


def _trace_value(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            key: "<redacted>" if key.lower() in _REDACT_KEYS else _trace_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_trace_value(item) for item in value]
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return value


def save_trace(state: ResearchState, events: list[dict], directory: str = "logs") -> Path:
    """Write one JSONL record per emitted event and audit decision."""
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    filename = datetime.now().strftime("research_%Y_%m_%d_%H%M%S.jsonl")
    target = path / filename
    records = [
        {"kind": "event", **_trace_value(event)}
        for event in events
    ]
    records.extend(
        {"kind": "audit", **_trace_value(entry)}
        for entry in state.audit_log
    )
    with target.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return target
