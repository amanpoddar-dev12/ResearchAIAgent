"""Compatibility name for the routed client and legacy offline test doubles."""

import json
from typing import Any

from pydantic import BaseModel

from app.config import Settings
from .base import LLMRequestBudgetExceeded, ModelConfigurationError
from .router import LLMRouter


class GeminiClient:
    """Use LLMRouter in production; retain the old constructor for offline tests."""

    def __new__(cls, settings_or_model: Settings | str, api_key: str | None = None,
                max_requests: int = 10, timeout: float = 60, client: Any | None = None):
        if isinstance(settings_or_model, Settings):
            return LLMRouter(settings_or_model, max_requests=max_requests)
        if not settings_or_model:
            raise ModelConfigurationError("GEMINI_MODEL is missing.")
        if not api_key:
            raise ModelConfigurationError("GEMINI_API_KEY is missing.")
        return _LegacyOfflineClient(settings_or_model, max_requests=max_requests, client=client)


class _LegacyOfflineClient:
    def __init__(self, model_name: str, max_requests: int, client: Any | None):
        self.model_name = model_name
        self._max_requests = max_requests
        self._requests_used = 0
        self.client = client

    @property
    def requests_used(self) -> int:
        return self._requests_used

    @property
    def max_requests(self) -> int:
        return self._max_requests

    def _response(self) -> str:
        if self._requests_used >= self._max_requests:
            raise LLMRequestBudgetExceeded("LLM request budget reached.")
        self._requests_used += 1
        response = self.client.models.generate_content()
        return response.text

    def generate_text(self, prompt: str, **_kwargs) -> str:
        return self._response().strip()

    def generate_structured(self, prompt: str, schema: Any, **_kwargs):
        text = self._response()
        for candidate in (text.strip(), text.replace("```json", "").replace("```", "").strip()):
            try:
                data = json.loads(candidate)
                if hasattr(schema, "model_validate"):
                    return schema.model_validate(data)
                if hasattr(schema, "validate_python"):
                    return schema.validate_python(data)
                return data
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        repair = self._response()
        data = json.loads(repair)
        if hasattr(schema, "model_validate"):
            return schema.model_validate(data)
        return schema.validate_python(data)
