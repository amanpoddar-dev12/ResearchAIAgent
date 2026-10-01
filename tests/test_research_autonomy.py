"""Offline synthetic autonomy regressions; these fixtures are not real research."""
import asyncio
import json
import threading
import time
import pytest
from app.agent import ResearchAgent
from app.models import (BudgetOverrides, ClaimExtraction, Evidence, Finding, ResearchPlan,
    ResearchQuestion, ResearchState, SubQuestion, ReportDraft)
from app.evidence import validate_evidence, merge_extraction, evidence_conflicts
from app.deduplication import near_duplicate
from app.planner import refine_question
from app.research_control import decide_stop
from app.researcher import Researcher
from app.synthesizer import render_report
from tools.web_search import normalize_url
from tests.research_fakes import SyntheticLLM, synthetic_search, synthetic_settings, SYNTHETIC_TEXT
from tests.test_research_features import synthetic_source


def decision(**changes):
    values = dict(coverage=.5, unresolved=["Synthetic open question"], gains=[1], searches=1,
        sources=1, iterations=1, elapsed=1, max_searches=10, max_sources=10,
        max_iterations=10, max_wall_seconds=30, plateau_window=2)
    values.update(changes)
    return decide_stop(**values)


def test_pure_stopping_coverage_plateau_and_unresolved():
    assert decision(coverage=1, unresolved=[]).reason == "Evidence coverage reached"
    assert decision(gains=[1, 0, 0]).reason == "New-evidence gain plateau"
    assert not decision(coverage=1).stop
    assert not decision(gains=[0, 1, 0]).stop
    gaps = ["Synthetic open question"]
    result = decision(unresolved=gaps)
    result.unresolved.append("Mutated return")
    assert gaps == ["Synthetic open question"]


@pytest.mark.parametrize("field,value,reason", [("searches", 10, "search"), ("sources", 10, "source"),
    ("iterations", 10, "iteration"), ("elapsed", 30, "wall-clock")])
def test_each_budget_stops(field, value, reason):
    result = decision(**{field: value})
    assert result.stop and result.reason == reason + " budget exhausted"
    assert result.unresolved


def finding(key, relation="supports", dependencies=None):
    return Finding(id=key, claim=f"SYNTHETIC TEST claim {key}", explanation="Fictional test fixture",
        confidence=.5, category="fact", source_ids=["S1"], evidence_ids=["E" + key[1:]], depends_on=dependencies or [])


def evidence(key, relation="supports"):
    return Evidence(id=key, source_id="S1", excerpt=SYNTHETIC_TEXT, relation=relation, strength="direct")


def state_with_claims(claims, items):
    return ResearchState(question=ResearchQuestion(question="Test widget"), sources=[synthetic_source()],
        findings=claims, evidence=items, provenance_required=True, retrieved_urls=[synthetic_source().url])


@pytest.mark.parametrize("relation,status", [("contradicts", "Contradicted"), ("context", "Unverified")])
def test_dependencies_propagate_transitively(relation, status):
    state = state_with_claims([finding("C3", dependencies=["C2"]), finding("C2", dependencies=["C1"]), finding("C1")],
        [evidence("E1", relation), evidence("E2"), evidence("E3")])
    validate_evidence(state)
    assert [claim.evidence_status for claim in state.findings] == ["Unverified", "Unverified", status]


def test_cycles_and_unknown_dependencies_are_rejected():
    state = state_with_claims([finding("C1", dependencies=["C2"]), finding("C2", dependencies=["C1"]), finding("C3", dependencies=["missing"])],
        [evidence("E1"), evidence("E2"), evidence("E3")])
    validate_evidence(state)
    assert all(claim.dependency_rejected and not claim.depends_on and claim.evidence_status == "Unverified" for claim in state.findings)
    validate_evidence(state)  # Revalidation must not upgrade rejected cyclic claims.
    assert all(claim.evidence_status == "Unverified" for claim in state.findings)
    assert {item.reason for item in state.citation_rejections} >= {"Dependency cycle rejected", "Unknown claim dependency"}


