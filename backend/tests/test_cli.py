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

    monkeypatch.setattr(cli, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--repo", "example/demo", "--issue", "16", "--apply"])

    assert captured["state"] == {
        "repository": "example/demo",
        "issue_number": 16,
        "apply_changes": True,
    }
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "RepoPilot run complete" in output
    assert "Status: changes_applied" in output
    assert "Branch: repopilot/issue-16" in output
    assert "Run Workspace:" not in output


def test_cli_legacy_root_flags_still_work(monkeypatch) -> None:
    cli = importlib.import_module("app.cli")
    captured = {}

    class FakeWorkflow:
        def invoke(self, state):
            captured["state"] = state
            return _minimal_result()

    monkeypatch.setattr(cli, "build_workflow", lambda: FakeWorkflow())

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
    captured = {}

    class FakeWorkflow:
        def invoke(self, state):
            captured["state"] = state
            return _minimal_result()

    monkeypatch.setattr(cli, "build_workflow", lambda: FakeWorkflow())

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
        "max_repair_attempts": 1,
        "test_command": ["python", "-m", "pytest"],
        "approved": True,
        "publish_dry_run": True,
    }


def test_cli_test_uses_configured_default_command(monkeypatch) -> None:
    cli = importlib.import_module("app.cli")
    captured = {}

    class FakeWorkflow:
        def invoke(self, state):
            captured["state"] = state
            return _minimal_result()

    monkeypatch.setenv("REPO_PILOT_DEFAULT_TEST_COMMAND", "pytest -q")
    monkeypatch.setattr(cli, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--repo", "example/demo", "--issue", "16", "--test"])

    assert exit_code == 0
    assert captured["state"]["test_command"] == ["pytest", "-q"]


def test_cli_dry_run_alias_sets_publication_state(monkeypatch) -> None:
    cli = importlib.import_module("app.cli")
    captured = {}

    class FakeWorkflow:
        def invoke(self, state):
            captured["state"] = state
            return _minimal_result()

    monkeypatch.setattr(cli, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(
        [
            "run",
            "--repo",
            "example/demo",
            "--issue",
            "16",
            "--approve",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert captured["state"] == {
        "repository": "example/demo",
        "issue_number": 16,
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

    class FakeWorkflow:
        def invoke(self, state):
            return _minimal_result()

    monkeypatch.setattr(cli, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--issue-text", "Fix login validation", "--json"])

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body["issue"] == "Login endpoint returns 500 when email is missing."
    assert body["run_summary"]["next_action"] == "commit_changes"


def test_cli_verbose_output_prints_detailed_sections(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")

    class FakeWorkflow:
        def invoke(self, state):
            return _minimal_result()

    monkeypatch.setattr(cli, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--issue-text", "Fix login validation", "--verbose"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Analysis:" in output
    assert "Implementation Plan:" in output


def test_cli_returns_nonzero_for_failed_run(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")

    class FakeWorkflow:
        def invoke(self, state):
            return _failed_result()

    monkeypatch.setattr(cli, "build_workflow", lambda: FakeWorkflow())

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
