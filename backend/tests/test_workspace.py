from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.core.config import Settings
import app.tools.workspace as workspace_module
from app.tools.workspace import (
    WorkspaceError,
    clone_repository,
    create_run_worktree,
    github_remote_url,
    github_ssh_remote_url,
    repository_workspace_paths,
    safe_branch_name,
    safe_repo_dir_name,
)


def test_repository_workspace_paths_are_under_configured_root(tmp_path) -> None:
    settings = Settings(workspace_root=str(tmp_path / "workspaces"))

    paths = repository_workspace_paths("Abhi150904/Wandr", settings=settings)

    assert paths.root == tmp_path / "workspaces"
    assert paths.repository_dir == paths.root / "Abhi150904__Wandr"
    assert paths.runs_dir == paths.repository_dir / "runs"
    assert paths.root.exists()


def test_safe_repo_dir_name_normalizes_owner_and_repo() -> None:
    assert safe_repo_dir_name("Abhi150904/Wandr") == "Abhi150904__Wandr"


def test_repository_slug_rejects_path_traversal() -> None:
    for repo in ["../Wandr", "Abhi150904/../Wandr", "Abhi150904/Wandr/extra", "Wandr"]:
        try:
            safe_repo_dir_name(repo)
        except WorkspaceError:
            pass
        else:
            raise AssertionError(f"Expected unsafe repo slug to be rejected: {repo}")


def test_safe_branch_name_accepts_simple_slugs() -> None:
    assert safe_branch_name("fix-login-validation") == "fix-login-validation"
    assert safe_branch_name("repopilot/issue-16") == "repopilot/issue-16"


def test_safe_branch_name_rejects_unsafe_names() -> None:
    for branch in ["", "../main", "bad branch", "bad..branch", "-bad", "bad.lock", "bad@{x}"]:
        try:
            safe_branch_name(branch)
        except WorkspaceError:
            pass
        else:
            raise AssertionError(f"Expected unsafe branch name to be rejected: {branch}")


def test_github_remote_url_uses_token_when_available() -> None:
    assert github_remote_url("Abhi150904/Wandr") == "https://github.com/Abhi150904/Wandr.git"
    assert (
        github_remote_url("Abhi150904/Wandr", token="secret")
        == "https://x-access-token:secret@github.com/Abhi150904/Wandr.git"
    )
    assert github_ssh_remote_url("Abhi150904/Wandr") == "git@github.com:Abhi150904/Wandr.git"


def test_clone_repository_clones_into_workspace(monkeypatch, tmp_path) -> None:
    calls = []
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("REPOPILOT_GITHUB_TOKEN", raising=False)
    settings = Settings(
        workspace_root=str(tmp_path / "workspaces"),
        github_token="secret-token",
        _env_file=None,
    )

    def fake_run(args, cwd=None, capture_output=True, text=True, check=False):
        calls.append({"args": args, "cwd": cwd})
        target = args[-1]
        if args[0] == "git" and "clone" in args:
            (tmp_path / "workspaces" / "Abhi150904__Wandr" / ".git").mkdir(parents=True)
            assert target.endswith("Abhi150904__Wandr")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"Unexpected subprocess call: {args}")

    monkeypatch.setattr(workspace_module.subprocess, "run", fake_run)

    result = clone_repository("Abhi150904/Wandr", settings=settings)

    assert result.cloned is True
    assert result.path == tmp_path / "workspaces" / "Abhi150904__Wandr"
    assert result.remote_url == "https://github.com/Abhi150904/Wandr.git"
    assert calls[0]["args"][-2] == "https://github.com/Abhi150904/Wandr.git"
    assert "secret-token" not in " ".join(calls[0]["args"])
    assert "extraheader=AUTHORIZATION: basic" in calls[0]["args"][2]


