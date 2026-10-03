from __future__ import annotations

import subprocess

from app.agents.publisher import PublishExecutor
from app.schemas.execution import GitSafetyReport, PublicationPackage


def test_publish_executor_dry_run_marks_safe_package_ready() -> None:
    result = PublishExecutor().dry_run(
        PublicationPackage(
            status="ready_to_publish",
            branch_name="fix-login-validation",
            commit_message="fix login validation",
            pr_title="Fix login validation",
            pr_body="## Summary\n- Fix login validation",
            changed_files=["app.py"],
            commands=[
                'git checkout -b "fix-login-validation"',
                'git add "app.py"',
                'git commit -m "fix login validation"',
                'git push -u origin "fix-login-validation"',
            ],
            git_safety=GitSafetyReport(
                status="safe",
                summary="Git safety check found only RepoPilot-applied changes.",
            ),
            next_action="create_pull_request",
        )
    )

    assert result.mode == "dry_run"
    assert result.status == "ready"
    assert result.commands[0] == 'git checkout -b "fix-login-validation"'
    assert result.next_action == "run_publication_commands"


def test_publish_executor_dry_run_blocks_unsafe_git_state() -> None:
    result = PublishExecutor().dry_run(
        PublicationPackage(
            status="ready_to_publish",
            branch_name="fix-login-validation",
            commit_message="fix login validation",
            pr_title="Fix login validation",
            pr_body="## Summary\n- Fix login validation",
            changed_files=["app.py"],
            commands=['git add "app.py"'],
            git_safety=GitSafetyReport(
                status="needs_attention",
                summary="Git safety check found items to inspect before publication.",
                warnings=["Working tree contains changes outside RepoPilot's modified files."],
            ),
            next_action="create_pull_request",
        )
    )

    assert result.status == "blocked"
    assert "Git safety status is needs_attention." in result.blockers
    assert "outside RepoPilot" in result.blockers[1]
    assert result.next_action == "inspect_failure"


def test_publish_executor_dry_run_blocks_missing_changed_files() -> None:
    result = PublishExecutor().dry_run(
        PublicationPackage(
            status="ready_to_publish",
            branch_name="fix-login-validation",
            commit_message="fix login validation",
            pr_title="Fix login validation",
            pr_body="## Summary\n- Fix login validation",
            changed_files=[],
            commands=[],
            git_safety=GitSafetyReport(
                status="safe",
                summary="Git safety check found only RepoPilot-applied changes.",
            ),
            next_action="create_pull_request",
        )
    )

    assert result.status == "blocked"
    assert "No changed files were recorded for publication." in result.blockers
    assert "No publication commands were generated." in result.blockers


def test_publish_executor_local_creates_branch_and_commit(tmp_path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "RepoPilot Test")
    (tmp_path / "app.py").write_text("print('fixed')\n", encoding="utf-8")

    result = PublishExecutor(workspace_path=str(tmp_path)).publish_local(
        PublicationPackage(
            status="ready_to_publish",
            branch_name="fix-login-validation",
            commit_message="fix login validation",
            pr_title="Fix login validation",
            pr_body="## Summary\n- Fix login validation",
            changed_files=["app.py"],
            commands=[
                'git checkout -b "fix-login-validation"',
                'git add "app.py"',
                'git commit -m "fix login validation"',
                'git push -u origin "fix-login-validation"',
            ],
            git_safety=GitSafetyReport(
                status="safe",
                summary="Git safety check found only RepoPilot-applied changes.",
            ),
            next_action="create_pull_request",
        )
    )

    assert result.mode == "local"
    assert result.status == "published"
    assert result.branch_name == "fix-login-validation"
    assert result.commit_sha
    assert result.executed_commands == [
        "git checkout -b fix-login-validation",
        "git add app.py",
        "git commit -m fix login validation",
    ]
    assert result.next_action == "push_branch"
    assert _git_output(tmp_path, "branch", "--show-current") == "fix-login-validation"
    assert _git_output(tmp_path, "log", "-1", "--pretty=%s") == "fix login validation"


def test_publish_executor_local_blocks_without_workspace() -> None:
    result = PublishExecutor().publish_local(
        PublicationPackage(
            status="ready_to_publish",
            branch_name="fix-login-validation",
            commit_message="fix login validation",
            pr_title="Fix login validation",
            pr_body="## Summary\n- Fix login validation",
            changed_files=["app.py"],
            commands=['git add "app.py"'],
            git_safety=GitSafetyReport(
                status="safe",
                summary="Git safety check found only RepoPilot-applied changes.",
            ),
            next_action="create_pull_request",
        )
    )

    assert result.status == "blocked"
    assert "Workspace path is required for local publication." in result.blockers


def _git(path, *args: str) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _git_output(path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()