def test_contradiction_has_graph_edges_and_graph_is_a_projection():
    state = state_with_claims([finding("C1")], [evidence("E1", "contradicts")])
    validate_evidence(state)
    state.conflicts = evidence_conflicts(state)
    graph = state.model_dump(mode="json")["graph"]
    assert state.findings[0].evidence_status == "Contradicted"
    assert {node["type"] for node in graph["nodes"]} == {"question", "claim", "evidence", "source", "conflict"}
    assert {"source": "S1", "target": "X1", "type": "conflicts"} in graph["edges"]
    assert {"source": "C1", "target": "X1", "type": "contradiction"} in graph["edges"]
    assert "graph" not in state.__dict__
    state.findings[0].claim = "Changed synthetic claim"
    assert next(node for node in state.graph["nodes"] if node["id"] == "C1")["label"] == "Changed synthetic claim"
    assert json.loads(state.model_dump_json())["graph"] == state.graph


def test_url_and_conservative_content_normalization():
    assert normalize_url("https://www.example.test/a/?utm_source=x&fbclid=y&b=2&a=1#fragment") == "https://example.test/a?a=1&b=2"
    assert normalize_url("https://example.test/") == normalize_url("https://www.example.test")
    text = "SYNTHETIC TEST DATA " + " ".join(f"word{i}" for i in range(30))
    assert near_duplicate(text, text + " ending")
    assert not near_duplicate("The synthetic widget is safe", "The synthetic widget is not safe", claim=True)
    assert not near_duplicate("Synthetic speed 10", "Synthetic speed 11", claim=True)
    assert not near_duplicate("Alpha synthetic widget", "Beta synthetic widget", claim=True)


def test_claim_merging_preserves_all_evidence_and_dependencies():
    state = state_with_claims([], [])
    source2 = synthetic_source(id="S2", url="https://second.example.test/docs")
    state.sources.append(source2)
    state.retrieved_urls.append(source2.url)
    first = finding("old")
    first.claim, first.evidence_ids = "The synthetic widget operates", ["first"]
    merge_extraction(state, ClaimExtraction(findings=[first], evidence=[evidence("first")]))
    second = finding("new")
    second.claim, second.evidence_ids, second.source_ids = "Synthetic widget operates", ["second"], ["S2"]
    next_claim = finding("dependent")
    next_claim.evidence_ids, next_claim.depends_on = ["second"], ["new"]
    item = evidence("second").model_copy(update={"source_id": "S2"})
    merge_extraction(state, ClaimExtraction(findings=[second, next_claim], evidence=[item]))
    assert len(state.findings) == 2
    assert set(state.findings[0].source_ids) == {"S1", "S2"}
    assert len(state.findings[0].evidence_ids) == 2
    assert state.findings[1].depends_on == ["C1"]
    assert state.merge_records[-1]["kind"] == "claim"


def test_unretrieved_source_and_fabricated_excerpt_rejected_and_audited():
    state = state_with_claims([finding("C1")], [evidence("E1")])
    state.retrieved_urls = []
    validate_evidence(state)
    assert state.findings[0].evidence_status == "Unverified" and not state.evidence
    assert any("not retrieved" in entry.message for entry in state.audit_log)
    state = state_with_claims([finding("C1")], [evidence("E1").model_copy(update={"excerpt": "FABRICATED TEXT"})])
    validate_evidence(state)
    assert not state.evidence
    assert any("not present" in entry.message for entry in state.audit_log)


def test_refinement_preserves_original_and_declares_assumptions():
    question = ResearchQuestion(question="Best widget today?")
    refine_question(question)
    assert question.question == "Best widget today?"
    assert question.refined_question.startswith(question.question)
    assert question.ambiguities and question.assumptions
    assert any("universal winner" in item for item in question.assumptions)


