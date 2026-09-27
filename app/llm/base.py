"""Provider-independent LLM contracts and request budgeting."""

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMError(RuntimeError):
    """A controlled model-service failure."""


class ModelConfigurationError(LLMError):
    """The configured model or credentials cannot be used."""


class LLMRequestBudgetExceeded(LLMError):
    """The application-level Gemini request budget has been exhausted."""


class LLMClient(ABC):
    """Interface consumed by research orchestration components."""

    @property
    @abstractmethod
    def requests_used(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def max_requests(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def generate_text(self, prompt: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate_structured(self, prompt: str, schema: Any) -> ModelT:
        raise NotImplementedError
