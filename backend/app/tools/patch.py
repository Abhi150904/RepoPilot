from __future__ import annotations

from app.schemas.code_change import ChangeApplicationResult, CodeChangeSet, FileChange
from app.tools.filesystem import WorkspaceFileSystem
from app.tools.git import render_change_set_diff


class PatchApplicationError(RuntimeError):
    """Raised when a structured change set cannot be safely applied."""


def apply_change_set(
    change_set: CodeChangeSet,
    filesystem: WorkspaceFileSystem,
) -> ChangeApplicationResult:
    originals = _read_originals(change_set.changes, filesystem)
    modified_files: list[str] = []

    for change in change_set.changes:
        if change.proposed_content is None:
            continue

        _validate_action(change=change, filesystem=filesystem)
        filesystem.write_text(change.path, change.proposed_content)
        modified_files.append(change.path)

    diff = render_change_set_diff(changes=change_set.changes, originals=originals)
    return ChangeApplicationResult(
        modified_files=modified_files,
        diff=diff,
    )


def _read_originals(
    changes: list[FileChange],
    filesystem: WorkspaceFileSystem,
) -> dict[str, str]:
    originals: dict[str, str] = {}
    for change in changes:
        if filesystem.file_exists(change.path):
            originals[change.path] = filesystem.read_text(change.path)
        else:
            originals[change.path] = ""
    return originals


def _validate_action(change: FileChange, filesystem: WorkspaceFileSystem) -> None:
    exists = filesystem.file_exists(change.path)
    if change.action == "modify" and not exists:
        raise PatchApplicationError(f"Cannot modify missing file: {change.path}")
    if change.action == "create" and exists:
        raise PatchApplicationError(f"Cannot create existing file: {change.path}")
