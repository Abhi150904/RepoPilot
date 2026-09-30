from __future__ import annotations

from app.agents.repair_decider import RepairDecider
from app.schemas.execution import TestAnalysis as ExecutionAnalysis


def test_repair_decider_marks_passed_tests_ready_for_review() -> None:
    analysis = ExecutionAnalysis(
        status="passed",
        summary="The sandbox test command passed 4 test(s).",
        next_action="ready_for_review",
    )

    decision = RepairDecider().decide(analysis)

    assert decision.should_retry is False
    assert decision.next_action == "ready_for_review"
    assert "no repair" in decision.reason


def test_repair_decider_allows_repair_for_failed_tests_with_output() -> None:
    analysis = ExecutionAnalysis(
        status="failed",
        summary="The sandbox test command failed with 1 failing test(s).",
        failure_reason="FAILED tests/test_login.py::test_missing_email",
        next_action="inspect_failure",
    )

    decision = RepairDecider().decide(analysis)

    assert decision.should_retry is True
    assert decision.next_action == "repair"
    assert "failure output" in decision.reason


def test_repair_decider_reruns_command_errors() -> None:
    analysis = ExecutionAnalysis(
        status="error",
        summary="The sandbox test command exited with code 127.",
        failure_reason="python: command not found",
        next_action="rerun_tests",
    )

    decision = RepairDecider().decide(analysis)

    assert decision.should_retry is False
    assert decision.next_action == "rerun_tests"
    assert "test command failed" in decision.reason


def test_repair_decider_stops_for_timeouts() -> None:
    analysis = ExecutionAnalysis(
        status="timed_out",
        summary="The sandbox test command timed out before completing.",
        failure_reason="The command exceeded the configured sandbox timeout.",
        next_action="inspect_failure",
    )

    decision = RepairDecider().decide(analysis)

    assert decision.should_retry is False
    assert decision.next_action == "stop"
    assert "human inspection" in decision.reason
