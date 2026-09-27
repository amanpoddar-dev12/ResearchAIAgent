"""Markdown report persistence."""

from datetime import datetime
from pathlib import Path
from app.models import ResearchState


def save_report(report: str, directory: str = "reports") -> Path:
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    filename = datetime.now().strftime("research_%Y_%m_%d_%H%M%S.md")
    target = path / filename
    target.write_text(report, encoding="utf-8")
    return target

