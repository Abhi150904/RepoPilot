from __future__ import annotations

import pytest

from app.agents.publication import PublicationPreparer
from app.schemas.execution import ApprovalDecision


def test_publication_preparer_builds_publication_package() -> None:
    package = PublicationPreparer().prepare(
        issue="App crashes when destination field is empty.\n\nNo description provided.",
        approval=ApprovalDecision(
            approved=True,
            status="approved",
            summary="Human approval was provided for this reviewed patch.",
            next_action="commit_changes",
        ),
        changed_files=["src/search.py", "tests/test_search.py"],
        issue_number=16,
    )

    assert package.status == "ready_to_publish"
    assert package.branch_name == "issue-16-app-crashes-when-destination-field-is-empty"
    assert package.commit_message == "app crashes when destination field is empty"
    assert package.pr_title == "Fix #16: App crashes when destination field is empty"
    assert "Related issue: #16" in package.pr_body
    assert "src/search.py, tests/test_search.py" in package.pr_body
    assert package.next_action == "create_pull_request"


def test_publication_preparer_requires_human_approval() -> None:
    with pytest.raises(ValueError, match="human approval"):
        PublicationPreparer().prepare(
            issue="App crashes when destination field is empty.",
            approval=ApprovalDecision(
                approved=False,
                status="awaiting_approval",
                summary="Waiting for explicit human approval.",
                next_action="human_review",
            ),
            changed_files=["src/search.py"],
        )
