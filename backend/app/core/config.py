from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    llm_provider: str = "mock"
    llm_model: str = "repopilot-mock-v0"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="REPOPILOT_",
        extra="ignore",
    )


def get_settings() -> Settings:
    return Settings()

