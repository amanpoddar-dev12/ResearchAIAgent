from app.models import Finding, ResearchQuestion, ResearchState


def test_models_validate_and_serialize():
    state = ResearchState(question=ResearchQuestion(question="What changed?"))
    state.findings.append(Finding(
        claim="A documented change occurred", explanation="Source evidence",
        source_ids=["S1"], confidence=0.9, category="fact",
    ))
    assert state.model_dump()["question"]["question"] == "What changed?"

