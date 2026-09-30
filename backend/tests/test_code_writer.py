from __future__ import annotations

from pathlib import Path
import shutil
from uuid import uuid4

import pytest

from app.agents.coder import CodeWriter
from app.schemas.code_change import CodeChangeSet, FileChange
from app.schemas.plan import ImplementationPlan
from app.schemas.repository import RepositoryContext, RetrievedFile
from app.tools.filesystem import WorkspaceFileSystem, WorkspacePathError
from app.tools.git import render_unified_diff
from app.tools.patch import PatchApplicationError, apply_change_set


def _make_workspace_dir() -> Path:
    root = Path(".test-workspaces") / uuid4().hex
    root.mkdir(parents=True)
    return root


def _remove_workspace_dir(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_workspace_file_system_blocks_paths_outside_root() -> None:
    fs = WorkspaceFileSystem(root=".")

    with pytest.raises(WorkspacePathError):
        fs.resolve_path("../outside.py")


def test_render_unified_diff_for_modified_content() -> None:
    diff = render_unified_diff(
        original="line one\nline two\n",
        proposed="line one\nline changed\n",
        path="src/example.py",
    )

    assert "--- a/src/example.py" in diff
    assert "+++ b/src/example.py" in diff
    assert "-line two" in diff
    assert "+line changed" in diff


def test_code_writer_uses_retrieved_files_for_patch_proposal() -> None:
    plan = ImplementationPlan(
        summary="Validate destination input before planning.",
        steps=["Check destination parsing.", "Add validation guard."],
        files_to_inspect=["fallback file"],
        tests_required=["empty destination returns validation error"],
    )
    context = RepositoryContext(
        repository="example/demo",
        query="destination validation",
        matched_files=[
            RetrievedFile(
                path="src/agents/planner.agent.ts",
                reason="matched",
                content_preview="const extractDestination = () => {};",
            )
        ],
    )

    change_set = CodeWriter().propose_changes(
        issue="App crashes when destination field is empty",
        plan=plan,
        repository_context=context,
    )

    assert change_set.changes[0].path == "src/agents/planner.agent.ts"
    assert change_set.changes[0].action == "modify"
    assert "Validate destination input" in change_set.diff
    assert "const extractDestination" in change_set.diff
    assert "// RepoPilot patch proposal" in change_set.diff


def test_workspace_file_system_writes_inside_root() -> None:
    root = _make_workspace_dir()
    fs = WorkspaceFileSystem(root=root)

    try:
        fs.write_text("src/example.py", "print('hello')\n")

        assert fs.read_text("src/example.py") == "print('hello')\n"
    finally:
        _remove_workspace_dir(root)


def test_apply_change_set_modifies_existing_file_and_returns_diff() -> None:
    root = _make_workspace_dir()
    fs = WorkspaceFileSystem(root=root)

    try:
        fs.write_text("src/example.py", "old value\n")
        change_set = CodeChangeSet(
            summary="Update example",
            changes=[
                FileChange(
                    path="src/example.py",
                    action="modify",
                    explanation="Update content",
                    proposed_content="new value\n",
                )
            ],
        )

        result = apply_change_set(change_set=change_set, filesystem=fs)

        assert result.modified_files == ["src/example.py"]
        assert fs.read_text("src/example.py") == "new value\n"
        assert "-old value" in result.diff
        assert "+new value" in result.diff
    finally:
        _remove_workspace_dir(root)


def test_apply_change_set_creates_new_file() -> None:
    root = _make_workspace_dir()
    fs = WorkspaceFileSystem(root=root)

    try:
        change_set = CodeChangeSet(
            summary="Create example",
            changes=[
                FileChange(
                    path="src/new_file.py",
                    action="create",
                    explanation="Create content",
                    proposed_content="print('new')\n",
                )
            ],
        )

        result = apply_change_set(change_set=change_set, filesystem=fs)

        assert result.modified_files == ["src/new_file.py"]
        assert fs.read_text("src/new_file.py") == "print('new')\n"
        assert "+print('new')" in result.diff
    finally:
        _remove_workspace_dir(root)


def test_apply_change_set_rejects_wrong_actions() -> None:
    root = _make_workspace_dir()
    fs = WorkspaceFileSystem(root=root)

    try:
        fs.write_text("src/existing.py", "exists\n")

        with pytest.raises(PatchApplicationError, match="missing file"):
            apply_change_set(
                change_set=CodeChangeSet(
                    summary="Missing modify",
                    changes=[
                        FileChange(
                            path="src/missing.py",
                            action="modify",
                            explanation="No file",
                            proposed_content="content\n",
                        )
                    ],
                ),
                filesystem=fs,
            )

        with pytest.raises(PatchApplicationError, match="existing file"):
            apply_change_set(
                change_set=CodeChangeSet(
                    summary="Existing create",
                    changes=[
                        FileChange(
                            path="src/existing.py",
                            action="create",
                            explanation="Already there",
                            proposed_content="content\n",
                        )
                    ],
                ),
                filesystem=fs,
            )
    finally:
        _remove_workspace_dir(root)
