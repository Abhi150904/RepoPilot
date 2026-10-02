from __future__ import annotations

from app.schemas.execution import RepairDecision, ReviewResult, RunSummary, TestAnalysis


class RunSummarizer:
    """Produces a compact final verdict for a completed workflow run."""

    def summarize(self, state: dict[str, object]) -> RunSummary:
        repair_attempts = int(state.get("repair_attempts", 0))

        if "test_analysis" in state:
            return _summarize_tested_run(state=state, repair_attempts=repair_attempts)

        if state.get("modified_files"):
            return RunSummary(
                status="changes_applied",
                summary="Code changes were applied, but tests were not run.",
                repair_attempts=repair_attempts,
                next_action="commit_changes",
            )

        if _has_proposed_changes(state):
            return RunSummary(
                status="changes_proposed",
                summary="Code changes were proposed but not applied or tested.",
                repair_attempts=repair_attempts,
                next_action="review_diff",
            )

        return RunSummary(
            status="planned_only",
            summary="The workflow produced analysis and a plan, but no concrete file changes.",
            repair_attempts=repair_attempts,
            next_action="review_plan",
        )


def _summarize_tested_run(
    state: dict[str, object],
    repair_attempts: int,
) -> RunSummary:
    analysis = TestAnalysis.model_validate(state["test_analysis"])

    if analysis.status == "passed":
        if "review_result" in state:
            review = ReviewResult.model_validate(state["review_result"])
            if review.approved:
                return RunSummary(
                    status="awaiting_approval",
                    summary="Tests passed and automated review approved the patch.",
                    tests_passed=True,
                    repair_attempts=repair_attempts,
                    next_action="human_review",
                )
            return RunSummary(
                status="review_failed",
                summary="Tests passed, but automated review found issues to address.",
                tests_passed=True,
                repair_attempts=repair_attempts,
                next_action="inspect_failure",
            )
        return RunSummary(
            status="ready_for_review",
            summary=_passed_summary(repair_attempts),
            tests_passed=True,
            repair_attempts=repair_attempts,
            next_action="review_diff",
        )

    if analysis.status == "failed":
        decision = RepairDecision.model_validate(state["repair_decision"])
        if decision.next_action == "repair" and repair_attempts > 0:
            return RunSummary(
                status="repair_failed",
                summary=f"Tests are still failing after {repair_attempts} repair attempt(s).",
                tests_passed=False,
                repair_attempts=repair_attempts,
                next_action="inspect_failure",
            )
        return RunSummary(
            status="repair_needed",
            summary="Tests failed and a repair pass is available.",
            tests_passed=False,
            repair_attempts=repair_attempts,
            next_action="inspect_failure",
        )

    if analysis.status == "error":
        return RunSummary(
            status="needs_human",
            summary="The test command failed before producing a reliable test result.",
            tests_passed=False,
            repair_attempts=repair_attempts,
            next_action="rerun_tests",
        )

    return RunSummary(
        status="needs_human",
        summary="The test command timed out and needs human inspection.",
        tests_passed=False,
        repair_attempts=repair_attempts,
        next_action="human_review",
    )


def _passed_summary(repair_attempts: int) -> str:
    if repair_attempts:
        return f"Tests passed after {repair_attempts} repair attempt(s)."
    return "Tests passed without a repair attempt."


def _has_proposed_changes(state: dict[str, object]) -> bool:
    code_changes = state.get("code_changes")
    if not isinstance(code_changes, dict):
        return False
    changes = code_changes.get("changes")
    return isinstance(changes, list) and bool(changes)
