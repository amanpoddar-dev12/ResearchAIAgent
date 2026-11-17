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

## Answer-quality improvements

The answer checklist uses the existing planned sub-questions and evidence links. It is visible in the workspace scope details and in the executive summary. A row marked `supported findings` means that individual findings are supported; it is not a completeness or correctness verdict for the whole question. The user can refine scope through the existing follow-up research input.

Session diagnostics distinguish unsearched questions, missing retained sources, snippet-only access, incomplete extraction, inadmissible evidence, disagreement and missing corroboration. Discovery result counts, question-level diagnoses and final structural checks use the existing audit-log fields; no API or SSE shape changed. Synthesis-worker audit entries are merged only after worker completion, so failed or timed-out workers cannot mutate the live session.

Recovery variants depend on the observed gap and reuse existing query/iteration/time/call limits. They never loosen filters, add a provider or expand budgets. Existing DOI/domain grouping, source deduplication, matched comparison criteria, cell-level numerical provenance and citation checks remain in place. These mechanisms do not prove source independence or measurement comparability.

The writer/reviewer prompts now require relevance, scoped explanations and useful incomplete briefs. Raw `Finding.explanation` is never promoted to trusted report prose. Supported observations without a reviewed interpretation are disclosed. All existing report section IDs remain available to exports and navigation. Missing evidence produces a brief with reasons and next steps; it is not filled with invented background or recommendations.

Feedback adds `Too shallow`, `Missed my question`, `Weak sources` and `Unclear explanation` as reasons within the existing Missing information note. Research ID and section already link feedback to the report and its audit trace. Notes are stored using the existing workspace flow, not automatically emailed, used to train a model or fed back as truth.

### Local report checks

Run `python -m tools.evaluate_report_quality path/to/state.json` with a local **ResearchState JSON object**, including source content for verbatim checks. This is not the browser's saved-history wrapper. The command makes no network requests and does not alter the input. Missing full source text prevents evidence from counting; export the original state securely if conducting this evaluation. Output includes the checklist and structural rubric, with explicit human-review requirements and no aggregate accuracy score.

`tests/fixtures/research_quality_questions.json` supplies a fixed six-question manual evaluation set. Run baseline and revised versions with the same model, date, filters and budgets; preserve report, state, audit trace, elapsed time and cost. Have a reviewer assess exact-question relevance, citation entailment, primary-source quality, methods, number scope, clarity and completeness. Repeat runs to assess variance. Synthetic regression tests and passage-recall benchmarks cannot establish real-world user satisfaction or factual accuracy.

## Bounded pre-publication research recovery

For routed-model runs with more than one iteration and automatic additional research enabled, the coordinator reserves the final iteration for one pre-publication evidence-coverage assessment. The model uses the existing GapAssessment schema and routing to request at most three standalone searches tied to existing question IDs. The initial phase reserves one of the configured gap-assessment rounds for this check. Quick mode retains its single iteration, and the user-controlled checkpoint flow retains its existing collection decisions.

Recovery reuses the same sources, claim/evidence validation, filters and global counters. It never replans the question or resets searches, iterations, source limits, time or model usage. Duplicate/URL queries and unknown question IDs are rejected. Exhausted budgets, insufficient final-report capacity, plateaued evidence or an unavailable assessment lead to an explicit audit entry, not unlimited retries. A model returning no queries does not establish correctness or completeness.

After one resumed iteration, normal independent evidence review, report writing and block review run before publication. If recovery adds no admissible linked excerpts, the model-requested evidence gap remains explicitly unresolved in the report. New excerpts are not an accuracy verdict. There are no new providers, configuration fields, dependencies, endpoints or SSE event shapes. Small default call budgets can skip this phase; increasing them requires a separate cost/latency decision.

Run `python -m pytest -q tests/test_publication_quality.py` for budget, query-validation, failure, global-counter and end-to-end publication regressions. These use synthetic models and searches, not live accuracy measurements.

## Information-first reports

