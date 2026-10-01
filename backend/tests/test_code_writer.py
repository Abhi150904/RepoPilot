from __future__ import annotations

from pathlib import Path
import shutil
from uuid import uuid4

import pytest

from app.agents.coder import CodeWriter, CodeWriterError
from app.core.llm import MockLLMProvider
from app.schemas.code_change import CodeChangeSet, FileChange, SourceFile
from app.schemas.execution import RepairContext
from app.schemas.issue import IssueAnalysis
from app.schemas.plan import ImplementationPlan
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


def _analysis() -> IssueAnalysis:
    return IssueAnalysis(
        summary="Login fails when email is missing.",
        suspected_area="authentication flow",
        likely_cause="Missing request validation.",
        risk_level="medium",
    )


def test_code_writer_generates_real_single_file_modification() -> None:
    plan = ImplementationPlan(
        summary="Validate login input.",
        steps=["Add email validation guard."],
        files_to_inspect=["src/routes/login.py"],
        tests_required=["missing email returns validation error"],
    )

    change_set = CodeWriter(llm=MockLLMProvider()).propose_changes(
        issue="Login endpoint returns 500 when email is missing",
        analysis=_analysis(),
        plan=plan,
        target_files=[
            SourceFile(
                path="src/routes/login.py",
                content=(
                    "def login(payload):\n"
                    "    email = payload[\"email\"]\n"
                    "    return {\"email\": email}\n"
                ),
            )
        ],
    )

    assert change_set.changes[0].path == "src/routes/login.py"
    assert change_set.changes[0].action == "modify"
    assert "payload.get(\"email\")" in change_set.changes[0].proposed_content
    assert "email is required" in change_set.diff


def test_code_writer_includes_repair_context_in_patch_proposal() -> None:
    plan = ImplementationPlan(
        summary="Validate login input.",
        steps=["Add email validation."],
        files_to_inspect=["src/routes/login.py"],
        tests_required=["missing email returns validation error"],
    )
    repair_context = RepairContext(
        attempt=1,
        test_status="failed",
        test_summary="The sandbox test command failed with 1 failing test(s).",
        failure_reason="FAILED tests/test_login.py::test_missing_email",
        previous_diff="-old\n+new\n",
    )

    change_set = CodeWriter(llm=MockLLMProvider()).propose_changes(
        issue="Login endpoint returns 500 when email is missing",
        analysis=_analysis(),
        plan=plan,
        target_files=[
            SourceFile(
                path="src/routes/login.py",
                content=(
                    "def login(payload):\n"
                    "    email = payload[\"email\"]\n"
                    "    return {\"email\": email}\n"
                ),
            )
        ],
        repair_context=repair_context,
    )

    assert "email is required" in change_set.diff


class FakeCodeLLM:
    def __init__(self, change: FileChange) -> None:
        self._change = change

    def propose_code_changes(self, **kwargs):
        return CodeChangeSet(summary="Fake change", changes=[self._change])


def test_code_writer_rejects_empty_generated_content() -> None:
    plan = ImplementationPlan(
        summary="Update example.",
        steps=["Modify file."],
        files_to_inspect=["src/example.py"],
        tests_required=[],
    )

    with pytest.raises(CodeWriterError, match="empty content"):
        CodeWriter(
            llm=FakeCodeLLM(
                FileChange(
                    path="src/example.py",
                    action="modify",
                    explanation="Bad content",
                    proposed_content="",
                )
            )
        ).propose_changes(
            issue="Update example",
            analysis=_analysis(),
            plan=plan,
            target_files=[SourceFile(path="src/example.py", content="old\n")],
        )


def test_code_writer_rejects_unrelated_generated_path() -> None:
    plan = ImplementationPlan(
        summary="Update example.",
        steps=["Modify file."],
        files_to_inspect=["src/example.py"],
        tests_required=[],
    )

    with pytest.raises(CodeWriterError, match="unrelated file"):
        CodeWriter(
            llm=FakeCodeLLM(
                FileChange(
                    path="src/other.py",
                    action="modify",
                    explanation="Wrong file",
                    proposed_content="new\n",
                )
            )
        ).propose_changes(
            issue="Update example",
            analysis=_analysis(),
            plan=plan,
            target_files=[SourceFile(path="src/example.py", content="old\n")],
        )


def test_code_writer_rejects_traversal_generated_path() -> None:
    plan = ImplementationPlan(
        summary="Update example.",
        steps=["Modify file."],
        files_to_inspect=["src/example.py"],
        tests_required=[],
    )

    with pytest.raises(CodeWriterError, match="escapes repository"):
        CodeWriter(
            llm=FakeCodeLLM(
                FileChange(
                    path="../outside.py",
                    action="modify",
                    explanation="Bad path",
                    proposed_content="new\n",
                )
            )
        ).propose_changes(
            issue="Update example",
            analysis=_analysis(),
            plan=plan,
            target_files=[SourceFile(path="src/example.py", content="old\n")],
        )


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
