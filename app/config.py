"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    gemini_api_key: str = Field(default="")
    gemini_model: str = "gemini-2.0-flash"
    tavily_api_key: str = Field(default="")
    max_searches: int = Field(default=10, ge=1)
    max_sources: int = Field(default=15, ge=1)
    max_iterations: int = Field(default=5, ge=1)
    max_llm_requests: int = Field(default=10, ge=1)
    gemini_timeout: float = Field(default=60, gt=0)
    debug: bool = False
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    def validate_api_keys(self) -> None:
        missing = []
        if not self.tavily_api_key:
            missing.append("TAVILY_API_KEY")
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        if missing:
            raise ValueError(
                f"Missing {', '.join(missing)}. Create a .env file based on .env.example."
            )

    def validate_configuration(self) -> None:
        self.validate_api_keys()
        if not self.gemini_model.strip():
            raise ValueError(
                "GEMINI_MODEL is missing. Set it to a model available to your Google AI Studio project."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
