from __future__ import annotations

import difflib

from app.schemas.code_change import FileChange


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
