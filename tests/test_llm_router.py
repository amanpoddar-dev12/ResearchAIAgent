import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.llm import (
    LLMRequestBudgetExceeded, LLMRouter, ProviderAuthError, ProviderResponseError, ProviderTimeoutError,
)
from app.llm.routing import FINAL_REVIEW, PLANNING
from app.llm.providers import GroqProvider, MistralProvider
from app.planner import Planner
from app.models import ResearchPlan, ResearchQuestion


class Result(BaseModel):
    value: str


def settings(**changes):
    values = dict(
        _env_file=None,
        gemini_api_key="gemini-key", gemini_model="gemini-free",
        groq_api_key="groq-key", groq_model="groq-free",
        mistral_api_key="mistral-key", mistral_model="mistral-free",
        tavily_api_key="tavily-key", llm_timeout_seconds=1, llm_max_retries=2,
    )
    values.update(changes)
    return Settings(**values)


class Response:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


def chat_payload(text):
    return {"choices": [{"message": {"content": text}}]}


def test_tasks_route_to_exactly_one_provider(monkeypatch):
    router = LLMRouter(settings())
    calls = []

    async def complete(messages, **kwargs):
        calls.append(kwargs["task"])
        return "{}"

    for name, provider in router.providers.items():
        monkeypatch.setattr(provider, "complete", complete)
    asyncio.run(router.complete([{"role": "user", "content": "x"}], task=PLANNING))
    asyncio.run(router.complete([{"role": "user", "content": "x"}], task=FINAL_REVIEW))
    assert calls == [PLANNING, FINAL_REVIEW]
    assert router.providers["gemini"].provider == "gemini"


def test_timeout_raises_typed_error(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: (_ for _ in ()).throw(httpx.TimeoutException("slow")))
    router = LLMRouter(settings(llm_max_retries=0))
    with pytest.raises(ProviderTimeoutError) as error:
        asyncio.run(router.complete([{"role": "user", "content": "x"}], task=PLANNING))
    assert error.value.provider == "gemini"
    assert error.value.task == PLANNING


def test_retry_then_success(monkeypatch):
    calls = 0
    def request(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.TimeoutException("temporary")
        return Response(payload=chat_payload('{"value":"ok"}'))
    monkeypatch.setattr(httpx, "post", request)
    router = LLMRouter(settings())
    async def no_wait(_seconds):
        return None
    monkeypatch.setattr("app.llm.providers.asyncio.sleep", no_wait)
    result = asyncio.run(router.complete([{"role": "user", "content": "x"}], task=PLANNING, response_model=Result))
    assert result.value == "ok"
    assert router.requests_used == 2


def test_429_honors_retry_after(monkeypatch):
    responses = iter([Response(429, {}, {"Retry-After": "3"}), Response(payload=chat_payload("done"))])
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: next(responses))
    waits = []

    async def no_wait(seconds):
        waits.append(seconds)

    monkeypatch.setattr("app.llm.providers.asyncio.sleep", no_wait)
    router = LLMRouter(settings())
    result = asyncio.run(router.complete([{"role": "user", "content": "x"}], task=PLANNING))
    assert result == "done"
    assert waits == [3.0]


def test_auth_error_is_not_retried(monkeypatch):
    calls = 0

    def unauthorized(*args, **kwargs):
        nonlocal calls
        calls += 1
        return Response(401, {})

    monkeypatch.setattr(httpx, "post", unauthorized)
    router = LLMRouter(settings())
    with pytest.raises(ProviderAuthError):
        asyncio.run(router.complete([{"role": "user", "content": "x"}], task=PLANNING))
    assert calls == 1


def test_invalid_json_is_repaired_once(monkeypatch):
    responses = iter([Response(payload=chat_payload("not json")), Response(payload=chat_payload('{"value":"fixed"}'))])
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: next(responses))
    router = LLMRouter(settings())
    result = asyncio.run(router.complete(
        [{"role": "user", "content": "x"}], task=PLANNING, response_model=Result,
    ))
    assert result.value == "fixed"
    assert router.requests_used == 2


def test_concurrent_requests_cannot_overspend_budget(monkeypatch):
    router = LLMRouter(settings(max_llm_requests=1))

    async def complete(*args, **kwargs):
        await asyncio.sleep(0)
        return '{"value":"ok"}'

    for provider in router.providers.values():
        monkeypatch.setattr(provider, "complete", complete)

    async def run():
        results = await asyncio.gather(
            router.complete([{"role": "user", "content": "x"}], task=PLANNING, response_model=Result),
            router.complete([{"role": "user", "content": "y"}], task=PLANNING, response_model=Result),
            return_exceptions=True,
        )
        return results

    results = asyncio.run(run())
    assert sum(isinstance(result, Result) for result in results) == 1
    assert router.requests_used == 1


def test_repair_requires_a_remaining_request_budget(monkeypatch):
    router = LLMRouter(settings(max_llm_requests=1))
    async def malformed(*args, **kwargs):
        return "not json"

    monkeypatch.setattr(router.providers["gemini"], "complete", malformed)
    with pytest.raises(LLMRequestBudgetExceeded) as error:
        asyncio.run(router.complete(
            [{"role": "user", "content": "x"}], task=PLANNING, response_model=Result,
        ))
    assert "request budget" in str(error.value).lower()
    assert router.requests_used == 1


def test_repair_failure_raises_provider_response_error(monkeypatch):
    responses = iter([Response(payload=chat_payload("bad")), Response(payload=chat_payload("still bad"))])
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: next(responses))
    with pytest.raises(ProviderResponseError) as error:
        asyncio.run(LLMRouter(settings()).complete(
            [{"role": "user", "content": "x"}], task=PLANNING, response_model=Result,
        ))
    assert error.value.provider == "gemini"
    assert error.value.task == PLANNING


def test_missing_environment_configuration_names_variables():
    config = Settings(_env_file=None)
    with pytest.raises(ValueError) as error:
        config.validate_configuration()
    message = str(error.value)
    for name in ("GEMINI_API_KEY", "GEMINI_MODEL", "GROQ_API_KEY", "GROQ_MODEL",
                 "MISTRAL_API_KEY", "MISTRAL_MODEL", "TAVILY_API_KEY",
                 "LLM_TIMEOUT_SECONDS", "LLM_MAX_RETRIES"):
        assert name in message


@pytest.mark.parametrize(
    ("provider_type", "model"),
    [(GroqProvider, "configured-groq-model"), (MistralProvider, "configured-mistral-model")],
)
def test_openai_compatible_provider_sends_exact_model_and_api_key(monkeypatch, provider_type, model):
    captured = {}

    def fake_post(endpoint, headers, json, timeout):
        captured.update(endpoint=endpoint, headers=headers, payload=json, timeout=timeout)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    provider_type("secret-key", model, 10, 0)._request([{"role": "user", "content": "ping"}], 0, None)
    assert captured["payload"]["model"] == model
    assert captured["headers"]["Authorization"] == "Bearer secret-key"


def test_planner_passes_routing_task_not_prompt_text():
    calls = []

    class PlannerLLM:
        def generate_structured(self, prompt, schema, *, task):
            calls.append(task)
            return ResearchPlan(objective="x", search_queries=["q"])

    Planner(PlannerLLM()).create_plan(ResearchQuestion(question="A research question"))
    assert calls == ["planning"]
