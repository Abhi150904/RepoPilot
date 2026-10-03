from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class EvalExpectations(BaseModel):
    final_status: str | None = None
    tests_passed: bool | None = None
    touched_files: list[str] = Field(default_factory=list)
    forbidden_files: list[str] = Field(default_factory=list)


class EvalCase(BaseModel):
    id: str
    issue: str
    workspace_path: str | None = None
    copy_workspace: bool = False
    target_paths: list[str] = Field(default_factory=list)
    apply_changes: bool = False
    run_tests: bool = False
    test_runner: Literal["docker", "local"] = "docker"
    test_command: list[str] | None = None
    approved: bool = False
    expectations: EvalExpectations = Field(default_factory=EvalExpectations)


class EvalCheck(BaseModel):
    name: str
    passed: bool
    message: str


class EvalCaseResult(BaseModel):
    id: str
    status: Literal["passed", "failed"]
    checks: list[EvalCheck]


class EvalSuiteResult(BaseModel):
    total: int
    passed: int
    failed: int
    cases: list[EvalCaseResult]


def resolve_workspace_path(case: EvalCase, case_file: Path) -> str | None:
    if case.workspace_path is None:
        return None
    path = Path(case.workspace_path)
    if path.is_absolute():
        return str(path)
    return str((case_file.parent / path).resolve())
