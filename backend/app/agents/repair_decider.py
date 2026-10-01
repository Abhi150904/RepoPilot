from __future__ import annotations

from app.schemas.execution import RepairDecision, TestAnalysis


class RepairDecider:
    """Decides whether a failed test result is eligible for an automated repair pass."""

    def decide(self, analysis: TestAnalysis) -> RepairDecision:
        if analysis.status == "passed":
            return RepairDecision(
                should_retry=False,
                next_action="ready_for_review",
                reason="Tests passed, so no repair pass is needed.",
            )

        if analysis.status == "failed" and analysis.failure_reason:
            return RepairDecision(
                should_retry=True,
                next_action="repair",
                reason="Tests failed with captured failure output that can guide a repair pass.",
            )

        if analysis.status == "error" and analysis.next_action == "rerun_tests":
            return RepairDecision(
                should_retry=False,
                next_action="rerun_tests",
                reason="The test command failed before producing a reliable test failure.",
            )

        return RepairDecision(
            should_retry=False,
            next_action="stop",
            reason="The test outcome needs human inspection before another automated pass.",
        )
