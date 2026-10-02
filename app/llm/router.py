"""Provider router with retries and Pydantic structured-output validation."""

import asyncio
import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings
from .base import (
    LLMClient, LLMRequestBudgetExceeded, ModelConfigurationError,
    ProviderResponseError,
)
from .providers import GeminiProvider, GroqProvider, MistralProvider
from .routing import TASK_PROVIDER

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMRouter(LLMClient):
    supports_task_routing = True

    def __init__(self, settings: Settings, max_requests: int | None = None):
        self.settings = settings
        self._max_requests = max_requests or settings.max_llm_requests
        self._requests_used = 0
        timeout, retries = settings.llm_timeout_seconds or 60, settings.llm_max_retries or 2
        self.providers = {
            "gemini": GeminiProvider(settings.gemini_api_key, settings.gemini_model, timeout, retries),
            "groq": GroqProvider(settings.groq_api_key, settings.groq_model, timeout, retries),
            "mistral": MistralProvider(settings.mistral_api_key, settings.mistral_model, timeout, retries),
        }
        self.model_name = settings.gemini_model
        self.deadline: float | None = None

    @property
    def requests_used(self) -> int:
        return self._requests_used

    @property
    def max_requests(self) -> int:
        return self._max_requests

    async def complete(self, messages, *, task, response_model=None, temperature=0.2, max_tokens=None):
        if self.deadline is not None and asyncio.get_running_loop().time() >= self.deadline:
            raise LLMRequestBudgetExceeded("Session wall-clock budget exhausted")
        if self._requests_used >= self._max_requests:
            raise LLMRequestBudgetExceeded("LLM request budget reached; continuing with collected evidence.")
        provider_name = TASK_PROVIDER[task]
        provider = self.providers[provider_name]
        self._requests_used += 1
        text = await provider.complete(messages, task=task, temperature=temperature, max_tokens=max_tokens)
        if response_model is None:
            return text.strip()
        try:
            return self._parse(text, response_model)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as first_error:
            repair = [{"role": "system", "content": "Return only valid JSON matching the requested schema."},
                      {"role": "user", "content": f"Repair the previous response. Validation error: {first_error}"}]
            try:
                repaired = await provider.complete(messages + repair, task=task, temperature=temperature, max_tokens=max_tokens)
                return self._parse(repaired, response_model)
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as second_error:
                raise ProviderResponseError(provider_name, task, f"structured response validation failed: {second_error}") from second_error

    @staticmethod
    def _parse(text: str, schema: type[ModelT]) -> ModelT:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
        return schema.model_validate_json(cleaned)

    def validate_model_access(self) -> None:
        return None
