from app.models import ResearchQuestion, ResearchPlan, ResearchState
from app.researcher import Researcher


class FakeLLM:
    def generate_structured(self, prompt, schema):
        if "Assess research coverage" in prompt:
            return {"gaps": [], "follow_up_queries": []}
        return []


def test_researcher_deduplicates_and_respects_search_limit(monkeypatch):
    monkeypatch.setattr("app.researcher.search_web", lambda *args, **kwargs: [
        {"title": "One", "url": "https://example.com/a", "content": "evidence", "source_domain": "example.com"},
        {"title": "Duplicate", "url": "https://example.com/a", "content": "evidence", "source_domain": "example.com"},
    ])
    class FakeExtractor:
        def extract(self, question, source):
            return []
    researcher = Researcher(FakeLLM(), "key", 1, 10, 1)
    researcher.extractor = FakeExtractor()
    state = ResearchState(
        question=ResearchQuestion(question="Question"),
        plan=ResearchPlan(objective="x", search_queries=["q"], research_areas=[]),
    )
    # Search results are normally SearchResult models; this test targets the loop budget.
    monkeypatch.setattr("app.researcher.search_web", lambda *args, **kwargs: [])
    result = researcher.run(state)
    assert result.searches_performed == 1

