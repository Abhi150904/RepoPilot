from __future__ import annotations

from app.schemas.execution import TestAnalysis, TestResult


class TestAnalyzer:
    """Turns raw sandbox execution output into a workflow decision."""

    def analyze(self, result: TestResult) -> TestAnalysis:
        if result.timed_out:
            return TestAnalysis(
                status="timed_out",
                summary="The sandbox test command timed out before completing.",
                failure_reason="The command exceeded the configured sandbox timeout.",
                next_action="inspect_failure",
            )

        if result.exit_code == 0:
            return TestAnalysis(
                status="passed",
                summary=_passed_summary(result),
                next_action="ready_for_review",
            )

        if result.failed > 0:
            return TestAnalysis(
                status="failed",
                summary=f"The sandbox test command failed with {result.failed} failing test(s).",
                failure_reason=_failure_reason(result),
                next_action="inspect_failure",
            )

        return TestAnalysis(
            status="error",
            summary=f"The sandbox test command exited with code {result.exit_code}.",
            failure_reason=_failure_reason(result),
            next_action="rerun_tests",
        )


def _passed_summary(result: TestResult) -> str:
    if result.passed > 0:
        return f"The sandbox test command passed {result.passed} test(s)."
    return "The sandbox test command completed successfully."


def _failure_reason(result: TestResult) -> str:
    output = "\n".join(part for part in [result.stderr.strip(), result.stdout.strip()] if part)
    first_line = output.splitlines()[0] if output else ""
    if first_line:
        return first_line[:300]
    return "No failure output was captured."
