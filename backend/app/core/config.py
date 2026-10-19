from __future__ import annotations

from pydantic import AliasChoices, Field, field_validator
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
        default="gpt-5.4-mini",
        validation_alias=AliasChoices(
            "REPO_PILOT_LLM_MODEL",
            "REPOPILOT_LLM_MODEL",
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
        default=60_000,
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
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OPENAI_API_KEY",
            "REPO_PILOT_OPENAI_API_KEY",
            "REPOPILOT_OPENAI_API_KEY",
        ),
    )
    llm_budget_usd: float = Field(default=5.0, gt=0, allow_inf_nan=False)
    llm_run_budget_usd: float = Field(default=0.50, gt=0, allow_inf_nan=False)
    llm_budget_path: str = ".repopilot/openai-budget.sqlite"
    user_max_active_runs: int = Field(default=1, ge=1)
    user_max_daily_runs: int = Field(default=5, ge=1)
    staging_github_user_ids: str = ""
    sandbox_image: str = "python:3.11-slim"
    sandbox_docker_host: str | None = None
    azure_runner_enabled: bool = False
    azure_runner_resource_id: str | None = None
    azure_runner_idle_seconds: int = Field(default=600, ge=60)
    azure_runner_boot_timeout_seconds: int = Field(default=600, ge=30, le=1800)
    azure_runner_lock_path: str = "/opt/repopilot/data/runner-controller.lock"

    @field_validator("sandbox_docker_host")
    @classmethod
    def validate_sandbox_host(cls, value: str | None) -> str | None:
        if value is not None:
            from urllib.parse import urlsplit

            parsed = urlsplit(value)
            if (parsed.scheme != "ssh" or not parsed.hostname or not parsed.username
                    or parsed.password or parsed.path or parsed.query or parsed.fragment):
                raise ValueError("Sandbox Docker host must be ssh://user@host[:port].")
        return value

    @field_validator("staging_github_user_ids")
    @classmethod
    def validate_staging_users(cls, value: str) -> str:
        ids = [item.strip() for item in value.split(",") if item.strip()]
        if any(not item.isascii() or not item.isdigit() or int(item) <= 0 for item in ids):
            raise ValueError("Staging access requires comma-separated positive GitHub user IDs.")
        return ",".join(str(int(item)) for item in ids)
    github_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GITHUB_TOKEN", "REPOPILOT_GITHUB_TOKEN"),
    )
    github_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GITHUB_CLIENT_ID",
            "REPO_PILOT_GITHUB_CLIENT_ID",
            "REPOPILOT_GITHUB_CLIENT_ID",
        ),
    )
    github_client_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GITHUB_CLIENT_SECRET",
            "REPO_PILOT_GITHUB_CLIENT_SECRET",
            "REPOPILOT_GITHUB_CLIENT_SECRET",
        ),
    )
    github_oauth_callback_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GITHUB_OAUTH_CALLBACK_URL",
            "REPO_PILOT_GITHUB_OAUTH_CALLBACK_URL",
            "REPOPILOT_GITHUB_OAUTH_CALLBACK_URL",
        ),
    )
    github_app_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GITHUB_APP_ID",
            "REPO_PILOT_GITHUB_APP_ID",
            "REPOPILOT_GITHUB_APP_ID",
        ),
    )
    github_app_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GITHUB_APP_NAME",
            "REPO_PILOT_GITHUB_APP_NAME",
            "REPOPILOT_GITHUB_APP_NAME",
        ),
    )
    github_app_private_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GITHUB_APP_PRIVATE_KEY",
            "REPO_PILOT_GITHUB_APP_PRIVATE_KEY",
            "REPOPILOT_GITHUB_APP_PRIVATE_KEY",
        ),
    )
    github_webhook_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GITHUB_WEBHOOK_SECRET",
            "REPO_PILOT_GITHUB_WEBHOOK_SECRET",
            "REPOPILOT_GITHUB_WEBHOOK_SECRET",
        ),
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
    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "REPO_PILOT_DATABASE_URL",
            "REPOPILOT_DATABASE_URL",
            "DATABASE_URL",
        ),
    )
    inline_run_execution: bool | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "REPO_PILOT_INLINE_RUN_EXECUTION",
            "REPOPILOT_INLINE_RUN_EXECUTION",
            "REPO_PILOT_INLINE_WORKER",
            "REPOPILOT_INLINE_WORKER",
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
    if settings.hosted_mode and not (settings.github_client_id and settings.github_client_secret):
        warnings.append("Hosted mode should configure GitHub OAuth client credentials.")
    if settings.hosted_mode and not (settings.github_app_id and settings.github_app_private_key):
        warnings.append("Hosted mode should configure GitHub App credentials.")
    if settings.hosted_mode and settings.database_url:
        warnings.append(
            "Hosted mode requires a separate worker process for queued runs: repopilot worker run."
        )
    if settings.hosted_mode and inline_run_execution_enabled(settings):
        warnings.append("Inline run execution is enabled in hosted mode; use a worker process instead.")
    if "*" in _cors_origins(settings.cors_origins):
        warnings.append("Wildcard CORS origins are not recommended outside local development.")
    return warnings


