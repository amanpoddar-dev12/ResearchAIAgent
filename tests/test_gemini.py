import json

import pytest

from app.llm import GeminiClient, LLMRequestBudgetExceeded, ModelConfigurationError
from app.models import ClaimExtraction


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    def __init__(self, responses):
        self.responses = iter(responses)

    def generate_content(self, **_kwargs):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)

    def get(self, **_kwargs):
        return object()


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)


def test_gemini_requires_key_and_model():
    with pytest.raises(ModelConfigurationError):
        GeminiClient("model", "")
    with pytest.raises(ModelConfigurationError):
        GeminiClient("", "key")


def test_structured_response_is_validated_and_budgeted():
    client = GeminiClient(
        "model", "key", max_requests=1,
        client=FakeClient([json.dumps({"gaps": [], "follow_up_queries": []})]),
    )
    result = client.generate_structured(
        "prompt",
        type("Schema", (), {
            "validate_python": staticmethod(
                lambda value: value
            )
        }),
    )
    assert result["gaps"] == []
    with pytest.raises(LLMRequestBudgetExceeded):
        client.generate_text("second")


def test_malformed_structured_response_retries_once():
    client = GeminiClient(
        "model", "key", max_requests=2,
        client=FakeClient(["not json", json.dumps({"ok": True})]),
    )
    result = client.generate_structured(
        "prompt",
        type("Schema", (), {
            "validate_python": staticmethod(
                lambda value: value
            )
        }),
    )
    assert result == {"ok": True}


def test_structured_schema_is_a_sdk_compatible_pydantic_model():
    client = GeminiClient(
        "model", "key",
        client=FakeClient([json.dumps({"findings": []})]),
    )
    result = client.generate_structured("prompt", ClaimExtraction)
    assert result.findings == []
