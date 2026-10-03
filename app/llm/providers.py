"""HTTP adapters for Gemini, Groq, and Mistral chat APIs."""

import asyncio
import json
import logging
import random
import threading
from typing import Any

import httpx

from .base import (
    ProviderAuthError, ProviderRateLimitError, ProviderResponseError,
    ProviderTimeoutError,
)

logger = logging.getLogger(__name__)


class HTTPProvider:
    provider = ""
    endpoint = ""

    def __init__(self, api_key: str, model: str, timeout: float, max_retries: int):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.before_retry = lambda task: None
        self.remaining_time = lambda: float("inf")
        self.record_usage = lambda task, values: None
        self._local = threading.local()

    def _request_for_task(self, task, messages, temperature, max_tokens):
        self._local.task = task
        return self._request(messages, temperature, max_tokens)

    def _request(self, messages: list[dict[str, str]], temperature: float, max_tokens: int | None) -> tuple[str, int | None]:
        raise NotImplementedError

    async def complete(self, messages: list[dict[str, str]], *, task: str,
                       temperature: float, max_tokens: int | None) -> str:
        for attempt in range(self.max_retries + 1):
            if attempt:
                self.before_retry(task)
            remaining = min(self.timeout, self.remaining_time())
            if remaining <= 0:
                raise ProviderTimeoutError(self.provider, task, "session deadline reached")
            try:
                text, status = await asyncio.wait_for(
                    asyncio.to_thread(self._request_for_task, task, messages, temperature, max_tokens),
                    timeout=remaining,
                )
                return text
            except (httpx.TimeoutException, TimeoutError) as exc:
                if attempt >= self.max_retries:
                    raise ProviderTimeoutError(self.provider, task, "request timed out") from exc
                await asyncio.sleep(min(self._backoff(attempt), self.remaining_time()))
            except ProviderRateLimitError as exc:
                if exc.task != task:
                    wrapped = ProviderRateLimitError(exc.provider, task, "rate limit reached", exc.status_code)
                    wrapped.retry_after = getattr(exc, "retry_after", None)
                    exc = wrapped
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(min(self._retry_after(exc, attempt), self.remaining_time()))
            except ProviderTimeoutError as original:
                exc = ProviderTimeoutError(self.provider, task, "request timed out")
                if attempt >= self.max_retries:
                    raise exc from original
                await asyncio.sleep(min(self._backoff(attempt), self.remaining_time()))
            except ProviderResponseError as exc:
                if exc.task != task:
                    exc = ProviderResponseError(exc.provider, task, "provider request failed", exc.status_code)
                if (exc.status_code is None or exc.status_code >= 500) and attempt < self.max_retries:
                    await asyncio.sleep(min(self._backoff(attempt), self.remaining_time()))
                    continue
                raise
            except ProviderAuthError:
                raise
        raise ProviderResponseError(self.provider, task, "request failed")

    def _backoff(self, attempt: int) -> float:
        return min(8.0, (2 ** attempt) + random.uniform(0, 0.25))

    def _retry_after(self, error: ProviderRateLimitError, attempt: int) -> float:
        retry_after = getattr(error, "retry_after", None)
        try:
            return max(0, min(60, float(retry_after))) if retry_after is not None else self._backoff(attempt)
        except (TypeError, ValueError):
            return self._backoff(attempt)

    def _post_json(self, headers: dict[str, str], payload: dict[str, Any]) -> tuple[str, int | None]:
        try:
            response = httpx.post(self.endpoint, headers=headers, json=payload, timeout=min(self.timeout, self.remaining_time()))
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(self.provider, "http_request", "request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderResponseError(self.provider, "http_request", "network request failed") from exc
        status = response.status_code
        if status in {401, 403}:
            raise ProviderAuthError(self.provider, "http_request", "authentication failed", status)
        if status == 429:
            error = ProviderRateLimitError(self.provider, "http_request", "rate limit reached", status)
            error.retry_after = response.headers.get("Retry-After")
            raise error
        if status >= 500:
            raise ProviderResponseError(self.provider, "http_request", "provider temporarily unavailable", status)
        if status >= 400:
            raise ProviderResponseError(self.provider, "http_request", "provider rejected the request", status)
        try:
            data = response.json()
            self.record_usage(getattr(self._local, "task", "unknown"), data.get("usage") or data.get("usageMetadata"))
            return self._extract_text(data), status
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderResponseError(self.provider, "http_request", "provider returned invalid JSON", status) from exc

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        choices = data.get("choices")
        if choices and choices[0].get("message", {}).get("content"):
            return str(choices[0]["message"]["content"])
        candidates = data.get("candidates")
        if candidates and candidates[0].get("content", {}).get("parts"):
            return str(candidates[0]["content"]["parts"][0].get("text", ""))
        raise ValueError("missing response text")


class GeminiProvider(HTTPProvider):
    provider = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float, max_retries: int):
        super().__init__(api_key, model, timeout, max_retries)
        self.endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def _request(self, messages, temperature, max_tokens):
        contents = [{"role": "model" if item["role"] == "assistant" else "user", "parts": [{"text": item["content"]}]} for item in messages if item["role"] != "system"]
        payload: dict[str, Any] = {"contents": contents, "generationConfig": {"temperature": temperature}}
        instructions = [item["content"] for item in messages if item["role"] == "system"]
        if instructions:
            payload["systemInstruction"] = {"parts": [{"text": "\n".join(instructions)}]}
        if max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens
        return self._post_json({"Content-Type": "application/json", "x-goog-api-key": self.api_key}, payload)


class OpenAICompatibleProvider(HTTPProvider):
    def _request(self, messages, temperature, max_tokens):
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": temperature}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return self._post_json({"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, payload)


class GroqProvider(OpenAICompatibleProvider):
    provider = "groq"
    endpoint = "https://api.groq.com/openai/v1/chat/completions"


class MistralProvider(OpenAICompatibleProvider):
    provider = "mistral"
    endpoint = "https://api.mistral.ai/v1/chat/completions"
