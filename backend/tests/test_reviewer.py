from __future__ import annotations

from app.agents.reviewer import Reviewer
from app.schemas.code_change import CodeChangeSet, FileChange
from app.schemas.execution import ReviewResult, TestAnalysis as ExecutionAnalysis
from app.schemas.plan import ImplementationPlan


def _plan() -> ImplementationPlan:
    return ImplementationPlan(
        summary="Validate missing email.",
        steps=["Add validation."],
        files_to_inspect=["src/routes/login.py"],
        tests_required=["missing email returns validation error"],
    )


def _passed_tests() -> ExecutionAnalysis:
    return ExecutionAnalysis(
        status="passed",
        summary="The sandbox test command passed 1 test(s).",
        next_action="ready_for_review",
    )


def test_reviewer_approves_tested_relevant_patch() -> None:
    change_set = CodeChangeSet(
        summary="Validate email.",
        changes=[
            FileChange(
                path="src/routes/login.py",
                action="modify",
                explanation="Add validation",
                proposed_content="email = payload.get('email')\n",
            )
        ],
        diff="+email = payload.get('email')\n",
    )

    result = Reviewer().review(
        issue="Login endpoint returns 500 when email is missing",
        plan=_plan(),
        change_set=change_set,
        diff=change_set.diff,
        test_analysis=_passed_tests(),
    )

    assert result.approved is True
    assert result.next_action == "await_human_approval"
    assert not any(finding.severity == "error" for finding in result.findings)


def test_reviewer_rejects_empty_diff() -> None:
    result = Reviewer().review(
        issue="Login endpoint returns 500 when email is missing",
        plan=_plan(),
        change_set=CodeChangeSet(summary="No changes", changes=[]),
        diff="",
        test_analysis=_passed_tests(),
    )

    assert result.approved is False
    assert result.next_action == "repair"
    assert any(finding.severity == "error" for finding in result.findings)


def test_reviewer_rejects_when_tests_did_not_pass() -> None:
    result = Reviewer().review(
        issue="Login endpoint returns 500 when email is missing",
        plan=_plan(),
        change_set=CodeChangeSet(
            summary="Validate email.",
            changes=[
                FileChange(
                    path="src/routes/login.py",
                    action="modify",
                    explanation="Add validation",
                    proposed_content="email = payload.get('email')\n",
                )
            ],
            diff="+email = payload.get('email')\n",
        ),
        diff="+email = payload.get('email')\n",
        test_analysis=ExecutionAnalysis(
            status="failed",
            summary="The sandbox test command failed with 1 failing test(s).",
            failure_reason="FAILED tests/test_login.py",
            next_action="inspect_failure",
        ),
    )

    assert result.approved is False
    assert any(finding.category == "correctness" for finding in result.findings)


def test_reviewer_can_delegate_to_model_backed_reasoning() -> None:
    calls = {}

    class FakeReviewerLLM:
        def review_changes(
            self,
            issue,
            plan,
            change_set,
            diff,
            test_analysis,
            repair_attempts=0,
        ):
            calls["issue"] = issue
            calls["repair_attempts"] = repair_attempts
            return ReviewResult(
                approved=True,
                summary="Model reviewer approved the tested patch.",
                findings=[],
                next_action="await_human_approval",
            )

    change_set = CodeChangeSet(
        summary="Validate email.",
        changes=[
            FileChange(
                path="src/routes/login.py",
                action="modify",
                explanation="Add validation",
                proposed_content="email = payload.get('email')\n",
            )
        ],
        diff="+email = payload.get('email')\n",
    )

    result = Reviewer(llm=FakeReviewerLLM()).review(
        issue="Login endpoint returns 500 when email is missing",
        plan=_plan(),
        change_set=change_set,
        diff=change_set.diff,
        test_analysis=_passed_tests(),
        repair_attempts=1,
    )

    assert result.approved is True
    assert result.summary == "Model reviewer approved the tested patch."
    assert calls == {
        "issue": "Login endpoint returns 500 when email is missing",
        "repair_attempts": 1,
    }
