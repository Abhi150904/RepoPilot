from __future__ import annotations

from app.schemas.execution import PublicationPackage, PublishResult


class PublishExecutor:
    """Validates publication readiness without performing side effects."""

    def dry_run(self, package: PublicationPackage) -> PublishResult:
        blockers = _blockers(package)
        if blockers:
            return PublishResult(
                mode="dry_run",
                status="blocked",
                summary="Publication dry run found blockers to inspect before publishing.",
                commands=package.commands,
                pr_title=package.pr_title,
                pr_body=package.pr_body,
                pr_url=package.pr_url,
                blockers=blockers,
                next_action="inspect_failure",
            )

        return PublishResult(
            mode="dry_run",
            status="ready",
            summary="Publication dry run passed. Commands are ready for explicit execution.",
            commands=package.commands,
            pr_title=package.pr_title,
            pr_body=package.pr_body,
            pr_url=package.pr_url,
            blockers=[],
            next_action="run_publication_commands",
        )


def _blockers(package: PublicationPackage) -> list[str]:
    blockers: list[str] = []

    if not package.changed_files:
        blockers.append("No changed files were recorded for publication.")
    if not package.commands:
        blockers.append("No publication commands were generated.")

    safety = package.git_safety
    if safety is None:
        blockers.append("Git safety report is missing.")
    elif safety.status != "safe":
        blockers.append(f"Git safety status is {safety.status}.")
        blockers.extend(safety.warnings)

    return blockers
