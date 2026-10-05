from __future__ import annotations

import importlib


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


def test_cli_github_apply_changes_can_create_workspace(monkeypatch, capsys) -> None:
    cli = importlib.import_module("main")
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
    monkeypatch.setattr(
        "sys.argv",
        ["main.py", "--repo", "example/demo", "--issue", "16", "--apply-changes"],
    )

    cli.main()

    assert captured["state"] == {
        "repository": "example/demo",
        "issue_number": 16,
        "apply_changes": True,
    }
    assert "Run Workspace:" in capsys.readouterr().out


def test_cli_local_apply_changes_still_requires_workspace(monkeypatch) -> None:
    cli = importlib.import_module("main")
    monkeypatch.setattr("sys.argv", ["main.py", "--apply-changes"])

    try:
        cli.main()
    except SystemExit as exc:
        assert "--workspace is required with --apply-changes" in str(exc)
    else:
        raise AssertionError("Expected local apply-changes runs to require --workspace.")


def test_cli_github_run_tests_can_create_workspace(monkeypatch) -> None:
    cli = importlib.import_module("main")
    captured = {}

    class FakeWorkflow:
        def invoke(self, state):
            captured["state"] = state
            return _minimal_result()

    monkeypatch.setattr(cli, "build_workflow", lambda: FakeWorkflow())
    monkeypatch.setattr(
        "sys.argv",
        [
            "main.py",
            "--repo",
            "example/demo",
            "--issue",
            "16",
            "--run-tests",
            "--test-command",
            "python",
            "-m",
            "pytest",
        ],
    )

    cli.main()

    assert captured["state"] == {
        "repository": "example/demo",
        "issue_number": 16,
        "run_tests": True,
        "max_repair_attempts": 1,
        "test_command": ["python", "-m", "pytest"],
    }
