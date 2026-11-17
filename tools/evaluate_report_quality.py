"""Inspect a local ResearchState JSON export without network or LLM calls.

Usage: python -m tools.evaluate_report_quality path/to/state.json
"""
import argparse
import json
from pathlib import Path
from app.models import ResearchState
from app.research_quality import report_usefulness, research_diagnosis


def evaluate(state: ResearchState) -> dict:
    return {'diagnosis': research_diagnosis(state), 'usefulness': report_usefulness(state)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state', type=Path, help='ResearchState JSON; not the browser history wrapper')
    args = parser.parse_args()
    try:
        state = ResearchState.model_validate_json(args.state.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        parser.exit(2, 'Could not read a valid ResearchState JSON file. No data was uploaded.\n')
    print(json.dumps(evaluate(state), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
