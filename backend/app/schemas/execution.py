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
