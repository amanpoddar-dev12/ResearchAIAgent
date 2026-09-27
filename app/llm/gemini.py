"""Google Gemini implementation using the official google-genai SDK."""

import json
import logging
import time
from typing import Any, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from .base import LLMClient, LLMError, LLMRequestBudgetExceeded, ModelConfigurationError

logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


class GeminiClient(LLMClient):
    def __init__(
        self,
        model_name: str,
        api_key: str,
        max_requests: int = 10,
        timeout: float = 60.0,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ModelConfigurationError("GEMINI_API_KEY is missing.")
        if not model_name:
            raise ModelConfigurationError(
                "GEMINI_MODEL is missing. Set it to a model available to your Google AI Studio project."
            )
        self.model_name = model_name
        self._max_requests = max_requests
        self._requests_used = 0
        self.timeout = timeout
        self.client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        )

    @property
    def requests_used(self) -> int:
        return self._requests_used

    @property
    def max_requests(self) -> int:
        return self._max_requests

    def _reserve(self) -> None:
        if self._requests_used >= self._max_requests:
            raise LLMRequestBudgetExceeded(
                "Gemini request budget reached; continuing with collected evidence."
            )
        self._requests_used += 1

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        if status in {401, 403, 400}:
            return False
        text = str(exc).lower()
        return status in {408, 429, 500, 502, 503, 504} or any(
            marker in text for marker in ("timeout", "temporarily", "rate limit", "unavailable")
        )

    def _request(self, call: Any) -> Any:
        self._reserve()
        for attempt in range(3):
            try:
                return call()
            except Exception as exc:
                if not self._is_retryable(exc) or attempt == 2:
                    logger.error("Gemini request failed (%s)", type(exc).__name__)
                    raise LLMError(
                        "Gemini API request failed. Check your API key, model, quota, and network."
                    ) from exc
                time.sleep(2**attempt)
        raise LLMError("Gemini request failed.")

    def validate_model_access(self) -> None:
        try:
            self.client.models.get(model=self.model_name)
        except Exception as exc:
            logger.error("Configured Gemini model is unavailable: %s", type(exc).__name__)
            raise ModelConfigurationError(
                "Configured Gemini model is unavailable. Check GEMINI_MODEL and your Google AI Studio project."
            ) from exc

    @staticmethod
    def _parse_structured(text: str, schema: Any) -> ModelT:
        candidates = [text.strip()]
        if "```" in text:
            candidates.append(text.replace("```json", "").replace("```", "").strip())
        for candidate in candidates:
            try:
                data = json.loads(candidate)
                if hasattr(schema, "model_validate"):
                    return schema.model_validate(data)
                return schema.validate_python(data)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        raise ValueError("Gemini returned malformed structured data.")

    def generate_text(self, prompt: str) -> str:
        response = self._request(
            lambda: self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
        )
        text = getattr(response, "text", None)
        if not text:
            raise LLMError("Gemini returned an empty response.")
        return text.strip()

    def generate_structured(self, prompt: str, schema: Any) -> ModelT:
        response = self._request(
            lambda: self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
        )
        text = getattr(response, "text", None)
        if not text:
            raise ValueError("Gemini returned an empty structured response.")
        try:
            return self._parse_structured(text, schema)
        except ValueError:
            logger.error("Gemini structured response failed validation.")
            retry_prompt = f"{prompt}\nReturn only valid JSON matching the requested schema."
            response = self._request(
                lambda: self.client.models.generate_content(
                    model=self.model_name,
                    contents=retry_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema,
                    ),
                )
            )
            retry_text = getattr(response, "text", None)
            if not retry_text:
                raise ValueError("Gemini returned an empty corrected structured response.")
            return self._parse_structured(retry_text, schema)

    async def agenerate_text(self, prompt: str) -> str:
        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )
        text = getattr(response, "text", None)
        if not text:
            raise LLMError("Gemini returned an empty response.")
        return text.strip()
