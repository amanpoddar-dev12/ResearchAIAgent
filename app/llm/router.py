"""Provider router with retries and Pydantic structured-output validation."""

import asyncio
import json
import re
import threading
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings
from .base import (
    LLMClient, LLMRequestBudgetExceeded, ModelConfigurationError,
    ProviderResponseError,
)
from .providers import GeminiProvider, GroqProvider
from .routing import TASK_PROVIDER, REVIEW_TASKS

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMRouter(LLMClient):
    supports_task_routing = True

    def __init__(self, settings: Settings, max_requests: int | None = None):
        self.settings = settings
        self._max_requests = max_requests or settings.max_llm_requests
        self._requests_used = 0
        self._request_lock = threading.Lock()
        timeout = settings.llm_timeout_seconds or 60
        retries = settings.llm_max_retries if settings.llm_max_retries is not None else 2
        self.providers = {
            "gemini": GeminiProvider(settings.gemini_api_key, settings.gemini_model, timeout, retries),
            "groq": GroqProvider(settings.groq_api_key, settings.groq_model, timeout, retries),
        }
        self.review_provider = GroqProvider(settings.groq_api_key, settings.groq_review_model, timeout, retries)
        self.model_name = settings.gemini_model
        self.deadline: float | None = None
        self.cancelled = threading.Event()
        self.reserved_final_calls = 0
        self.usage: dict[str, dict] = {}
        for provider in [*self.providers.values(), self.review_provider]:
            provider.before_retry = self._reserve_attempt
            provider.remaining_time = self.remaining_time
            provider.record_usage = self._record_usage

    def remaining_time(self):
        if self.cancelled.is_set():
            raise LLMRequestBudgetExceeded("Research session cancelled")
        return max(0, self.deadline - time.monotonic()) if self.deadline else float("inf")

    def _record_usage(self, task, values):
        with self._request_lock:
            entry = self.usage.setdefault(task, {"attempts": 0, "input_tokens": 0, "output_tokens": 0, "usage_reported": False})
            if values:
                entry["usage_reported"] = True
                entry["input_tokens"] += values.get("prompt_tokens", values.get("promptTokenCount", 0)) or 0
                entry["output_tokens"] += values.get("completion_tokens", values.get("candidatesTokenCount", 0)) or 0

    @property
    def requests_used(self) -> int:
        return self._requests_used

    @property
    def max_requests(self) -> int:
        return self._max_requests

    async def complete(self, messages, *, task, response_model=None, temperature=0.2, max_tokens=None):
        if self.remaining_time() <= 0:
            raise LLMRequestBudgetExceeded("Session wall-clock budget exhausted")
        provider_name = TASK_PROVIDER[task]
        provider = self.review_provider if task in REVIEW_TASKS else self.providers[provider_name]
        if response_model is not None:
            messages = [*messages, {"role": "user", "content": "Return only JSON conforming exactly to this schema:\n" + json.dumps(response_model.model_json_schema())}]
        if max_tokens is None:
            max_tokens = 8000 if task == "final_synthesis" else 5000 if task in {"evidence_extraction", "source_extraction", "final_review"} else 3000
        await self._reserve_request(task)
        text = await provider.complete(messages, task=task, temperature=temperature, max_tokens=max_tokens)
        if response_model is None:
            return text.strip()
        try:
            return self._parse(text, response_model)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as first_error:
            await self._reserve_request(task)
            repair = [{"role": "system", "content": "Return only valid JSON matching the requested schema."},
                      {"role": "user", "content": f"Repair this response. Validation error: {first_error}\nPrevious response:\n{text}"}]
            try:
                repaired = await provider.complete(messages + repair, task=task, temperature=temperature, max_tokens=max_tokens)
                return self._parse(repaired, response_model)
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as second_error:
                # Validation errors include model values, which may contain private evidence.
                raise ProviderResponseError(provider_name, task, "structured response validation failed") from None

    async def _reserve_request(self, task="unknown") -> None:
        self._reserve_attempt(task)

    def _reserve_attempt(self, task):
        with self._request_lock:
            if self.remaining_time() <= 0:
                raise LLMRequestBudgetExceeded("Session wall-clock budget exhausted")
            reserve = 0 if task in {"final_synthesis", "final_review"} else min(2, self.reserved_final_calls) if task in {"evidence_evaluation", "independent_review"} else self.reserved_final_calls
            if task not in {"final_synthesis", "final_review"}:
                reserve += getattr(self, "recovery_reserve", 0)
            if self._requests_used >= self._max_requests - reserve:
                raise LLMRequestBudgetExceeded("LLM request budget reached; continuing with collected evidence.")
            self._requests_used += 1
            entry = self.usage.setdefault(task, {"attempts": 0, "input_tokens": 0, "output_tokens": 0, "usage_reported": False})
            entry["attempts"] += 1

    @staticmethod
    def _parse(text: str, schema: type[ModelT]) -> ModelT:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
        return schema.model_validate_json(cleaned)

    def validate_model_access(self) -> None:
        return None
