from __future__ import annotations

import re

from app.schemas.execution import ApprovalDecision, GitSafetyReport, PublicationPackage


class PublicationPreparer:
    """Builds publication-ready metadata without changing git state."""

    def prepare(
        self,
        *,
        issue: str,
        approval: ApprovalDecision,
        changed_files: list[str],
        issue_number: int | None = None,
        repository: str | None = None,
        git_safety: GitSafetyReport | None = None,
        branch_name: str | None = None,
        branch_exists: bool = False,
    ) -> PublicationPackage:
        if not approval.approved:
            raise ValueError("Publication can only be prepared after human approval.")

        title = _first_line(issue)
        short_title = _clean_title(title)
        branch_name = branch_name or _branch_name(short_title, issue_number)
        commit_message = _commit_message(short_title)
        pr_title = _pr_title(short_title, issue_number)
        pr_body = _pr_body(
            title=title,
            changed_files=changed_files,
            issue_number=issue_number,
        )
        commands = _commands(
            branch_name=branch_name,
            changed_files=changed_files,
            commit_message=commit_message,
            branch_exists=branch_exists,
        )
        pr_url = _pr_url(repository=repository, branch_name=branch_name)
        pr_command = _pr_command(title=pr_title, body=pr_body)
        pr_instructions = _pr_instructions(repository=repository, pr_url=pr_url)

        return PublicationPackage(
            status="ready_to_publish",
            branch_name=branch_name,
            commit_message=commit_message,
            pr_title=pr_title,
            pr_body=pr_body,
            pr_url=pr_url,
            pr_command=pr_command,
            pr_instructions=pr_instructions,
            changed_files=changed_files,
            commands=commands,
            git_safety=git_safety,
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


def _commands(
    *,
    branch_name: str,
    changed_files: list[str],
    commit_message: str,
    branch_exists: bool = False,
) -> list[str]:
    commands = []
    if not branch_exists:
        commands.append(f"git checkout -b {_quote(branch_name)}")
    if changed_files:
        files = " ".join(_quote(path) for path in changed_files)
        commands.append(f"git add {files}")
    else:
        commands.append("# No changed files were recorded; inspect git status before committing.")
    commands.extend(
        [
            f"git commit -m {_quote(commit_message)}",
            f"git push -u origin {_quote(branch_name)}",
        ]
    )
    return commands


def _pr_url(repository: str | None, branch_name: str) -> str | None:
    if not repository:
        return None
    return f"https://github.com/{repository}/pull/new/{branch_name}"


def _pr_command(*, title: str, body: str) -> str:
    return f"gh pr create --title {_quote(title)} --body {_quote(body)}"


def _pr_instructions(repository: str | None, pr_url: str | None) -> list[str]:
    instructions = [
        "Run the git commands after confirming the git safety report.",
        "Open a pull request with the generated title and body.",
    ]
    if repository and pr_url:
        instructions.append(f"Use the PR URL after pushing the branch: {pr_url}")
    else:
        instructions.append("Use your GitHub repository page to create the PR after pushing the branch.")
    return instructions


def _quote(value: str) -> str:
    escaped = value.replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n")
    return f'"{escaped}"'