def test_parallel_ready_waves_deterministic_commits_and_dependencies(monkeypatch):
    barrier = threading.Barrier(2)
    completed, starts, events, emitter_threads = [], [], [], []
    lock = threading.Lock()
    def search(_key, query, **kwargs):
        with lock:
            starts.append(query)
        if query in {"Test widget A", "Test widget B"}:
            barrier.wait(timeout=2)  # Fails if independent tasks are executed serially.
            if query.endswith("A"):
                time.sleep(.02)  # Completion order differs from coordinator order.
        else:
            assert set(completed) >= {"Test widget A", "Test widget B"}
        with lock:
            completed.append(query)
        return synthetic_search()
    monkeypatch.setattr("app.researcher.search_web", search)
    tasks = [SubQuestion(id="Q1", question="Test widget A", query="Test widget A"),
        SubQuestion(id="Q2", question="Test widget B", query="Test widget B"),
        SubQuestion(id="Q3", question="Test widget C", query="Test widget C", depends_on=["Q1", "Q2"])]
    state = ResearchState(question=ResearchQuestion(question="Test widget"), plan=ResearchPlan(objective="SYNTHETIC TEST", sub_question_tasks=tasks), mode="quick", max_parallel_tasks=2)
    def emit(kind, message, data=None):
        events.append((kind, data))
        emitter_threads.append(threading.get_ident())
    Researcher(SyntheticLLM(), "synthetic-not-a-key", 3, 10, 1).run(state, emit)
    assert starts[:2] == ["Test widget A", "Test widget B"]
    assert [data["query"] for kind, data in events if kind == "search_completed"] == [task.query for task in tasks]
    assert set(emitter_threads) == {threading.get_ident()}
    assert state.searched_sub_questions == ["Q1", "Q2", "Q3"]
    assert len(state.sources) == 1 and len(state.merge_records) == 2
    progress = [data["progress"] for kind, data in events if kind == "research_progress"]
    assert progress == sorted(progress)


