from __future__ import annotations

import re
import subprocess
from base64 import b64encode
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings, get_settings


class WorkspaceError(ValueError):
    """Raised when a repository workspace path is unsafe or invalid."""


@dataclass(frozen=True)
class RepositoryWorkspacePaths:
    root: Path
    repository_dir: Path
    runs_dir: Path


@dataclass(frozen=True)
class CloneResult:
    repo: str
    path: Path
    cloned: bool
    remote_url: str


@dataclass(frozen=True)
class RunWorkspace:
    repo: str
    source_path: Path
    path: Path
    branch_name: str
    base_ref: str


def get_workspace_root(settings: Settings | None = None) -> Path:
    config = settings or get_settings()
    return Path(config.workspace_root).expanduser().resolve()


def ensure_workspace_root(settings: Settings | None = None) -> Path:
    root = get_workspace_root(settings)
    root.mkdir(parents=True, exist_ok=True)
    return root


def repository_workspace_paths(
    repo: str,
    settings: Settings | None = None,
) -> RepositoryWorkspacePaths:
    root = ensure_workspace_root(settings)
    repository_dir = _resolve_inside(root, safe_repo_dir_name(repo))
    runs_dir = _resolve_inside(repository_dir, "runs")
    return RepositoryWorkspacePaths(
        root=root,
        repository_dir=repository_dir,
        runs_dir=runs_dir,
    )


def clone_repository(
    repo: str,
    settings: Settings | None = None,
    token: str | None = None,
) -> CloneResult:
    config = settings or get_settings()
    paths = repository_workspace_paths(repo, settings=config)
    remote_url = github_remote_url(repo)
    auth_token = token or config.github_token

    if paths.repository_dir.exists():
        if _is_git_repository(paths.repository_dir):
            _validate_existing_remote(
                repo=repo,
                path=paths.repository_dir,
                token=auth_token,
            )
            return CloneResult(
                repo=repo,
                path=paths.repository_dir,
                cloned=False,
                remote_url=remote_url,
            )
        raise WorkspaceError(
            f"Workspace path already exists but is not a git repository: {paths.repository_dir}"
        )

    clone_url = github_remote_url(repo)
    _run_git_clone(clone_url=clone_url, target=paths.repository_dir, token=auth_token)
    return CloneResult(
        repo=repo,
        path=paths.repository_dir,
        cloned=True,
        remote_url=remote_url,
    )


def create_run_worktree(
    *,
    repo: str,
    branch_name: str,
    base_ref: str = "HEAD",
    settings: Settings | None = None,
    token: str | None = None,
) -> RunWorkspace:
    clone = clone_repository(repo, settings=settings, token=token)
    paths = repository_workspace_paths(repo, settings=settings)
    safe_branch = safe_branch_name(branch_name)
    worktree_path = _resolve_inside(paths.runs_dir, safe_branch)

    if worktree_path.exists():
        raise WorkspaceError(f"Run workspace already exists: {worktree_path}")
    if _branch_exists(clone.path, safe_branch):
        raise WorkspaceError(f"Branch already exists in workspace repository: {safe_branch}")

    paths.runs_dir.mkdir(parents=True, exist_ok=True)
    _run_git_worktree_add(
        source=clone.path,
        target=worktree_path,
        branch_name=safe_branch,
        base_ref=base_ref,
    )
    return RunWorkspace(
        repo=repo,
        source_path=clone.path,
        path=worktree_path,
        branch_name=safe_branch,
        base_ref=base_ref,
    )


def github_remote_url(repo: str, token: str | None = None) -> str:
    owner, name = parse_repo_slug(repo)
    if token:
        return f"https://x-access-token:{token}@github.com/{owner}/{name}.git"
    return f"https://github.com/{owner}/{name}.git"


def github_ssh_remote_url(repo: str) -> str:
    owner, name = parse_repo_slug(repo)
    return f"git@github.com:{owner}/{name}.git"


def safe_repo_dir_name(repo: str) -> str:
    owner, name = parse_repo_slug(repo)
    return f"{owner}__{name}"


