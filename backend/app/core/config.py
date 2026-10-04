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
    analyzer_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "REPO_PILOT_ANALYZER_MODEL",
            "REPOPILOT_ANALYZER_MODEL",
        ),
    )
    planner_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "REPO_PILOT_PLANNER_MODEL",
            "REPOPILOT_PLANNER_MODEL",
        ),
    )
    coder_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "REPO_PILOT_CODER_MODEL",
            "REPOPILOT_CODER_MODEL",
        ),
    )
    reviewer_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "REPO_PILOT_REVIEWER_MODEL",
            "REPOPILOT_REVIEWER_MODEL",
        ),
    )
    llm_max_output_tokens: int = Field(
        default=8192,
        validation_alias=AliasChoices(
            "REPO_PILOT_LLM_MAX_OUTPUT_TOKENS",
            "REPOPILOT_LLM_MAX_OUTPUT_TOKENS",
        ),
    )
    llm_max_prompt_chars: int = Field(
        default=120_000,
        validation_alias=AliasChoices(
            "REPO_PILOT_LLM_MAX_PROMPT_CHARS",
            "REPOPILOT_LLM_MAX_PROMPT_CHARS",
        ),
    )
    llm_max_retries: int = Field(
        default=2,
        validation_alias=AliasChoices(
            "REPO_PILOT_LLM_MAX_RETRIES",
            "REPOPILOT_LLM_MAX_RETRIES",
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