def test_parallel_limit_one_and_cyclic_tasks_never_dispatched(monkeypatch):
    active, peak, calls = 0, 0, []
    lock = threading.Lock()
    def search(_key, query, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            calls.append(query)
        time.sleep(.005)
        with lock:
            active -= 1
        return synthetic_search()
    monkeypatch.setattr("app.researcher.search_web", search)
    tasks = [SubQuestion(id="Q1", question="Test widget A", query="Test widget A"), SubQuestion(id="Q2", question="Test widget B", query="Test widget B"),
        SubQuestion(id="Q3", question="Cyclic", query="must not run", depends_on=["Q3"])]
    state = ResearchState(question=ResearchQuestion(question="Test widget"), plan=ResearchPlan(objective="SYNTHETIC", sub_question_tasks=tasks), mode="quick", max_parallel_tasks=1)
    Researcher(SyntheticLLM(), "synthetic-not-a-key", 3, 10, 1).run(state)
    assert peak == 1 and calls == ["Test widget A", "Test widget B"]
    assert any(entry.action == "dependency_rejected" for entry in state.audit_log)
    assert any("Q3" in question for question in state.unresolved_questions)


def test_expansion_only_targets_measured_gaps_and_logs_each_iteration(monkeypatch):
    calls = []
    monkeypatch.setattr("app.researcher.search_web", lambda _key, query, **kwargs: calls.append(query) or [])
    state = ResearchState(question=ResearchQuestion(question="Test widget"), mode="deep",
        plan=ResearchPlan(objective="SYNTHETIC", search_queries=["Test widget evidence"]),
        budget_overrides=BudgetOverrides(max_searches=3, max_iterations=3))
    Researcher(SyntheticLLM(), "synthetic-not-a-key", 10, 10, 5).run(state)
    assert len(calls) == 3 and calls[1] == "Test widget evidence primary source evidence"
    assert len(state.stop_decisions) == 3 and state.stop_decisions[-1].stop
    expansions = [entry for entry in state.audit_log if entry.action == "expansion"]
    assert expansions and all("no verified evidence" in entry.details["reason"] for entry in expansions)
    assert state.unresolved_questions


def test_wall_clock_returns_report_and_discards_late_worker_results(monkeypatch):
    release, finished = threading.Event(), threading.Event()
    class SlowPlannerLLM(SyntheticLLM):
        def generate_structured(self, prompt, schema):
            if schema is ResearchPlan:
                release.wait(timeout=1)
                finished.set()
            return super().generate_structured(prompt, schema)
    monkeypatch.setattr("app.agent.GeminiClient", SlowPlannerLLM)
    monkeypatch.setattr("app.researcher.search_web", lambda *args, **kwargs: pytest.fail("No search may start after deadline"))
    agent = ResearchAgent(synthetic_settings())
    state = agent.run("Test widget", budgets=BudgetOverrides(max_wall_seconds=.02))
    assert state.status == "complete" and "wall-clock budget exhausted" in state.final_report
    assert state.unresolved_questions and not state.sources
    assert state.searches_performed == 0 and state.iteration == 0
    serialized = state.model_dump_json()
    release.set()
    assert finished.wait(timeout=1)
    assert state.model_dump_json() == serialized


def test_strict_report_does_not_publish_free_form_fabrication():
    state = state_with_claims([], [])
    draft = ReportDraft(title="Fabricated", executive_summary="FAKE UNTRACEABLE RESULT https://invented.example.test/ [S404]", key_findings=["FAKE RESULT"], conclusion="")
    report = render_report(draft, state)
    assert "FAKE" not in report and "invented.example.test" not in report
    assert "Unverified" in report
    assert any(entry.action == "rejection" for entry in state.audit_log)


@pytest.mark.parametrize("mode", ["quick", "academic"])
def test_additive_sse_snapshots_budgets_and_graph_match_final_result(monkeypatch, mode):
    from server.api import research
    from server.api.models import ResearchRequest
    monkeypatch.setattr("app.agent.GeminiClient", SyntheticLLM)
    monkeypatch.setattr("app.researcher.search_web", synthetic_search)
    monkeypatch.setattr(research, "Settings", synthetic_settings)
    async def run():
        identifier = await research.start_research(ResearchRequest(question="Test widget", mode=mode,
            budgets=BudgetOverrides(max_searches=2, max_iterations=2, max_parallel_tasks=1, max_wall_seconds=10)))
        events = [json.loads(chunk[6:]) async for chunk in research.stream_research(identifier)]
        final = events[-1]["data"]["state"]
        snapshots = [event["data"] for event in events if event["type"] == "research_snapshot"]
        assert snapshots[-1] == final
        assert final["max_searches"] == 2 and final["max_parallel_tasks"] == 1
        assert final["max_wall_seconds"] == 10 and final["stop_decisions"][-1]["stop"]
        assert final["graph"]["nodes"] and final["audit_log"]
        assert all("content" not in source for snapshot in snapshots for source in snapshot["sources"])
        assert all(entry["timestamp"] for entry in final["audit_log"])
        assert [event["progress"] for event in events] == sorted(event["progress"] for event in events)
        assert events[-1]["type"] == "complete" and events[-1]["progress"] == 100
        research.jobs.pop(identifier)
    asyncio.run(run())

def test_near_duplicate_content_is_merged_in_pipeline(monkeypatch):
    original = synthetic_search()[0]
    duplicate = original.model_copy(update={"url": "https://mirror.example.test/docs/widgets", "content": original.content + " Appendix."})
    monkeypatch.setattr("app.researcher.search_web", lambda *args, **kwargs: [original, duplicate])
    state = ResearchState(question=ResearchQuestion(question="Test widget"), mode="quick", plan=ResearchPlan(objective="SYNTHETIC", search_queries=["Test widget"]))
    Researcher(SyntheticLLM(), "synthetic-not-a-key", 3, 10, 1).run(state)
    assert len(state.sources) == 1
    assert {state.sources[0].url, *state.sources[0].aliases} == {original.url, duplicate.url}
    assert set(state.retrieved_urls) == {original.url, duplicate.url}
    assert any(entry.action == "source_deduplicated" for entry in state.audit_log)


def test_explicit_subquestion_coverage_does_not_inherit_unrelated_source_queries():
    from app.research_control import coverage_gaps
    state = state_with_claims([finding("C1")], [evidence("E1")])
    state.plan = ResearchPlan(objective="SYNTHETIC", sub_question_tasks=[SubQuestion(id="Q1", question="Test widget speed", query="speed"), SubQuestion(id="Q2", question="Test widget safety", query="safety")])
    state.explicit_sub_question_links = True
    state.sources[0].sub_question_ids = ["Q1", "Q2"]
    state.findings[0].sub_question_ids = ["Q1", "Q404"]
    validate_evidence(state)
    coverage, gaps = coverage_gaps(state)
    assert coverage == .5 and state.findings[0].sub_question_ids == ["Q1"]
    assert any("Q2" in reason for _, reason, _ in gaps)


def test_claim_with_invented_url_cannot_be_supported():
    state = state_with_claims([finding("C1")], [evidence("E1")])
    state.findings[0].claim = "SYNTHETIC TEST widget is documented at https://invented.example.test/fake"
    validate_evidence(state)
    assert state.findings[0].evidence_status == "Unverified"
    assert not state.evidence and any("untraceable URL" in item.reason for item in state.citation_rejections)