def safe_branch_name(branch_name: str) -> str:
    cleaned = branch_name.strip().replace("\\", "/").strip("/")
    if not cleaned:
        raise WorkspaceError("Branch name cannot be empty.")
    if cleaned.startswith("-") or cleaned.endswith("."):
        raise WorkspaceError("Branch name has an unsafe format.")
    if any(part in {"", ".", ".."} or part.endswith(".lock") for part in cleaned.split("/")):
        raise WorkspaceError("Branch name cannot contain empty or relative path segments.")
    if re.search(r"[\s~^:?*\[\]@{}\\]", cleaned):
        raise WorkspaceError("Branch name contains unsupported characters.")
    if ".." in cleaned or "//" in cleaned or "@{" in cleaned:
        raise WorkspaceError("Branch name contains unsupported sequences.")
    return cleaned


def parse_repo_slug(repo: str) -> tuple[str, str]:
    cleaned = repo.strip().strip("/")
    parts = cleaned.split("/")
    if len(parts) != 2 or not all(parts):
        raise WorkspaceError("Repository must use the 'owner/name' format.")
    owner, name = parts
    if not _is_safe_slug_part(owner) or not _is_safe_slug_part(name):
        raise WorkspaceError(
            "Repository owner and name may only contain letters, numbers, dots, underscores, and hyphens."
        )
    if owner in {".", ".."} or name in {".", ".."}:
        raise WorkspaceError("Repository owner and name cannot be relative path segments.")
    return owner, name


def _is_safe_slug_part(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9._-]+", value) is not None


def _resolve_inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise WorkspaceError(f"Workspace path escapes root: {relative}")
    return path


def _is_git_repository(path: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _run_git_clone(clone_url: str, target: Path, token: str | None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", *_git_auth_args(token), "clone", clone_url, str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorkspaceError(
            "Git clone failed: "
            f"{_redact_token(result.stderr.strip() or result.stdout.strip(), token)}"
        )


def _branch_exists(source: Path, branch_name: str) -> bool:
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
        cwd=source,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _run_git_worktree_add(
    *,
    source: Path,
    target: Path,
    branch_name: str,
    base_ref: str,
) -> None:
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(target), base_ref],
        cwd=source,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorkspaceError(
            "Git worktree creation failed: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def _validate_existing_remote(repo: str, path: Path, token: str | None) -> None:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorkspaceError(
            "Existing workspace does not have an origin remote, so it cannot be reused safely."
        )
    actual = result.stdout.strip()
    if not _remote_matches_repo(actual_remote=actual, repo=repo):
        raise WorkspaceError(
            "Existing workspace origin does not match requested repository: "
            f"{_redact_token(actual, token)}"
        )


def _remote_matches_repo(actual_remote: str, repo: str) -> bool:
    return _normalize_remote(actual_remote) == _normalize_remote(github_remote_url(repo))


def _normalize_remote(remote: str) -> str:
    cleaned = remote.strip()
    cleaned = re.sub(r"^https://[^/@]+:[^/@]+@github\.com/", "https://github.com/", cleaned)
    cleaned = re.sub(r"^https://[^/@]+@github\.com/", "https://github.com/", cleaned)
    cleaned = re.sub(r"^git@github\.com:", "https://github.com/", cleaned)
    cleaned = re.sub(r"^ssh://git@github\.com/", "https://github.com/", cleaned)
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    return cleaned.rstrip("/")


def _redact_token(text: str, token: str | None) -> str:
    if not token:
        return text
    return text.replace(token, "[redacted]").replace(_git_auth_header(token), "[redacted]")


def _git_auth_args(token: str | None) -> list[str]:
    if not token:
        return []
    return [
        "-c",
        f"http.https://github.com/.extraheader=AUTHORIZATION: basic {_git_auth_header(token)}",
    ]


def _git_auth_header(token: str) -> str:
    return b64encode(f"x-access-token:{token}".encode("utf-8")).decode("ascii")
