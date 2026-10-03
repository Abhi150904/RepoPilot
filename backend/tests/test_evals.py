from __future__ import annotations

import json
from pathlib import Path

from app.evals.models import EvalCase
from app.evals.runner import evaluate_result, load_eval_case, run_eval_case, run_eval_suite


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
                "copy_workspace": True,
                "target_paths": ["app.py"],
                "apply_changes": True,
                "run_tests": True,
                "test_runner": "local",
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
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "app.py").write_text("def login(payload):\n    return payload\n", encoding="utf-8")

    class FakeWorkflow:
        def invoke(self, workflow_input):
            assert workflow_input["issue"] == "Login endpoint returns 500 when email is missing."
            assert Path(workflow_input["workspace_path"]).exists()
            assert Path(workflow_input["workspace_path"]).parent != tmp_path
            assert workflow_input["target_paths"] == ["app.py"]
            assert workflow_input["apply_changes"] is True
            assert workflow_input["run_tests"] is True
            assert workflow_input["test_runner"] == "local"
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


def test_fixture_eval_cases_pass_with_mock_provider(monkeypatch) -> None:
    from app.core.llm import MockLLMProvider
    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "get_llm", lambda role: MockLLMProvider())

    fixture_root = Path(__file__).parent / "fixtures" / "evals"
    cases = [
        fixture_root / "login_validation.case.json",
        fixture_root / "destination_validation.case.json",
    ]

    results = [run_eval_case(path) for path in cases]

    assert [result.status for result in results] == ["passed", "passed"]
