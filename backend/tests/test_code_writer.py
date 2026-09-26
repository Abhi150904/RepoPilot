from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.coder import CodeWriter
from app.schemas.plan import ImplementationPlan
from app.schemas.repository import RepositoryContext, RetrievedFile
from app.tools.filesystem import WorkspaceFileSystem, WorkspacePathError
from app.tools.git import render_unified_diff


def test_workspace_file_system_blocks_paths_outside_root() -> None:
    fs = WorkspaceFileSystem(root=Path.cwd())

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
