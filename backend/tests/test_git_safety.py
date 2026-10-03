from __future__ import annotations

import subprocess

from app.tools.git import inspect_git_safety


def test_git_safety_marks_only_expected_changes_safe(tmp_path) -> None:
    _git(tmp_path, "init")
    changed_file = tmp_path / "app.py"
    changed_file.write_text("print('hello')\n", encoding="utf-8")

    report = inspect_git_safety(
        workspace_path=str(tmp_path),
        expected_changed_files=["app.py"],
    )

    assert report.status == "safe"
    assert report.changed_files[0].path == "app.py"
    assert report.unexpected_files == []
    assert report.warnings == []


def test_git_safety_warns_for_unexpected_changes(tmp_path) -> None:
    _git(tmp_path, "init")
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("local note\n", encoding="utf-8")

    report = inspect_git_safety(
        workspace_path=str(tmp_path),
        expected_changed_files=["app.py"],
    )

    assert report.status == "needs_attention"
    assert report.unexpected_files == ["notes.txt"]
    assert "outside RepoPilot" in report.warnings[0]


def test_git_safety_warns_when_workspace_is_not_git_repo(tmp_path) -> None:
    report = inspect_git_safety(
        workspace_path=str(tmp_path),
        expected_changed_files=["app.py"],
    )

    assert report.status == "not_git_repository"
    assert report.current_branch is None
    assert report.warnings


def _git(path, *args: str) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
