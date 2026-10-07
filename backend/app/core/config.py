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
    workspace_root: str = Field(
        default=".repopilot/workspaces",
        validation_alias=AliasChoices(
            "REPO_PILOT_WORKSPACE_ROOT",
            "REPOPILOT_WORKSPACE_ROOT",
        ),
    )
    default_test_command: str = Field(
        default="python -m pytest",
        validation_alias=AliasChoices(
            "REPO_PILOT_DEFAULT_TEST_COMMAND",
            "REPOPILOT_DEFAULT_TEST_COMMAND",
        ),
    )
    cors_origins: str = Field(
        default=(
            "http://localhost:3000,"
            "http://127.0.0.1:3000,"
            "http://localhost:3001,"
            "http://127.0.0.1:3001,"
            "http://localhost:5173,"
            "http://127.0.0.1:5173"
        ),
        validation_alias=AliasChoices(
            "REPO_PILOT_CORS_ORIGINS",
            "REPOPILOT_CORS_ORIGINS",
        ),
    )
    deployment_environment: str = Field(
        default="local",
        validation_alias=AliasChoices(
            "REPO_PILOT_DEPLOYMENT_ENVIRONMENT",
            "REPOPILOT_DEPLOYMENT_ENVIRONMENT",
        ),
    )
    hosted_mode: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "REPO_PILOT_HOSTED_MODE",
            "REPOPILOT_HOSTED_MODE",
        ),
    )
    public_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "REPO_PILOT_PUBLIC_BASE_URL",
            "REPOPILOT_PUBLIC_BASE_URL",
        ),
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="REPOPILOT_",
        extra="ignore",
        populate_by_name=True,
    )


def get_settings() -> Settings:
    return Settings()


def deployment_warnings(settings: Settings) -> list[str]:
    warnings: list[str] = []
    if settings.hosted_mode and settings.github_token:
        warnings.append("Hosted mode should use GitHub App/OAuth instead of a personal GitHub token.")
    if settings.hosted_mode and not settings.public_base_url:
        warnings.append("Hosted mode should set REPO_PILOT_PUBLIC_BASE_URL.")
    if "*" in _cors_origins(settings.cors_origins):
        warnings.append("Wildcard CORS origins are not recommended outside local development.")
    return warnings


def deployment_issues(settings: Settings) -> list[str]:
    issues: list[str] = []
    if settings.hosted_mode and settings.github_token:
        issues.append("REPO_PILOT_HOSTED_MODE=true cannot be used with a personal GitHub token.")
    if settings.hosted_mode and "*" in _cors_origins(settings.cors_origins):
        issues.append("REPO_PILOT_CORS_ORIGINS cannot include * in hosted mode.")
    return issues


def readiness_report(settings: Settings) -> dict[str, object]:
    checks = {
        "cors_configured": bool(_cors_origins(settings.cors_origins)),
        "llm_provider_configured": bool(settings.llm_provider),
        "workspace_root_configured": bool(settings.workspace_root),
    }
    warnings = deployment_warnings(settings)
    issues = deployment_issues(settings)
    ready = all(checks.values()) and not issues
    return {
        "status": "ready" if ready else "degraded",
        "service": "repopilot",
        "environment": settings.deployment_environment,
        "hosted_mode": settings.hosted_mode,
        "checks": checks,
        "warnings": warnings,
    }


def _cors_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]
