from __future__ import annotations

import re

from app.schemas.execution import ApprovalDecision, PublicationPackage


class PublicationPreparer:
    """Builds publication-ready metadata without changing git state."""

    def prepare(
        self,
        *,
        issue: str,
        approval: ApprovalDecision,
        changed_files: list[str],
        issue_number: int | None = None,
    ) -> PublicationPackage:
        if not approval.approved:
            raise ValueError("Publication can only be prepared after human approval.")

        title = _first_line(issue)
        short_title = _clean_title(title)
        branch_name = _branch_name(short_title, issue_number)
        commit_message = _commit_message(short_title)
        pr_title = _pr_title(short_title, issue_number)
        pr_body = _pr_body(
            title=title,
            changed_files=changed_files,
            issue_number=issue_number,
        )

        return PublicationPackage(
            status="ready_to_publish",
            branch_name=branch_name,
            commit_message=commit_message,
            pr_title=pr_title,
            pr_body=pr_body,
            changed_files=changed_files,
            next_action="create_pull_request",
        )


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "RepoPilot changes"


def _clean_title(title: str) -> str:
    cleaned = re.sub(r"\s+", " ", title).strip()
    return cleaned.rstrip(".")


def _branch_name(title: str, issue_number: int | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)[:60].strip("-")
    if not slug:
        slug = "repopilot-changes"
    if issue_number is not None:
        return f"issue-{issue_number}-{slug}"
    return slug


def _commit_message(title: str) -> str:
    if not title:
        return "prepare repopilot changes"
    return title[:72].lower()


def _pr_title(title: str, issue_number: int | None) -> str:
    if issue_number is not None:
        return f"Fix #{issue_number}: {title}"
    return title


def _pr_body(
    *,
    title: str,
    changed_files: list[str],
    issue_number: int | None,
) -> str:
    lines = [
        "## Summary",
        f"- Addresses: {title}",
    ]
    if issue_number is not None:
        lines.append(f"- Related issue: #{issue_number}")
    if changed_files:
        lines.append(f"- Changed files: {', '.join(changed_files)}")

    lines.extend(
        [
            "",
            "## Validation",
            "- Tests passed before human approval.",
            "- Automated review approved the patch.",
            "- Human approval was provided before publication.",
        ]
    )
    return "\n".join(lines)
