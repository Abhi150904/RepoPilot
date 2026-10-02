from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TestResult(BaseModel):
    passed: int = 0
    failed: int = 0
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    command: list[str] = Field(default_factory=list)


class TestAnalysis(BaseModel):
    status: Literal["passed", "failed", "timed_out", "error"]
    summary: str
    failure_reason: str | None = None
    next_action: Literal["ready_for_review", "inspect_failure", "rerun_tests"]


class RepairDecision(BaseModel):
    should_retry: bool
    next_action: Literal["ready_for_review", "repair", "rerun_tests", "stop"]
    reason: str


class RepairContext(BaseModel):
    attempt: int
    test_status: Literal["failed", "timed_out", "error"]
    test_summary: str
    failure_reason: str | None = None
    previous_diff: str = ""


class ReviewFinding(BaseModel):
    severity: Literal["info", "warning", "error"]
    category: Literal[
        "correctness",
        "edge_cases",
        "error_handling",
        "security",
        "maintainability",
        "test_coverage",
    ]
    message: str
    path: str | None = None


class ReviewResult(BaseModel):
    approved: bool
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)
    next_action: Literal["await_human_approval", "repair", "needs_human"]


class RunSummary(BaseModel):
    status: Literal[
        "planned_only",
        "changes_proposed",
        "changes_applied",
        "ready_for_review",
        "awaiting_approval",
        "review_failed",
        "repair_needed",
        "repair_failed",
        "needs_human",
    ]
    summary: str
    tests_passed: bool | None = None
    repair_attempts: int = 0
    next_action: Literal[
        "review_plan",
        "review_diff",
        "commit_changes",
        "inspect_failure",
        "rerun_tests",
        "human_review",
    ]
