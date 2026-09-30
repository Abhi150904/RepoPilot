from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    repository: str
    issue_number: int
    issue: str
    issue_title: str
    issue_body: str
    issue_url: str
    analysis: dict[str, object]
    repository_context: dict[str, object]
    plan: dict[str, object]
    code_changes: dict[str, object]
    diff: str
    apply_changes: bool
    workspace_path: str
    modified_files: list[str]
