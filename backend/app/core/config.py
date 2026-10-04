from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    llm_provider: str = Field(
        default="mock",
        validation_alias=AliasChoices(
            "REPO_PILOT_LLM_PROVIDER",
            "REPOPILOT_LLM_PROVIDER",
        ),
    )
    llm_model: str = Field(
        default="repopilot-mock-v0",
        validation_alias=AliasChoices(
            "REPO_PILOT_LLM_MODEL",
            "REPOPILOT_LLM_MODEL",
            "GEMINI_MODEL",
        ),
    )
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GEMINI_API_KEY",
            "REPO_PILOT_GEMINI_API_KEY",
            "REPOPILOT_GEMINI_API_KEY",
        ),
    )
    github_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GITHUB_TOKEN", "REPOPILOT_GITHUB_TOKEN"),
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="REPOPILOT_",
        extra="ignore",
        populate_by_name=True,
    )


def get_settings() -> Settings:
    return Settings()
