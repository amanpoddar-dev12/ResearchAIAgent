"""Provider-agnostic LLM contracts, errors, and structured-call compatibility."""

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMError(RuntimeError):
    """Base class for controlled model-service failures."""


class ModelConfigurationError(LLMError):
    """Required provider configuration is missing or invalid."""


class LLMRequestBudgetExceeded(LLMError):
    """The application-level model request budget has been exhausted."""


class ProviderError(LLMError):
    """A provider failure without exposing credentials or response secrets."""

    def __init__(self, provider: str, task: str, message: str, status_code: int | None = None):
        self.provider = provider
        self.task = task
        self.status_code = status_code
        suffix = f" (HTTP {status_code})" if status_code is not None else ""
        super().__init__(f"{provider} provider failed for {task}: {message}{suffix}")


class ProviderTimeoutError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderAuthError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    pass


class LLMClient(ABC):
    """Async provider contract consumed by research orchestration."""

    @property
    @abstractmethod
    def requests_used(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def max_requests(self) -> int:
        raise NotImplementedError

    @abstractmethod
    async def complete(self, messages: list[dict[str, str]], *, task: str,
                       response_model: type[ModelT] | None = None,
                       temperature: float = 0.2, max_tokens: int | None = None) -> ModelT | str:
        raise NotImplementedError

    def generate_text(self, prompt: str, *, task: str = "open_reasoning") -> str:
        from .sync import run_sync
        result = run_sync(self.complete([{"role": "user", "content": prompt}], task=task))
        return result if isinstance(result, str) else result.model_dump_json()

    def generate_structured(self, prompt: str, schema: type[ModelT], *, task: str = "open_reasoning") -> ModelT:
        from .sync import run_sync
        result = run_sync(self.complete([{"role": "user", "content": prompt}], task=task, response_model=schema))
        return result


def invoke_structured(client: Any, prompt: str, schema: type[ModelT], *, task: str) -> ModelT:
    """Call routed clients with task metadata while retaining old offline fakes."""
    try:
        return client.generate_structured(prompt, schema, task=task)
    except TypeError as exc:
        if "unexpected keyword argument 'task'" not in str(exc):
            raise
        return client.generate_structured(prompt, schema)
