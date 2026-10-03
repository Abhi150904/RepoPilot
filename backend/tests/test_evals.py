from __future__ import annotations

import json
from pathlib import Path

from app.evals.models import EvalCase
from app.evals.runner import (
    discover_eval_cases,
    evaluate_result,
    load_eval_case,
    run_eval_case,
    run_eval_suite,
)


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
    assert result.points_earned == 4
    assert result.points_possible == 4
    assert result.score == 1.0


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
    assert result.points_earned == 0
    assert result.points_possible == 4
    assert result.score == 0.0


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
    assert result.points_earned == 3
    assert result.points_possible == 3
    assert result.category_scores == {
        "files": 1.0,
        "outcome": 1.0,
        "tests": 1.0,
    }


def test_discover_eval_cases_accepts_files_and_directories(tmp_path) -> None:
    case_dir = tmp_path / "cases"
    nested = case_dir / "nested"
    nested.mkdir(parents=True)
    first = case_dir / "first.case.json"
    second = nested / "second.case.json"
    ignored = case_dir / "notes.json"
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    ignored.write_text("{}", encoding="utf-8")

    paths = discover_eval_cases([case_dir, first])

    assert paths == [first, second]


def test_discover_eval_cases_rejects_missing_path(tmp_path) -> None:
    missing = tmp_path / "missing"

    try:
        discover_eval_cases([missing])
    except FileNotFoundError as exc:
        assert str(missing) in str(exc)
    else:
        raise AssertionError("Expected missing eval paths to be rejected.")


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
    assert [result.score for result in results] == [1.0, 1.0]
