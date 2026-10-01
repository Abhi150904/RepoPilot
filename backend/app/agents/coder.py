from __future__ import annotations

from pathlib import PurePosixPath

from app.core.llm import LLMProvider
from app.schemas.code_change import CodeChangeSet, FileChange, SourceFile
from app.schemas.execution import RepairContext
from app.schemas.issue import IssueAnalysis
from app.schemas.plan import ImplementationPlan
from app.schemas.repository import RepositoryContext
from app.tools.git import render_change_set_diff


class CodeWriterError(ValueError):
    """Raised when generated code changes are malformed or unsafe."""


class CodeWriter:
    """Produces validated structured code changes from full source files."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def propose_changes(
        self,
        issue: str,
        analysis: IssueAnalysis,
        plan: ImplementationPlan,
        target_files: list[SourceFile],
        repository_context: RepositoryContext | None = None,
        repair_context: RepairContext | None = None,
    ) -> CodeChangeSet:
        allowed_paths = _allowed_target_paths(
            plan=plan,
            target_files=target_files,
            repository_context=repository_context,
        )
        originals = {file.path: file.content for file in target_files if file.exists}
        change_set = self._llm.propose_code_changes(
            issue=issue,
            analysis=analysis,
            plan=plan,
            target_files=target_files,
            repair_context=repair_context,
        )
        changes = [
            _validate_change(change=change, allowed_paths=allowed_paths, originals=originals)
            for change in change_set.changes
        ]
        diff = render_change_set_diff(changes=changes, originals=originals)
        return CodeChangeSet(
            summary=change_set.summary,
            changes=changes,
            diff=diff,
        )


def _allowed_target_paths(
    plan: ImplementationPlan,
    target_files: list[SourceFile],
    repository_context: RepositoryContext | None,
) -> set[str]:
    paths = {file.path for file in target_files}
    paths.update(path for path in plan.files_to_inspect if _looks_like_repo_path(path))
    if repository_context:
        paths.update(file.path for file in repository_context.matched_files)
    return paths


def _validate_change(
    change: FileChange,
    allowed_paths: set[str],
    originals: dict[str, str],
) -> FileChange:
    _validate_relative_repo_path(change.path)

    if change.path not in allowed_paths:
        raise CodeWriterError(f"Generated change targets an unrelated file: {change.path}")
    if change.proposed_content is None or not change.proposed_content.strip():
        raise CodeWriterError(f"Generated change has empty content: {change.path}")
    if change.action == "modify" and change.path not in originals:
        raise CodeWriterError(f"Generated modify targets a file that was not loaded: {change.path}")
    if change.action == "create" and change.path in originals:
        raise CodeWriterError(f"Generated create targets an existing file: {change.path}")

    return change


def _validate_relative_repo_path(path: str) -> None:
    if not path or path.strip() != path:
        raise CodeWriterError("Generated change path is empty or padded.")
    normalized = path.replace("\\", "/")
    pure_path = PurePosixPath(normalized)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        raise CodeWriterError(f"Generated change path escapes repository: {path}")


def _looks_like_repo_path(path: str) -> bool:
    if not path or " " in path:
        return False
    try:
        _validate_relative_repo_path(path)
    except CodeWriterError:
        return False
    return "/" in path or "." in PurePosixPath(path).name
