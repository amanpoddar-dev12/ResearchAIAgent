# Research-quality evaluation

This upgrade keeps the existing providers, API/event shapes, global budgets, citation checks and numeric-provenance rules. It does not guarantee factual accuracy or exhaustiveness.

## What changed
- Paragraph-preserving HTML and bounded PDF fetching reuse the isolated parser, with public-IP/redirect checks, byte caps and a deadline. PDF extraction retains page labels. No OCR or paywall bypass is performed.
- Passage ranking searches the collected document instead of sending its opening characters only. Context stays bounded: 10,000 characters per source in evidence batches and 5,000 in the numerical pass. Documents are bounded to selected text; sources may still rely on snippets when full text is unavailable.
- Evidence packets organize validated quotations, claim status, counter-evidence, measurements and missing coverage by research sub-question. Detected reporting signals do not establish methodological validity; independent-origin counts remain conservative heuristics.
- The initial writer works from those packets. With spare calls it expands one weak analysis/discussion section, then reviews every publishable block. Rejected blocks can receive a single repair and a new review when at least two calls remain. Low budgets use the initial grouped draft; unreviewed prose stays excluded. No automatic budget increase.
- Audit entries show retrieval method/size, extraction coverage, proposed/approved/repaired blocks, final quality counts and stopping reasons. The report methodology distinguishes fetched-text sources from snippets.
- Follow-up priorities favor unanswered questions, important disagreements and primary evidence. Existing search/iteration/time caps still stop collection.

## Repeatable offline checks
Run `python -m tools.benchmark_research_quality` for eight fictional long-document cases comparing prefix-only retrieval with ranked passage recall. This measures known-passage retrieval, not live model performance or factual accuracy.
Run `python -m pytest -q tests/test_research_depth.py tests/test_report_readability.py tests/test_quantitative_research.py tests/test_security_audit.py` for packet isolation, bounded contexts, repair/review, numeric safeguards and secure fetching.

## Live report evaluation (manual, not executed by the offline benchmark)
Use a fixed set of questions covering technical implementation, a scientific review, a historical topic, conflicting studies, a comparison and an explicitly unanswerable topic. Fix source/date filters and record provider model, budgets, wall time and research date. Compare baseline and revised runs using the same settings; repeat to expose model variance.
For each run independently review: whether the answer addresses every question; whether citations support the exact assertion; exact numbers/units/population/timeframe; primary-source availability and full-text coverage; source independence; contradictions and uncertainty; useful non-repeated detail; elapsed time and token/call usage. Report unsupported statements explicitly rather than substituting word count or source count for quality. Distinguish model review from human verification.

## Operational limits
Default caps can leave little spare writing capacity. More sources or words alone are not a quality improvement. Raise deployment budgets only after reviewing measured calls/time/cost and rate limits; this change does not edit environment configuration or model selection. Scanned, encrypted, oversized and slow PDFs remain unavailable. Human verification is required for consequential conclusions.
