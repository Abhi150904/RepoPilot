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
        repository="Abhi150904/Wandr",
    )

    assert package.status == "ready_to_publish"
    assert package.branch_name == "issue-16-app-crashes-when-destination-field-is-empty"
    assert package.commit_message == "app crashes when destination field is empty"
    assert package.pr_title == "Fix #16: App crashes when destination field is empty"
    assert package.pr_url == (
        "https://github.com/Abhi150904/Wandr/pull/new/"
        "issue-16-app-crashes-when-destination-field-is-empty"
    )
    assert package.pr_command.startswith('gh pr create --title "Fix #16:')
    assert "Use the PR URL after pushing the branch" in package.pr_instructions[2]
    assert "Related issue: #16" in package.pr_body
    assert "src/search.py, tests/test_search.py" in package.pr_body
    assert package.commands == [
        'git checkout -b "issue-16-app-crashes-when-destination-field-is-empty"',
        'git add "src/search.py" "tests/test_search.py"',
        'git commit -m "app crashes when destination field is empty"',
        'git push -u origin "issue-16-app-crashes-when-destination-field-is-empty"',
    ]
    assert package.next_action == "create_pull_request"


def test_publication_preparer_quotes_command_values() -> None:
    package = PublicationPreparer().prepare(
        issue='Fix "special" destination path',
        approval=ApprovalDecision(
            approved=True,
            status="approved",
            summary="Human approval was provided for this reviewed patch.",
            next_action="commit_changes",
        ),
        changed_files=["src/search form.py"],
    )

    assert package.commands == [
        'git checkout -b "fix-special-destination-path"',
        'git add "src/search form.py"',
        'git commit -m "fix \\"special\\" destination path"',
        'git push -u origin "fix-special-destination-path"',
    ]


def test_publication_preparer_reuses_existing_run_branch() -> None:
    package = PublicationPreparer().prepare(
        issue="App crashes when destination field is empty.",
        approval=ApprovalDecision(
            approved=True,
            status="approved",
            summary="Human approval was provided for this reviewed patch.",
            next_action="commit_changes",
        ),
        changed_files=["src/search.py"],
        issue_number=16,
        repository="Abhi150904/Wandr",
        branch_name="repopilot/issue-16-app-crashes",
        branch_exists=True,
    )

    assert package.branch_name == "repopilot/issue-16-app-crashes"
    assert package.pr_url == "https://github.com/Abhi150904/Wandr/pull/new/repopilot/issue-16-app-crashes"
    assert package.commands == [
        'git add "src/search.py"',
        'git commit -m "app crashes when destination field is empty"',
        'git push -u origin "repopilot/issue-16-app-crashes"',
    ]


def test_publication_preparer_warns_when_no_changed_files_recorded() -> None:
    package = PublicationPreparer().prepare(
        issue="Prepare RepoPilot changes",
        approval=ApprovalDecision(
            approved=True,
            status="approved",
            summary="Human approval was provided for this reviewed patch.",
            next_action="commit_changes",
        ),
        changed_files=[],
    )

    assert package.commands[1] == (
        "# No changed files were recorded; inspect git status before committing."
    )
    assert package.pr_url is None
    assert "GitHub repository page" in package.pr_instructions[2]


def test_publication_preparer_builds_github_cli_command() -> None:
    package = PublicationPreparer().prepare(
        issue="Fix login validation",
        approval=ApprovalDecision(
            approved=True,
            status="approved",
            summary="Human approval was provided for this reviewed patch.",
            next_action="commit_changes",
        ),
        changed_files=["app.py"],
    )

    assert package.pr_command == (
        'gh pr create --title "Fix login validation" --body '
        '"## Summary\\n- Addresses: Fix login validation\\n- Changed files: app.py\\n\\n'
        '## Validation\\n- Tests passed before human approval.\\n'
        '- Automated review approved the patch.\\n'
        '- Human approval was provided before publication."'
    )


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
