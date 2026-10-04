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
    target_paths: list[str]
    target_files: list[dict[str, object]]
    code_changes: dict[str, object]
    diff: str
    llm_error: dict[str, object]
    apply_changes: bool
    workspace_path: str
    modified_files: list[str]
    run_tests: bool
    test_runner: str
    test_command: list[str]
    test_result: dict[str, object]
    test_analysis: dict[str, object]
    repair_decision: dict[str, object]
    repair_attempts: int
    max_repair_attempts: int
    repair_context: dict[str, object]
    review_result: dict[str, object]
    approved: bool
    approval_decision: dict[str, object]
    publication_package: dict[str, object]
    publish_dry_run: bool
    publish_local: bool
    publish_push: bool
    publish_pr: bool
    publish_result: dict[str, object]
    run_summary: dict[str, object]
