"""Command-line entry point."""

import argparse
import logging
import sys
from rich.console import Console
from rich.progress import Progress
from app.agent import ResearchAgent
from app.config import Settings
from app.reporter import save_report


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Research Agent")
    parser.add_argument("question", nargs="?", help="Research question")
    parser.add_argument("--max-searches", type=int)
    parser.add_argument("--max-sources", type=int)
    parser.add_argument("--max-iterations", type=int)
    parser.add_argument("--check-config", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if args.check_config:
        try:
            settings.validate_configuration()
            print(f"Configuration valid. Routed models configured (Gemini: {settings.gemini_model}, Groq: {settings.groq_model}, Mistral: {settings.mistral_model}). Tavily configured: yes.")
            return 0
        except ValueError as exc:
            print(f"Configuration error: {exc}")
            return 1
    question = args.question or input("What would you like me to research?\n> ").strip()
    if not question:
        print("A research question is required.")
        return 2
    for name in ("max_searches", "max_sources", "max_iterations"):
        value = getattr(args, name)
        if value is not None:
            setattr(settings, name, value)
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO, format="%(levelname)s %(message)s")
    console = Console()
    try:
        with Progress(console=console) as progress:
            console.print(f"AI RESEARCH AGENT\nLLM: routed Gemini/Groq/Mistral\nPrimary model: {settings.gemini_model}\nResearch question: {question}\n")
            task = progress.add_task("Planning...", total=None)
            state = ResearchAgent(settings).run(question)
            progress.update(task, description=f"Research complete: {state.searches_performed} searches, {len(state.sources)} sources")
        report_path = save_report(state.final_report or "")
        console.print(f"\nSaved report to {report_path}\n")
        console.print(state.final_report or "No report generated.")
        return 0
    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]ERROR:[/red] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