def test_clone_repository_reuses_existing_git_repo(monkeypatch, tmp_path) -> None:
    settings = Settings(workspace_root=str(tmp_path / "workspaces"), _env_file=None)
    repo_dir = tmp_path / "workspaces" / "Abhi150904__Wandr"
    repo_dir.mkdir(parents=True)
    calls = []

    def fake_run(args, cwd=None, capture_output=True, text=True, check=False):
        calls.append(args)
        assert cwd == repo_dir
        if args == ["git", "rev-parse", "--is-inside-work-tree"]:
            return SimpleNamespace(returncode=0, stdout="true\n", stderr="")
        if args == ["git", "remote", "get-url", "origin"]:
            return SimpleNamespace(returncode=0, stdout="git@github.com:Abhi150904/Wandr.git\n", stderr="")
        raise AssertionError(f"Unexpected subprocess call: {args}")

    monkeypatch.setattr(workspace_module.subprocess, "run", fake_run)

    result = clone_repository("Abhi150904/Wandr", settings=settings)

    assert result.cloned is False
    assert result.path == repo_dir
    assert calls == [
        ["git", "rev-parse", "--is-inside-work-tree"],
        ["git", "remote", "get-url", "origin"],
    ]


def test_clone_repository_rejects_mismatched_existing_origin(monkeypatch, tmp_path) -> None:
    settings = Settings(workspace_root=str(tmp_path / "workspaces"), _env_file=None)
    repo_dir = tmp_path / "workspaces" / "Abhi150904__Wandr"
    repo_dir.mkdir(parents=True)

    def fake_run(args, cwd=None, capture_output=True, text=True, check=False):
        if args == ["git", "rev-parse", "--is-inside-work-tree"]:
            return SimpleNamespace(returncode=0, stdout="true\n", stderr="")
        if args == ["git", "remote", "get-url", "origin"]:
            return SimpleNamespace(returncode=0, stdout="https://github.com/Other/Repo.git\n", stderr="")
        raise AssertionError(f"Unexpected subprocess call: {args}")

    monkeypatch.setattr(workspace_module.subprocess, "run", fake_run)

    try:
        clone_repository("Abhi150904/Wandr", settings=settings)
    except WorkspaceError as exc:
        assert "origin does not match" in str(exc)
    else:
        raise AssertionError("Expected mismatched origin to be rejected.")


def test_clone_repository_rejects_existing_repo_without_origin(monkeypatch, tmp_path) -> None:
    settings = Settings(workspace_root=str(tmp_path / "workspaces"), _env_file=None)
    repo_dir = tmp_path / "workspaces" / "Abhi150904__Wandr"
    repo_dir.mkdir(parents=True)

    def fake_run(args, cwd=None, capture_output=True, text=True, check=False):
        if args == ["git", "rev-parse", "--is-inside-work-tree"]:
            return SimpleNamespace(returncode=0, stdout="true\n", stderr="")
        if args == ["git", "remote", "get-url", "origin"]:
            return SimpleNamespace(returncode=2, stdout="", stderr="No such remote")
        raise AssertionError(f"Unexpected subprocess call: {args}")

    monkeypatch.setattr(workspace_module.subprocess, "run", fake_run)

    try:
        clone_repository("Abhi150904/Wandr", settings=settings)
    except WorkspaceError as exc:
        assert "does not have an origin remote" in str(exc)
    else:
        raise AssertionError("Expected missing origin to be rejected.")


def test_clone_repository_rejects_existing_non_git_directory(monkeypatch, tmp_path) -> None:
    settings = Settings(workspace_root=str(tmp_path / "workspaces"), _env_file=None)
    repo_dir = tmp_path / "workspaces" / "Abhi150904__Wandr"
    repo_dir.mkdir(parents=True)

    def fake_run(args, cwd=None, capture_output=True, text=True, check=False):
        return SimpleNamespace(returncode=1, stdout="", stderr="not a repo")

    monkeypatch.setattr(workspace_module.subprocess, "run", fake_run)

    try:
        clone_repository("Abhi150904/Wandr", settings=settings)
    except WorkspaceError as exc:
        assert "not a git repository" in str(exc)
    else:
        raise AssertionError("Expected existing non-git workspace to be rejected.")


