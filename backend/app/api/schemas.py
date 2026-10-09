from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: Literal["repopilot"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    service: Literal["repopilot"]
    environment: str
    hosted_mode: bool
    checks: dict[str, bool]
    warnings: list[str] = Field(default_factory=list)


class AuthUser(BaseModel):
    github_user_id: int
    login: str
    avatar_url: str | None = None
    name: str | None = None


class AuthMeResponse(BaseModel):
    authenticated: bool
    user: AuthUser | None = None
    csrf_token: str | None = None


class GitHubInstallationResponse(BaseModel):
    id: int
    account_login: str | None = None
    account_type: str | None = None


class GitHubRepositoryResponse(BaseModel):
    full_name: str
    installation_id: int
    default_branch: str | None = None
    private: bool | None = None


class GitHubRepositoriesResponse(BaseModel):
    repositories: list[GitHubRepositoryResponse]
    install_url: str | None = None


class RunRequest(BaseModel):
    issue: str | None = None
    repository: str | None = None
    issue_number: int | None = Field(default=None, ge=1)
    apply_changes: bool = False
    workspace_path: str | None = None
    run_tests: bool = False
    test_runner: Literal["docker", "local"] = "docker"
    test_command: list[str] | None = None
    max_repair_attempts: int = Field(default=1, ge=0)
    approved: bool = False
    publish_dry_run: bool = False
    publish_local: bool = False
    publish_push: bool = False
    publish_pr: bool = False

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Plan from issue text",
                    "value": {
                        "issue": "Login endpoint returns 500 when email is missing."
                    },
                },
                {
                    "summary": "Analyze a GitHub issue",
                    "value": {
                        "repository": "Abhi150904/Wandr",
                        "issue_number": 16,
                    },
                },
                {
                    "summary": "Apply changes and run tests for a GitHub issue",
                    "value": {
                        "repository": "Abhi150904/Wandr",
                        "issue_number": 16,
                        "apply_changes": True,
                        "run_tests": True,
                        "test_runner": "local",
                        "test_command": ["python", "-m", "pytest"],
                        "max_repair_attempts": 1,
                    },
                },
                {
                    "summary": "Approved PR publication flow",
                    "value": {
                        "repository": "Abhi150904/Wandr",
                        "issue_number": 16,
                        "apply_changes": True,
                        "run_tests": True,
                        "approved": True,
                        "publish_local": True,
                        "publish_push": True,
                        "publish_pr": True,
                    },
                },
            ]
        }
    }

    @field_validator("issue", "repository", "workspace_path")
    @classmethod
    def strip_blank_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value cannot be blank.")
        return stripped

    @field_validator("test_command")
    @classmethod
    def validate_test_command_tokens(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("test_command cannot be empty.")
        if any(not token.strip() for token in value):
            raise ValueError("test_command tokens cannot be blank.")
        return value

    @model_validator(mode="after")
    def validate_run_mode(self) -> RunRequest:
        github_fields = [self.repository is not None, self.issue_number is not None]
        github_mode = self.repository is not None and self.issue_number is not None
        publishing = self.publish_local or self.publish_push or self.publish_pr
        if any(github_fields) and not all(github_fields):
            raise ValueError("repository and issue_number must be provided together.")
        if self.issue is None and self.repository is None:
            raise ValueError("Either issue or repository and issue_number must be provided.")
        if self.issue is not None and self.repository is not None:
            raise ValueError("Use either issue text or GitHub issue mode, not both.")
        if (self.apply_changes or self.run_tests) and not github_mode and not self.workspace_path:
            raise ValueError("workspace_path is required for local apply_changes or run_tests.")
        if self.workspace_path and not (self.apply_changes or self.run_tests):
            raise ValueError("workspace_path can only be used with apply_changes or run_tests.")
        if self.test_command and not self.run_tests:
            raise ValueError("test_command can only be used with run_tests.")
        if self.publish_dry_run and not self.approved:
            raise ValueError("publish_dry_run requires approved=true.")
        if publishing and not self.approved:
            raise ValueError("publishing requires approved=true.")
        if self.publish_dry_run and (self.publish_local or self.publish_push or self.publish_pr):
            raise ValueError("publish_dry_run cannot be combined with publishing actions.")
        if (self.publish_dry_run or publishing) and not self.apply_changes:
            raise ValueError("publication requires apply_changes=true.")
        if (self.publish_dry_run or publishing) and not self.run_tests:
            raise ValueError("publication requires run_tests=true.")
        if self.publish_push and not self.publish_local:
            raise ValueError("publish_push requires publish_local=true.")
        if self.publish_pr and not self.publish_push:
            raise ValueError("publish_pr requires publish_push=true.")
        if self.publish_pr and self.repository is None:
            raise ValueError("publish_pr requires GitHub issue mode.")
        return self


class RunArtifacts(BaseModel):
    issue_url: str | None = None
    workspace_path: str | None = None
    branch_name: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    diff: str | None = None
    tests_passed: bool | None = None
    test_result: dict[str, Any] | None = None
    test_analysis: dict[str, Any] | None = None
    review_result: dict[str, Any] | None = None
    publication_package: dict[str, Any] | None = None
    publish_result: dict[str, Any] | None = None
    pr_url: str | None = None


class RunResponse(BaseModel):
    status: str
    next_action: str
    summary: str
    artifacts: RunArtifacts
    run_summary: dict[str, Any]
    result: dict[str, Any]


class RunError(BaseModel):
    code: str
    message: str
    type: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: RunError


class RunStatusResponse(BaseModel):
    run_id: str
    lifecycle_status: Literal["queued", "running", "completed", "failed", "interrupted"]
    publication_status: Literal["not_started", "ready", "publishing", "published", "failed"] = "not_started"
    created_at: datetime
    updated_at: datetime
    request: dict[str, Any]
    events: list[dict[str, Any]] = Field(default_factory=list)
    response: RunResponse | None = None
    error: RunError | None = None


class ApprovalRequest(BaseModel):
    note: str | None = None


class RejectRequest(BaseModel):
    reason: str | None = None


class PublishRequest(BaseModel):
    mode: Literal["dry_run", "local", "push", "pr"]


class MetricsResponse(BaseModel):
    metrics: dict[str, Any]


class EvaluationSuiteResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    eval_type: Literal["retrieval", "workflow"]
    version: str
    created_at: datetime


class EvaluationRunRequest(BaseModel):
    suite: str
    configuration: dict[str, Any] = Field(default_factory=dict)
    baseline_eval_run_id: str | None = None

    @field_validator("suite")
    @classmethod
    def validate_suite(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("suite cannot be blank.")
        return stripped


class EvaluationMetricResponse(BaseModel):
    metric_name: str
    metric_value: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationCaseResultResponse(BaseModel):
    id: int
    eval_run_id: str
    eval_case_id: int
    case_key: str
    status: Literal["passed", "failed", "error"]
    output: dict[str, Any] = Field(default_factory=dict)
    measurements: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    safe_error_message: str | None = None
    duration_ms: float | None = None
    created_at: datetime


class EvaluationRunResponse(BaseModel):
    id: str
    suite_id: int
    suite_name: str
    eval_type: Literal["retrieval", "workflow"]
    status: Literal["queued", "running", "completed", "failed", "interrupted"]
    configuration: dict[str, Any] = Field(default_factory=dict)
    metrics: list[EvaluationMetricResponse] = Field(default_factory=list)
    case_results: list[EvaluationCaseResultResponse] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    created_by: str | None = None
    error_type: str | None = None
    safe_error_message: str | None = None


class EvaluationComparisonMetric(BaseModel):
    metric_name: str
    baseline: float | None = None
    current: float | None = None
    delta: float | None = None
    direction: Literal["higher_is_better", "lower_is_better", "neutral"] = "neutral"


class EvaluationComparisonResponse(BaseModel):
    baseline_run_id: str
    current_run_id: str
    compatible: bool
    warning: str | None = None
    metrics: list[EvaluationComparisonMetric]
