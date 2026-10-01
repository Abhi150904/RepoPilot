from __future__ import annotations

from app.agents.test_analyzer import TestAnalyzer
from app.schemas.execution import TestResult as ExecutionResult


def test_test_analyzer_marks_success_ready_for_review() -> None:
    result = ExecutionResult(
        exit_code=0,
        passed=4,
        failed=0,
        stdout="===== 4 passed in 0.20s =====",
        command=["python", "-m", "pytest"],
    )

    analysis = TestAnalyzer().analyze(result)

    assert analysis.status == "passed"
    assert analysis.next_action == "ready_for_review"
    assert "4 test" in analysis.summary
    assert analysis.failure_reason is None


def test_test_analyzer_marks_pytest_failure_for_inspection() -> None:
    result = ExecutionResult(
        exit_code=1,
        passed=2,
        failed=1,
        stdout="FAILED tests/test_login.py::test_missing_email",
        command=["python", "-m", "pytest"],
    )

    analysis = TestAnalyzer().analyze(result)

    assert analysis.status == "failed"
    assert analysis.next_action == "inspect_failure"
    assert "1 failing" in analysis.summary
    assert analysis.failure_reason == "FAILED tests/test_login.py::test_missing_email"


def test_test_analyzer_marks_timeout_for_inspection() -> None:
    result = ExecutionResult(
        exit_code=124,
        timed_out=True,
        command=["python", "-m", "pytest"],
    )

    analysis = TestAnalyzer().analyze(result)

    assert analysis.status == "timed_out"
    assert analysis.next_action == "inspect_failure"
    assert "timeout" in analysis.failure_reason


def test_test_analyzer_marks_non_pytest_error_for_rerun() -> None:
    result = ExecutionResult(
        exit_code=127,
        stderr="python: command not found",
        command=["python", "-m", "pytest"],
    )

    analysis = TestAnalyzer().analyze(result)

    assert analysis.status == "error"
    assert analysis.next_action == "rerun_tests"
    assert analysis.failure_reason == "python: command not found"
