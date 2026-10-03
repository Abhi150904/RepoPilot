from __future__ import annotations

import difflib
from pathlib import Path
import subprocess

from app.schemas.code_change import FileChange
from app.schemas.execution import GitChangedFile, GitSafetyReport


def render_unified_diff(original: str, proposed: str, path: str) -> str:
    original_lines = original.splitlines(keepends=True)
    proposed_lines = proposed.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            original_lines,
            proposed_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="\n",
        )
    )


def render_change_set_diff(changes: list[FileChange], originals: dict[str, str]) -> str:
    diffs: list[str] = []
    for change in changes:
        if change.proposed_content is None:
            continue
        original = originals.get(change.path, "")
        diffs.append(
            render_unified_diff(
                original=original,
                proposed=change.proposed_content,
                path=change.path,
            )
        )
    return "\n".join(diff for diff in diffs if diff)


def inspect_git_safety(
    workspace_path: str,
    expected_changed_files: list[str],
) -> GitSafetyReport:
    root = Path(workspace_path)
    if not root.exists():
        return GitSafetyReport(
            status="unavailable",
            summary="The workspace path does not exist, so git safety could not be checked.",
            warnings=["Workspace path does not exist."],
        )

    inside_work_tree = _run_git(root, "rev-parse", "--is-inside-work-tree")
    if inside_work_tree.returncode != 0:
        return GitSafetyReport(
            status="not_git_repository",
            summary="The workspace is not a git repository.",
            warnings=["Run publication from a git repository workspace."],
        )

    branch_result = _run_git(root, "branch", "--show-current")
    current_branch = branch_result.stdout.strip() or None
    status_result = _run_git(root, "status", "--short")
    if status_result.returncode != 0:
        return GitSafetyReport(
            status="unavailable",
            summary="Git status could not be read.",
            current_branch=current_branch,
            warnings=[status_result.stderr.strip() or "git status failed."],
        )

    changed_files = _parse_status_lines(status_result.stdout.splitlines())
    expected = set(expected_changed_files)
    status_paths = {file.path for file in changed_files}
    unexpected_files = sorted(path for path in status_paths if path not in expected)
    warnings = _build_warnings(
        expected_changed_files=expected_changed_files,
        status_paths=status_paths,
        unexpected_files=unexpected_files,
    )

    if warnings:
        return GitSafetyReport(
            status="needs_attention",
            summary="Git safety check found items to inspect before publication.",
            current_branch=current_branch,
            changed_files=changed_files,
            unexpected_files=unexpected_files,
            warnings=warnings,
        )

    return GitSafetyReport(
        status="safe",
        summary="Git safety check found only RepoPilot-applied changes.",
        current_branch=current_branch,
        changed_files=changed_files,
        unexpected_files=[],
        warnings=[],
    )


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_status_lines(lines: list[str]) -> list[GitChangedFile]:
    changed_files: list[GitChangedFile] = []
    for line in lines:
        if not line:
            continue
        status = line[:2].strip()
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", maxsplit=1)[1]
        changed_files.append(GitChangedFile(status=status, path=path))
    return changed_files


def _build_warnings(
    *,
    expected_changed_files: list[str],
    status_paths: set[str],
    unexpected_files: list[str],
) -> list[str]:
    warnings: list[str] = []
    if not expected_changed_files:
        warnings.append("No RepoPilot-applied files were recorded for publication.")
    if expected_changed_files and not status_paths:
        warnings.append("Git does not show pending changes for the RepoPilot-applied files.")
    if unexpected_files:
        warnings.append("Working tree contains changes outside RepoPilot's modified files.")
    return warnings