def test_clone_repository_redacts_token_from_clone_errors(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("REPOPILOT_GITHUB_TOKEN", raising=False)
    settings = Settings(
        workspace_root=str(tmp_path / "workspaces"),
        github_token="secret-token",
        _env_file=None,
    )

    def fake_run(args, cwd=None, capture_output=True, text=True, check=False):
        return SimpleNamespace(
            returncode=128,
            stdout="",
            stderr="fatal: https://x-access-token:secret-token@github.com failed",
        )

    monkeypatch.setattr(workspace_module.subprocess, "run", fake_run)

    try:
        clone_repository("Abhi150904/Wandr", settings=settings)
    except WorkspaceError as exc:
        assert "secret-token" not in str(exc)
        assert "[redacted]" in str(exc)
    else:
        raise AssertionError("Expected failed clone to raise WorkspaceError.")


def test_create_run_worktree_creates_branch_workspace(monkeypatch, tmp_path) -> None:
    settings = Settings(workspace_root=str(tmp_path / "workspaces"), _env_file=None)
    repo_dir = tmp_path / "workspaces" / "Abhi150904__Wandr"
    repo_dir.mkdir(parents=True)
    calls = []

    def fake_run(args, cwd=None, capture_output=True, text=True, check=False):
        calls.append({"args": args, "cwd": cwd})
        if args == ["git", "rev-parse", "--is-inside-work-tree"]:
            return SimpleNamespace(returncode=0, stdout="true\n", stderr="")
        if args == ["git", "remote", "get-url", "origin"]:
            return SimpleNamespace(returncode=0, stdout="https://github.com/Abhi150904/Wandr.git\n", stderr="")
        if args[:3] == ["git", "show-ref", "--verify"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if args[:4] == ["git", "worktree", "add", "-b"]:
            Path(args[5]).mkdir(parents=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"Unexpected subprocess call: {args}")

    monkeypatch.setattr(workspace_module.subprocess, "run", fake_run)

    result = create_run_worktree(
        repo="Abhi150904/Wandr",
        branch_name="repopilot/issue-16",
        base_ref="origin/main",
        settings=settings,
    )

    assert result.source_path == repo_dir
    assert result.path == repo_dir / "runs" / "repopilot" / "issue-16"
    assert result.branch_name == "repopilot/issue-16"
    assert calls[-1]["args"] == [
        "git",
        "worktree",
        "add",
        "-b",
        "repopilot/issue-16",
        str(result.path),
        "origin/main",
    ]


def test_create_run_worktree_rejects_existing_run_path(monkeypatch, tmp_path) -> None:
    settings = Settings(workspace_root=str(tmp_path / "workspaces"), _env_file=None)
    repo_dir = tmp_path / "workspaces" / "Abhi150904__Wandr"
    (repo_dir / "runs" / "fix-login").mkdir(parents=True)

    def fake_run(args, cwd=None, capture_output=True, text=True, check=False):
        if args == ["git", "rev-parse", "--is-inside-work-tree"]:
            return SimpleNamespace(returncode=0, stdout="true\n", stderr="")
        if args == ["git", "remote", "get-url", "origin"]:
            return SimpleNamespace(returncode=0, stdout="https://github.com/Abhi150904/Wandr.git\n", stderr="")
        raise AssertionError(f"Unexpected subprocess call: {args}")

    monkeypatch.setattr(workspace_module.subprocess, "run", fake_run)

    try:
        create_run_worktree(
            repo="Abhi150904/Wandr",
            branch_name="fix-login",
            settings=settings,
        )
    except WorkspaceError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Expected existing run workspace to be rejected.")


def test_create_run_worktree_rejects_existing_branch(monkeypatch, tmp_path) -> None:
    settings = Settings(workspace_root=str(tmp_path / "workspaces"), _env_file=None)
    repo_dir = tmp_path / "workspaces" / "Abhi150904__Wandr"
    repo_dir.mkdir(parents=True)

    def fake_run(args, cwd=None, capture_output=True, text=True, check=False):
        if args == ["git", "rev-parse", "--is-inside-work-tree"]:
            return SimpleNamespace(returncode=0, stdout="true\n", stderr="")
        if args == ["git", "remote", "get-url", "origin"]:
            return SimpleNamespace(returncode=0, stdout="https://github.com/Abhi150904/Wandr.git\n", stderr="")
        if args[:3] == ["git", "show-ref", "--verify"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"Unexpected subprocess call: {args}")

    monkeypatch.setattr(workspace_module.subprocess, "run", fake_run)

    try:
        create_run_worktree(
            repo="Abhi150904/Wandr",
            branch_name="fix-login",
            settings=settings,
        )
    except WorkspaceError as exc:
        assert "Branch already exists" in str(exc)
    else:
        raise AssertionError("Expected existing branch to be rejected.")
