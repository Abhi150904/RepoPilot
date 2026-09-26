from __future__ import annotations

from app.schemas.code_change import CodeChangeSet, FileChange
from app.schemas.plan import ImplementationPlan
from app.schemas.repository import RepositoryContext
from app.tools.git import render_change_set_diff


class CodeWriter:
    """Produces controlled patch proposals from a plan and retrieved context."""

    def propose_changes(
        self,
        issue: str,
        plan: ImplementationPlan,
        repository_context: RepositoryContext | None = None,
    ) -> CodeChangeSet:
        target_files = _select_target_files(plan=plan, repository_context=repository_context)
        originals = _context_previews_by_path(repository_context)
        changes = [
            FileChange(
                path=path,
                action="modify",
                explanation=(
                    "Review this file for the planned fix. Version 3 proposes a "
                    "controlled patch placeholder rather than applying arbitrary code."
                ),
                proposed_content=_build_patch_placeholder(
                    issue=issue,
                    plan=plan,
                    path=path,
                    original_content=originals.get(path, ""),
                ),
            )
            for path in target_files
        ]
        diff = render_change_set_diff(changes=changes, originals=originals)
        return CodeChangeSet(
            summary=f"Prepared controlled patch proposal for {len(changes)} file(s).",
            changes=changes,
            diff=diff,
        )


def _select_target_files(
    plan: ImplementationPlan,
    repository_context: RepositoryContext | None,
    limit: int = 3,
) -> list[str]:
    if repository_context and repository_context.matched_files:
        return [file.path for file in repository_context.matched_files[:limit]]
    return [path for path in plan.files_to_inspect[:limit] if "/" in path or "." in path]


def _context_previews_by_path(
    repository_context: RepositoryContext | None,
) -> dict[str, str]:
    if not repository_context:
        return {}
    return {
        file.path: file.content_preview
        for file in repository_context.matched_files
    }


def _build_patch_placeholder(
    issue: str,
    plan: ImplementationPlan,
    path: str,
    original_content: str,
) -> str:
    comment = _comment_prefix(path)
    steps = "\n".join(f"{comment} - {step}" for step in plan.steps)
    tests = "\n".join(f"{comment} - {test}" for test in plan.tests_required)
    prefix = f"{original_content.rstrip()}\n\n" if original_content.strip() else ""
    return (
        f"{prefix}"
        f"{comment} RepoPilot patch proposal\n"
        f"{comment} Target file: {path}\n"
        f"{comment} Issue: {issue.strip().splitlines()[0] if issue.strip() else 'Unknown issue'}\n"
        f"{comment} Summary: {plan.summary}\n"
        f"{comment}\n"
        f"{comment} Planned steps:\n"
        f"{steps}\n"
        f"{comment}\n"
        f"{comment} Tests to add or update:\n"
        f"{tests}\n"
    )


def _comment_prefix(path: str) -> str:
    if path.endswith((".ts", ".tsx", ".js", ".jsx", ".java", ".go", ".rs", ".c", ".cpp", ".h")):
        return "//"
    return "#"
