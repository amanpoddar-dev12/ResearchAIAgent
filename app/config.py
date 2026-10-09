"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="")
    groq_api_key: str = Field(default="")
    groq_model: str = Field(default="")
    groq_review_model: str = Field(default="qwen/qwen3.8-27b")
    tavily_api_key: str = Field(default="")
    max_searches: int = Field(default=10, ge=1)
    max_sources: int = Field(default=15, ge=1)
    max_iterations: int = Field(default=5, ge=1)
    max_llm_requests: int = Field(default=10, ge=1)
    max_parallel_tasks: int = Field(default=3, ge=1, le=8)
    max_wall_seconds: float = Field(default=180, gt=0, le=3600)
    llm_timeout_seconds: float | None = Field(default=None, gt=0)
    llm_max_retries: int | None = Field(default=None, ge=0, le=5)
    additional_research_rounds: int = Field(default=2, ge=0, le=5)
    debug: bool = False
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    def validate_api_keys(self) -> None:
        missing = []
        for name, value in (
            ("GEMINI_API_KEY", self.gemini_api_key), ("GEMINI_MODEL", self.gemini_model),
            ("GROQ_API_KEY", self.groq_api_key), ("GROQ_MODEL", self.groq_model),
            ("GROQ_REVIEW_MODEL", self.groq_review_model),
            ("TAVILY_API_KEY", self.tavily_api_key),
            ("LLM_TIMEOUT_SECONDS", self.llm_timeout_seconds), ("LLM_MAX_RETRIES", self.llm_max_retries),
        ):
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(name)
        if missing:
            raise ValueError(
                f"Missing {', '.join(missing)}. Create a .env file based on .env.example."
            )

    def validate_configuration(self) -> None:
        self.validate_api_keys()
        if self.llm_timeout_seconds is None or self.llm_timeout_seconds <= 0:
            raise ValueError("LLM_TIMEOUT_SECONDS must be greater than zero.")
        if self.llm_max_retries is None:
            raise ValueError("LLM_MAX_RETRIES is missing.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
