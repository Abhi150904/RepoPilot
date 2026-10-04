from __future__ import annotations

from app.agents.run_summarizer import RunSummarizer


def test_run_summarizer_marks_planned_only_without_changes() -> None:
    summary = RunSummarizer().summarize({"code_changes": {"changes": []}})

    assert summary.status == "planned_only"
    assert summary.tests_passed is None
    assert summary.next_action == "review_plan"


def test_run_summarizer_marks_changes_proposed() -> None:
    summary = RunSummarizer().summarize(
        {"code_changes": {"changes": [{"path": "src/example.py"}]}}
    )

    assert summary.status == "changes_proposed"
    assert summary.next_action == "review_diff"


def test_run_summarizer_marks_tests_passed_after_repair() -> None:
    summary = RunSummarizer().summarize(
        {
            "repair_attempts": 1,
            "test_analysis": {
                "status": "passed",
                "summary": "The sandbox test command passed 1 test(s).",
                "failure_reason": None,
                "next_action": "ready_for_review",
            },
        }
    )

    assert summary.status == "ready_for_review"
    assert summary.tests_passed is True
    assert summary.repair_attempts == 1
    assert "after 1 repair" in summary.summary


def test_run_summarizer_marks_approved_review_as_awaiting_approval() -> None:
    summary = RunSummarizer().summarize(
        {
            "test_analysis": {
                "status": "passed",
                "summary": "The sandbox test command passed 1 test(s).",
                "failure_reason": None,
                "next_action": "ready_for_review",
            },
            "review_result": {
                "approved": True,
                "summary": "Automated review approved the tested patch.",
                "findings": [],
                "next_action": "await_human_approval",
            },
        }
    )

    assert summary.status == "awaiting_approval"
    assert summary.tests_passed is True
    assert summary.next_action == "human_review"


def test_run_summarizer_marks_human_approved_review_as_approved() -> None:
    summary = RunSummarizer().summarize(
        {
            "test_analysis": {
                "status": "passed",
                "summary": "The sandbox test command passed 1 test(s).",
                "failure_reason": None,
                "next_action": "ready_for_review",
            },
            "review_result": {
                "approved": True,
                "summary": "Automated review approved the tested patch.",
                "findings": [],
                "next_action": "await_human_approval",
            },
            "approval_decision": {
                "approved": True,
                "status": "approved",
                "summary": "Human approval was provided for this reviewed patch.",
                "next_action": "commit_changes",
            },
        }
    )

    assert summary.status == "approved"
    assert summary.tests_passed is True
    assert summary.next_action == "commit_changes"


def test_run_summarizer_mentions_ready_publication_package() -> None:
    summary = RunSummarizer().summarize(
        {
            "test_analysis": {
                "status": "passed",
                "summary": "The sandbox test command passed 1 test(s).",
                "failure_reason": None,
                "next_action": "ready_for_review",
            },
            "review_result": {
                "approved": True,
                "summary": "Automated review approved the tested patch.",
                "findings": [],
                "next_action": "await_human_approval",
            },
            "approval_decision": {
                "approved": True,
                "status": "approved",
                "summary": "Human approval was provided for this reviewed patch.",
                "next_action": "commit_changes",
            },
            "publication_package": {
                "status": "ready_to_publish",
                "branch_name": "fix-login-validation",
                "commit_message": "fix login validation",
                "pr_title": "Fix login validation",
                "pr_body": "## Summary\n- Fix login validation",
                "changed_files": ["app.py"],
                "next_action": "create_pull_request",
            },
        }
    )

    assert summary.status == "approved"
    assert "publication details are ready" in summary.summary
    assert summary.next_action == "commit_changes"


def test_run_summarizer_marks_rejected_review_as_review_failed() -> None:
    summary = RunSummarizer().summarize(
        {
            "test_analysis": {
                "status": "passed",
                "summary": "The sandbox test command passed 1 test(s).",
                "failure_reason": None,
                "next_action": "ready_for_review",
            },
            "review_result": {
                "approved": False,
                "summary": "Automated review found issues.",
                "findings": [
                    {
                        "severity": "error",
                        "category": "correctness",
                        "message": "No source changes were proposed.",
                        "path": None,
                    }
                ],
                "next_action": "repair",
            },
        }
    )

    assert summary.status == "review_failed"
    assert summary.next_action == "inspect_failure"


def test_run_summarizer_marks_repair_failed() -> None:
    summary = RunSummarizer().summarize(
        {
            "repair_attempts": 1,
            "test_analysis": {
                "status": "failed",
                "summary": "The sandbox test command failed with 1 failing test(s).",
                "failure_reason": "FAILED tests/test_example.py::test_example",
                "next_action": "inspect_failure",
            },
            "repair_decision": {
                "should_retry": True,
                "next_action": "repair",
                "reason": "Tests failed with captured failure output.",
            },
        }
    )

    assert summary.status == "repair_failed"
    assert summary.tests_passed is False
    assert summary.next_action == "inspect_failure"


def test_run_summarizer_marks_command_errors_as_needing_human_action() -> None:
    summary = RunSummarizer().summarize(
        {
            "test_analysis": {
                "status": "error",
                "summary": "The sandbox test command exited with code 127.",
                "failure_reason": "python: command not found",
                "next_action": "rerun_tests",
            },
        }
    )

    assert summary.status == "needs_human"
    assert summary.tests_passed is False
    assert summary.next_action == "rerun_tests"


def test_run_summarizer_marks_llm_provider_errors_as_needing_human_action() -> None:
    summary = RunSummarizer().summarize(
        {
            "llm_error": {
                "stage": "coder",
                "type": "LLMProviderError",
                "message": "Gemini returned malformed JSON.",
                "next_action": "inspect_failure",
            }
        }
    )

    assert summary.status == "needs_human"
    assert "Gemini returned malformed JSON" in summary.summary
    assert summary.next_action == "inspect_failure"


def test_run_summarizer_includes_compact_run_metrics() -> None:
    summary = RunSummarizer().summarize(
        {
            "run_metrics": {
                "llm_calls": [
                    {
                        "role": "analyzer",
                        "provider": "gemini",
                        "model": "gemini-3.7-pro",
                        "prompt_tokens": 10,
                        "output_tokens": 5,
                        "total_tokens": 15,
                        "duration_ms": 12.5,
                        "success": True,
                        "retry_count": 0,
                    }
                ],
                "prompt_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "llm_call_count": 1,
                "retries": 0,
                "repair_attempts": 0,
                "total_runtime_ms": 12.5,
                "stage_timings": [
                    {
                        "stage": "analyzer",
                        "duration_ms": 12.5,
                        "success": True,
                    }
                ],
                "models_by_role": {"analyzer": ["gemini-3.7-pro"]},
            }
        }
    )

    assert summary.status == "planned_only"
    assert summary.metrics is not None
    assert summary.metrics.llm_call_count == 1
    assert summary.metrics.total_tokens == 15
    assert summary.metrics.models_by_role == {"analyzer": ["gemini-3.7-pro"]}
