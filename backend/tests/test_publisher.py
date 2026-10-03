from __future__ import annotations

import subprocess

from app.agents.publisher import PublishExecutor
from app.schemas.execution import GitSafetyReport, PublicationPackage, PublishResult


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


def test_publish_executor_pushes_published_branch(tmp_path) -> None:
    remote = tmp_path / "remote.git"
    workspace = tmp_path / "workspace"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "clone", str(remote), str(workspace))
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "RepoPilot Test")
    (workspace / "app.py").write_text("print('fixed')\n", encoding="utf-8")

    package = PublicationPackage(
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
    executor = PublishExecutor(workspace_path=str(workspace))
    local_result = executor.publish_local(package)

    result = executor.push_branch(package=package, local_result=local_result)

    assert result.mode == "push"
    assert result.status == "published"
    assert result.branch_name == "fix-login-validation"
    assert result.remote_name == "origin"
    assert result.commit_sha == local_result.commit_sha
    assert result.executed_commands[-1] == "git push -u origin fix-login-validation"
    assert result.next_action == "open_pull_request"
    assert _git_output(remote, "rev-parse", "fix-login-validation") == result.commit_sha


def test_publish_executor_push_blocks_without_local_publication(tmp_path) -> None:
    result = PublishExecutor(workspace_path=str(tmp_path)).push_branch(
        package=PublicationPackage(
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
        ),
        local_result=PublishResult(
            mode="dry_run",
            status="ready",
            summary="Publication dry run passed.",
            pr_title="Fix login validation",
            pr_body="## Summary\n- Fix login validation",
            next_action="run_publication_commands",
        ),
    )

    assert result.status == "blocked"
    assert "Local publication must complete before pushing." in result.blockers


def test_publish_executor_opens_pull_request_after_push() -> None:
    class FakeGitHub:
        def create_pull_request(self, *, repo, title, body, head, base):
            assert repo == "Abhi150904/Wandr"
            assert title == "Fix login validation"
            assert head == "fix-login-validation"
            assert base == "main"
            from app.schemas.execution import PullRequestResult

            return PullRequestResult(
                number=17,
                url="https://github.com/Abhi150904/Wandr/pull/17",
                title=title,
                head=head,
                base=base,
            )

    result = PublishExecutor().open_pull_request(
        package=PublicationPackage(
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
        ),
        push_result=PublishResult(
            mode="push",
            status="published",
            summary="Publication branch was pushed.",
            pr_title="Fix login validation",
            pr_body="## Summary\n- Fix login validation",
            branch_name="fix-login-validation",
            commit_sha="abc123",
            remote_name="origin",
            next_action="open_pull_request",
        ),
        repository="Abhi150904/Wandr",
        github=FakeGitHub(),
    )

    assert result.mode == "pr"
    assert result.status == "published"
    assert result.pr_url == "https://github.com/Abhi150904/Wandr/pull/17"
    assert result.pull_request is not None
    assert result.pull_request.number == 17
    assert result.commit_sha == "abc123"
    assert result.next_action == "review_pull_request"


def test_publish_executor_pr_blocks_without_successful_push() -> None:
    result = PublishExecutor().open_pull_request(
        package=PublicationPackage(
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
        ),
        push_result=PublishResult(
            mode="local",
            status="published",
            summary="Local publication completed.",
            pr_title="Fix login validation",
            pr_body="## Summary\n- Fix login validation",
            branch_name="fix-login-validation",
            commit_sha="abc123",
            next_action="push_branch",
        ),
        repository="Abhi150904/Wandr",
    )

    assert result.status == "blocked"
    assert "Branch push must complete before opening a pull request." in result.blockers


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