All modes except Fact Check may now produce an informational introduction in the existing synthesis call, even when no finding reaches Supported. The generated introduction is labeled general knowledge, is separate from verified research, and receives no research citations. Model-generated source links and citation tokens are removed from this background. The writer is instructed not to invent studies, current statistics, prices or recent events. This is a disclosure boundary, not a guarantee of factual accuracy.

Only a successful live synthesis sets the private background opt-in; imported/legacy unchecked prose cannot activate it. The private attribute is not a public API field and is not stored as a new state field. Generated report sections persist through the existing report storage. Fact Check retains evidence-only behavior. If the model is unavailable or its budget is exhausted, the app does not invent a replacement explanation. No extra model call is introduced.

## Runtime audit fixes

- Tight call budgets skip the separate question-analysis call. Extraction reserves one evaluation call and final writing/review capacity. Dedicated numerical extraction follows claim extraction and runs only with spare capacity and no already-extracted measurements. Larger budgets reserve three recovery calls during initial collection; final writing has up to 60 seconds or 40% of the remaining session time. No environment budgets or model names are changed.
- Finding explanations are retained as explicitly unreviewed AI explanations. Native report blocks and cited legacy paragraphs share semantic review; the approved executive-summary answer is used for the main-page preview. General background has a separate, non-conflicting prompt policy; it receives no research citations. Expansion requires spare review/repair capacity.
- Extraction is keyed by source and assigned question scope, with at most two attempts per scope. Successfully parsed empty results are not treated as completed evidence extraction. Rediscovered sources can be re-extracted for new assignments. Overflow candidates are queued within the bounded collection phase, with fresh targeted candidates taking precedence on ties. Global source/query/time caps still apply. Relevance uses the better original-question/search-query match and a bounded discovery-provider signal; it never establishes claim support. Packet caps prioritize evidence for retained high-importance claims.
- Search failures are distinguished from valid zero-result searches. Fetch failures, extraction/provider/schema failures and output truncation are exposed through sanitized audit details and existing gap events. Multi-part Gemini text is joined while thought parts are omitted. Reports disclose processing limitations; timeline completion is not presented as proof of successful verification.
- Public snapshots retain previously collected source text in browser state only for matching IDs and URLs within the current session. Q&A retrieval maps numbered report citations to canonical source IDs, carries bounded linked quotations, and uses a less restrictive conservative input budget. Ordinal follow-ups can focus retrieval on the corresponding numbered answer item.
- General Q&A still uses one streamed generation. Research/PDF answers receive one additional bounded review through the existing review provider before publication. This adds latency and a possible model call; it is not the old single-call research-chat behavior. Unsupported numerical text is removed before review; semantic review checks entailment, units, dates and scope. If review is unavailable, retrieved excerpts are offered as quotations rather than verified conclusions. Research answers stream in reviewed increments using unchanged SSE event shapes. Existing API fields and storage schemas are preserved.

Run `python -m pytest -q tests/test_audit_reliability_fixes.py tests/test_roadmap_regressions.py tests/test_hybrid_assistant.py` and the frontend reliability/timeline tests. These are offline regressions. Actual provider access, rate limits, real-report accuracy and perceived latency still require live evaluation; no new accuracy guarantee follows from passing them.

### Verification observations

A bounded live Quick research smoke test (two searches requested, four-source ceiling, one iteration, 60-second ceiling) completed in 28.7 seconds using eight model attempts: four retained sources, ten evidence records, two Supported findings and four reviewed report blocks. Its completion quality remained partial, so this is a functioning-pipeline check, not a completeness claim. Search-wave source balancing was subsequently covered by an offline regression to prevent one question from crowding out another.

Tiny connectivity probes succeeded for the configured planning, extraction and review providers. A live assistant smoke test against an explicitly synthetic research fixture returned the fixture's 10 USD value with its S1 citation and no review limitations. These observations establish access and basic end-to-end operation at test time, not broad factual accuracy, production deployment health or future quota availability.
