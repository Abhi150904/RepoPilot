from __future__ import annotations

import json

from app.evals.models import EvalCase
from app.evals.runner import evaluate_result, load_eval_case, run_eval_suite


def test_load_eval_case_from_json(tmp_path) -> None:
    path = tmp_path / "case.json"
    path.write_text(
        json.dumps(
            {
                "id": "missing-email",
                "issue": "Login endpoint returns 500 when email is missing.",
                "apply_changes": True,
                "run_tests": True,
                "test_command": ["python", "-m", "pytest"],
                "expectations": {
                    "final_status": "awaiting_approval",
                    "tests_passed": True,
                    "touched_files": ["app.py"],
                },
            }
        ),
        encoding="utf-8",
    )

    case = load_eval_case(path)

    assert case.id == "missing-email"
    assert case.apply_changes is True
    assert case.test_command == ["python", "-m", "pytest"]
    assert case.expectations.touched_files == ["app.py"]


def test_evaluate_result_passes_when_expectations_match() -> None:
    case = EvalCase(
        id="missing-email",
        issue="Login endpoint returns 500 when email is missing.",
        expectations={
            "final_status": "awaiting_approval",
            "tests_passed": True,
            "touched_files": ["app.py"],
            "forbidden_files": ["README.md"],
        },
    )

    result = evaluate_result(
        case=case,
        result={
            "modified_files": ["app.py"],
            "run_summary": {
                "status": "awaiting_approval",
                "tests_passed": True,
            },
        },
    )

    assert result.status == "passed"
    assert all(check.passed for check in result.checks)


def test_evaluate_result_fails_with_actionable_check_messages() -> None:
    case = EvalCase(
        id="missing-email",
        issue="Login endpoint returns 500 when email is missing.",
        expectations={
            "final_status": "awaiting_approval",
            "tests_passed": True,
            "touched_files": ["app.py"],
            "forbidden_files": ["README.md"],
        },
    )

    result = evaluate_result(
        case=case,
        result={
            "modified_files": ["README.md"],
            "run_summary": {
                "status": "repair_failed",
                "tests_passed": False,
            },
        },
    )

    failed_checks = [check for check in result.checks if not check.passed]
    assert result.status == "failed"
    assert {check.name for check in failed_checks} == {
        "final_status",
        "tests_passed",
        "touched_files",
        "forbidden_files",
    }


def test_run_eval_suite_uses_workflow_input(monkeypatch, tmp_path) -> None:
    path = tmp_path / "case.json"
    path.write_text(
        json.dumps(
            {
                "id": "missing-email",
                "issue": "Login endpoint returns 500 when email is missing.",
                "workspace_path": "fixture",
                "apply_changes": True,
                "run_tests": True,
                "approved": True,
                "expectations": {
                    "final_status": "approved",
                    "tests_passed": True,
                    "touched_files": ["app.py"],
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeWorkflow:
        def invoke(self, workflow_input):
            assert workflow_input["issue"] == "Login endpoint returns 500 when email is missing."
            assert workflow_input["workspace_path"].endswith("fixture")
            assert workflow_input["apply_changes"] is True
            assert workflow_input["run_tests"] is True
            assert workflow_input["approved"] is True
            return {
                "modified_files": ["app.py"],
                "run_summary": {
                    "status": "approved",
                    "tests_passed": True,
                },
            }

    import app.evals.runner as runner

    monkeypatch.setattr(runner, "build_workflow", lambda: FakeWorkflow())

    result = run_eval_suite([path])

    assert result.total == 1
    assert result.passed == 1
    assert result.failed == 0
