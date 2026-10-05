from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path


def _minimal_result() -> dict[str, object]:
    return {
        "issue": "Login endpoint returns 500 when email is missing.",
        "analysis": {
            "summary": "Missing email is not validated.",
            "suspected_area": "request validation",
            "likely_cause": "Missing guard clause.",
            "risk_level": "medium",
        },
        "plan": {
            "summary": "Add missing email validation.",
            "steps": ["Add a guard clause."],
            "files_to_inspect": ["app.py"],
            "tests_required": ["missing email returns 400"],
        },
        "run_summary": {
            "status": "changes_applied",
            "summary": "Code changes were applied.",
            "tests_passed": None,
            "repair_attempts": 0,
            "metrics": None,
            "next_action": "commit_changes",
        },
    }


def _failed_result() -> dict[str, object]:
    result = _minimal_result()
    result["test_analysis"] = {
        "status": "failed",
        "summary": "Tests failed.",
        "failure_reason": "Assertion failed.",
        "next_action": "rerun_tests",
    }
    result["run_summary"] = {
        "status": "repair_failed",
        "summary": "Tests still fail after repair attempts.",
        "tests_passed": False,
        "repair_attempts": 1,
        "metrics": None,
        "next_action": "inspect_failure",
    }
    return result


def test_cli_run_subcommand_builds_github_apply_state(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")
    captured = {}

    class FakeWorkflow:
        def invoke(self, state):
            captured["state"] = state
            return {
                **_minimal_result(),
                "run_workspace": {
                    "repo": "example/demo",
                    "source_path": ".repopilot/workspaces/example__demo",
                    "path": ".repopilot/workspaces/example__demo/runs/repopilot/issue-16",
                    "branch_name": "repopilot/issue-16",
                    "base_ref": "HEAD",
                },
            }

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--repo", "example/demo", "--issue", "16", "--apply"])

    assert captured["state"] == {
        "repository": "example/demo",
        "issue_number": 16,
        "apply_changes": True,
        "max_repair_attempts": 1,
    }
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "RepoPilot run complete" in output
    assert "Status: changes_applied" in output
    assert "Branch: repopilot/issue-16" in output
    assert "Run Workspace:" not in output


def test_cli_legacy_root_flags_still_work(monkeypatch) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")
    captured = {}

    class FakeWorkflow:
        def invoke(self, state):
            captured["state"] = state
            return _minimal_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(
        [
            "--repo",
            "example/demo",
            "--issue",
            "16",
            "--run-tests",
            "--test-command",
            "python",
            "-m",
            "pytest",
        ]
    )

    assert exit_code == 0
    assert captured["state"] == {
        "repository": "example/demo",
        "issue_number": 16,
        "run_tests": True,
        "test_runner": "docker",
        "max_repair_attempts": 1,
        "test_command": ["python", "-m", "pytest"],
    }


def test_cli_local_apply_requires_workspace() -> None:
    cli = importlib.import_module("app.cli")

    try:
        cli.main(["run", "--apply"])
    except SystemExit as exc:
        assert "--workspace is required with --apply" in str(exc)
    else:
        raise AssertionError("Expected local apply runs to require --workspace.")


def test_cli_publish_shorthand_sets_publication_state(monkeypatch) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")
    captured = {}

    class FakeWorkflow:
        def invoke(self, state):
            captured["state"] = state
            return _minimal_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(
        [
            "run",
            "--repo",
            "example/demo",
            "--issue",
            "16",
            "--apply",
            "--test",
            "--approve",
            "--publish",
            "dry-run",
        ]
    )

    assert exit_code == 0
    assert captured["state"] == {
        "repository": "example/demo",
        "issue_number": 16,
        "apply_changes": True,
        "run_tests": True,
        "test_runner": "docker",
        "max_repair_attempts": 1,
        "test_command": ["python", "-m", "pytest"],
        "approved": True,
        "publish_dry_run": True,
    }


def test_cli_test_uses_configured_default_command(monkeypatch) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")
    captured = {}

    class FakeWorkflow:
        def invoke(self, state):
            captured["state"] = state
            return _minimal_result()

    monkeypatch.setenv("REPO_PILOT_DEFAULT_TEST_COMMAND", "pytest -q")
    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--repo", "example/demo", "--issue", "16", "--test"])

    assert exit_code == 0
    assert captured["state"]["test_command"] == ["pytest", "-q"]


def test_cli_dry_run_alias_sets_publication_state(monkeypatch) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")
    captured = {}

    class FakeWorkflow:
        def invoke(self, state):
            captured["state"] = state
            return _minimal_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(
        [
            "run",
            "--repo",
            "example/demo",
            "--issue",
            "16",
            "--apply",
            "--test",
            "--approve",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert captured["state"] == {
        "repository": "example/demo",
        "issue_number": 16,
        "apply_changes": True,
        "run_tests": True,
        "test_runner": "docker",
        "max_repair_attempts": 1,
        "test_command": ["python", "-m", "pytest"],
        "approved": True,
        "publish_dry_run": True,
    }


def test_cli_rejects_publication_without_approval() -> None:
    cli = importlib.import_module("app.cli")

    try:
        cli.main(["run", "--repo", "example/demo", "--issue", "16", "--dry-run"])
    except SystemExit as exc:
        assert "Publication mode requires --approve" in str(exc)
    else:
        raise AssertionError("Expected publication mode to require approval.")


def test_cli_json_output_prints_full_result(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")

    class FakeWorkflow:
        def invoke(self, state):
            return _minimal_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--issue-text", "Fix login validation", "--json"])

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body["issue"] == "Login endpoint returns 500 when email is missing."
    assert body["run_summary"]["next_action"] == "commit_changes"


def test_cli_verbose_output_prints_detailed_sections(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")

    class FakeWorkflow:
        def invoke(self, state):
            return _minimal_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--issue-text", "Fix login validation", "--verbose"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Analysis:" in output
    assert "Implementation Plan:" in output


def test_cli_returns_nonzero_for_failed_run(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")

    class FakeWorkflow:
        def invoke(self, state):
            return _failed_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--issue-text", "Fix login validation"])

    output = capsys.readouterr().out
    assert exit_code == 2
    assert "Status: repair_failed" in output
    assert "Tests: failed" in output


def test_main_wrapper_run_help_smoke() -> None:
    completed = subprocess.run(
        [sys.executable, "main.py", "run", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "usage: repopilot run" in completed.stdout
    assert "--dry-run" in completed.stdout
    assert "Examples:" in completed.stdout


def test_packaging_exposes_console_script_and_backend_package() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["repopilot"] == "app.cli:main"
    assert pyproject["tool"]["setuptools"]["package-dir"] == {"": "backend"}
    assert pyproject["tool"]["setuptools"]["packages"]["find"]["where"] == ["backend"]


def test_cli_config_validate_prints_human_report(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")

    monkeypatch.setenv("REPO_PILOT_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("REPO_PILOT_LLM_MODEL", "gemini-test-model")
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.setattr(cli.shutil, "which", lambda command: "C:/tools/repopilot.exe")

    exit_code = cli.main(["config", "validate"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "RepoPilot config" in output
    assert "LLM provider: gemini" in output
    assert "LLM model: gemini-test-model" in output
    assert "Gemini API key: configured" in output
    assert "GitHub token: configured" in output
    assert "CLI install: available" in output


def test_cli_config_validate_json_reports_settings(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")

    monkeypatch.setenv("REPO_PILOT_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("REPO_PILOT_LLM_MODEL", "gemini-test-model")
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.setattr(cli.shutil, "which", lambda command: None)

    exit_code = cli.main(["config", "validate", "--json"])

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body["llm_provider"] == "gemini"
    assert body["llm_model"] == "gemini-test-model"
    assert body["gemini_api_key"] == {
        "required": True,
        "configured": True,
        "status": "configured",
    }
    assert body["github_token"]["status"] == "configured"
    assert body["cli_install"] == {"available": False, "path": None}


def test_cli_eval_workflow_prints_report(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    eval_runner = importlib.import_module("app.evals.runner")
    eval_models = importlib.import_module("app.evals.models")

    result = eval_models.EvalSuiteResult(
        total=1,
        passed=1,
        failed=0,
        points_earned=1,
        points_possible=1,
        score=1.0,
        category_scores={"outcome": 1.0},
        cases=[
            eval_models.EvalCaseResult(
                id="sample",
                status="passed",
                points_earned=1,
                points_possible=1,
                score=1.0,
                checks=[
                    eval_models.EvalCheck(
                        name="final_status",
                        category="outcome",
                        passed=True,
                        message="Expected final status matched.",
                    )
                ],
            )
        ],
    )

    monkeypatch.setattr(eval_runner, "discover_eval_cases", lambda paths: [Path("case.case.json")])
    monkeypatch.setattr(eval_runner, "run_eval_suite", lambda paths: result)

    exit_code = cli.main(["eval"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Eval cases: 1/1 passed" in output
    assert "- sample: passed" in output


def test_cli_eval_workflow_json_prints_result(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    eval_runner = importlib.import_module("app.evals.runner")
    eval_models = importlib.import_module("app.evals.models")

    result = eval_models.EvalSuiteResult(
        total=1,
        passed=1,
        failed=0,
        points_earned=0,
        points_possible=0,
        score=1.0,
        cases=[
            eval_models.EvalCaseResult(
                id="sample",
                status="passed",
                checks=[],
            )
        ],
    )

    monkeypatch.setattr(eval_runner, "discover_eval_cases", lambda paths: [Path("case.case.json")])
    monkeypatch.setattr(eval_runner, "run_eval_suite", lambda paths: result)

    exit_code = cli.main(["eval", "--json"])

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body["total"] == 1
    assert body["cases"][0]["id"] == "sample"


def test_cli_eval_workflow_returns_nonzero_when_cases_fail(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    eval_runner = importlib.import_module("app.evals.runner")
    eval_models = importlib.import_module("app.evals.models")

    result = eval_models.EvalSuiteResult(
        total=1,
        passed=0,
        failed=1,
        points_earned=0,
        points_possible=1,
        score=0.0,
        cases=[
            eval_models.EvalCaseResult(
                id="sample",
                status="failed",
                points_earned=0,
                points_possible=1,
                score=0.0,
                checks=[
                    eval_models.EvalCheck(
                        name="final_status",
                        category="outcome",
                        passed=False,
                        message="Expected final status did not match.",
                    )
                ],
            )
        ],
    )

    monkeypatch.setattr(eval_runner, "discover_eval_cases", lambda paths: [Path("case.case.json")])
    monkeypatch.setattr(eval_runner, "run_eval_suite", lambda paths: result)

    exit_code = cli.main(["eval"])

    assert exit_code == 1
    assert "Eval cases: 0/1 passed" in capsys.readouterr().out


def test_cli_eval_retrieval_prints_report(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    retrieval_eval = importlib.import_module("app.evals.retrieval")

    result = retrieval_eval.RetrievalBenchmarkResult(
        total_cases=1,
        summaries=[
            retrieval_eval.RetrieverSummary(
                retriever="hybrid",
                cases=1,
                avg_recall_at_k={1: 1.0},
                avg_precision_at_k={1: 1.0},
                hit_rate_at_k={1: 1.0},
                avg_mrr=1.0,
                avg_duration_ms=0.1,
            )
        ],
        cases=[],
    )

    monkeypatch.setattr(retrieval_eval, "load_retrieval_benchmark", lambda path: object())
    monkeypatch.setattr(
        retrieval_eval,
        "run_retrieval_benchmark",
        lambda benchmark, limit: result,
    )

    exit_code = cli.main(["eval", "retrieval", "--limit", "3"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Retrieval benchmark cases: 1" in output
    assert "- hybrid:" in output
