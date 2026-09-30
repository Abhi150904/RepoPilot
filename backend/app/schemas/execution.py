from __future__ import annotations

from pydantic import BaseModel, Field


class TestResult(BaseModel):
    passed: int = 0
    failed: int = 0
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    command: list[str] = Field(default_factory=list)