def deployment_issues(settings: Settings) -> list[str]:
    issues: list[str] = []
    if getattr(settings, "azure_runner_enabled", False):
        from app.services.runner_lifecycle import valid_vm_resource_id

        if not valid_vm_resource_id(settings.azure_runner_resource_id):
            issues.append("Azure runner automation requires a valid runner VM resource ID.")
        if not settings.sandbox_docker_host or not settings.database_url:
            issues.append("Azure runner automation requires a remote SSH sandbox and durable database.")
        if inline_run_execution_enabled(settings):
            issues.append("Azure runner automation requires a separate worker; inline execution must be disabled.")
    if settings.deployment_environment == "production":
        if not settings.hosted_mode:
            issues.append("Production requires hosted mode.")
        if not settings.sandbox_docker_host:
            issues.append("Production requires an isolated SSH sandbox Docker host.")
        if inline_run_execution_enabled(settings):
            issues.append("Production requires a separate worker; inline execution must be disabled.")
        if not settings.public_base_url or not settings.public_base_url.startswith("https://"):
            issues.append("Production requires an HTTPS public frontend URL.")
        if not settings.github_oauth_callback_url or not settings.github_oauth_callback_url.startswith("https://"):
            issues.append("Production requires an HTTPS GitHub OAuth callback URL.")
    if settings.deployment_environment == "staging":
        if not settings.hosted_mode:
            issues.append("Staging requires hosted mode.")
        if not settings.staging_github_user_ids:
            issues.append("REPOPILOT_STAGING_GITHUB_USER_IDS is required for restricted staging access.")
        if not settings.public_base_url or not settings.public_base_url.startswith("https://"):
            issues.append("Staging requires an HTTPS public frontend URL.")
        if not settings.github_oauth_callback_url or not settings.github_oauth_callback_url.startswith("https://"):
            issues.append("Staging requires an HTTPS GitHub OAuth callback URL.")
        if inline_run_execution_enabled(settings):
            issues.append("Staging requires a separate worker; inline execution must be disabled.")
    if settings.hosted_mode and settings.github_token:
        issues.append("REPO_PILOT_HOSTED_MODE=true cannot be used with a personal GitHub token.")
    if settings.hosted_mode and "*" in _cors_origins(settings.cors_origins):
        issues.append("REPO_PILOT_CORS_ORIGINS cannot include * in hosted mode.")
    if settings.hosted_mode and not (settings.github_client_id and settings.github_client_secret):
        issues.append("GitHub OAuth client credentials are required in hosted mode.")
    if settings.hosted_mode and not (settings.github_app_id and settings.github_app_private_key):
        issues.append("GitHub App credentials are required in hosted mode.")
    if settings.hosted_mode and not settings.database_url:
        issues.append("REPOPILOT_DATABASE_URL is required in hosted mode for durable runs.")
    return issues


def readiness_report(settings: Settings) -> dict[str, object]:
    database_configured = bool(settings.database_url) if settings.hosted_mode else True
    checks = {
        "cors_configured": bool(_cors_origins(settings.cors_origins)),
        "llm_provider_configured": (
            settings.llm_provider.lower() == "mock"
            or (settings.llm_provider.lower() == "openai" and bool(settings.openai_api_key))
        ),
        "workspace_root_configured": bool(settings.workspace_root),
        "database_configured": database_configured,
        "worker_queue_configured": database_configured,
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


def inline_run_execution_enabled(settings: Settings) -> bool:
    inline_setting = getattr(settings, "inline_run_execution", None)
    if inline_setting is not None:
        return bool(inline_setting)
    return not settings.hosted_mode


def staging_user_allowed(settings: Settings, github_user_id: int) -> bool:
    return settings.deployment_environment != "staging" or str(github_user_id) in settings.staging_github_user_ids.split(",")


def _cors_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]
