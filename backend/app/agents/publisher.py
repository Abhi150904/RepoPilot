from __future__ import annotations

from pathlib import Path
import subprocess

from app.schemas.execution import PublicationPackage, PublishResult
from app.tools.github import GitHubClient, GitHubError


class PublishExecutor:
    """Validates publication readiness without performing side effects."""

    def __init__(self, workspace_path: str | None = None):
        self.workspace_path = workspace_path

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
                branch_name=package.branch_name,
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
            branch_name=package.branch_name,
            blockers=[],
            next_action="run_publication_commands",
        )

    def publish_local(self, package: PublicationPackage) -> PublishResult:
        blockers = _blockers(package)
        if self.workspace_path is None:
            blockers.append("Workspace path is required for local publication.")
        if blockers:
            return PublishResult(
                mode="local",
                status="blocked",
                summary="Local publication found blockers to inspect before publishing.",
                commands=package.commands,
                pr_title=package.pr_title,
                pr_body=package.pr_body,
                pr_url=package.pr_url,
                branch_name=package.branch_name,
                blockers=blockers,
                next_action="inspect_failure",
            )

        root = Path(self.workspace_path)
        executed: list[str] = []
        steps = []
        current_branch = _current_branch(root)
        if current_branch != package.branch_name:
            checkout_args = ["git", "checkout", "-b", package.branch_name]
            checkout_display = f"git checkout -b {package.branch_name}"
            if _branch_exists(root, package.branch_name):
                checkout_args = ["git", "checkout", package.branch_name]
                checkout_display = f"git checkout {package.branch_name}"
            steps.append((checkout_args, checkout_display))
        steps.extend(
            [
                (["git", "add", *package.changed_files], f"git add {' '.join(package.changed_files)}"),
                (["git", "commit", "-m", package.commit_message], f"git commit -m {package.commit_message}"),
            ]
        )
        for args, display in steps:
            completed = _run(args=args, root=root)
            if completed.returncode != 0:
                if args[:2] == ["git", "commit"]:
                    recovered = _recover_existing_local_commit(
                        root=root,
                        package=package,
                        executed=executed,
                    )
                    if recovered is not None:
                        return recovered
                return PublishResult(
                    mode="local",
                    status="blocked",
                    summary=f"Local publication failed while running: {display}",
                    commands=package.commands,
                    executed_commands=executed,
                    pr_title=package.pr_title,
                    pr_body=package.pr_body,
                    pr_url=package.pr_url,
                    branch_name=package.branch_name,
                    blockers=[completed.stderr.strip() or completed.stdout.strip() or "Git command failed."],
                    next_action="inspect_failure",
                )
            executed.append(display)

        sha = _run(args=["git", "rev-parse", "HEAD"], root=root)
        commit_sha = sha.stdout.strip() if sha.returncode == 0 else None
        return PublishResult(
            mode="local",
            status="published",
            summary="Local publication completed. Branch and commit were created locally.",
            commands=package.commands,
            executed_commands=executed,
            pr_title=package.pr_title,
            pr_body=package.pr_body,
            pr_url=package.pr_url,
            commit_sha=commit_sha,
            branch_name=package.branch_name,
            blockers=[],
            next_action="push_branch",
        )

    def push_branch(
        self,
        package: PublicationPackage,
        local_result: PublishResult,
        remote_name: str = "origin",
    ) -> PublishResult:
        blockers = _push_blockers(local_result=local_result)
        if self.workspace_path is None:
            blockers.append("Workspace path is required for pushing the publication branch.")
        if blockers:
            return PublishResult(
                mode="push",
                status="blocked",
                summary="Branch push found blockers to inspect before publishing.",
                commands=package.commands,
                executed_commands=local_result.executed_commands,
                pr_title=package.pr_title,
                pr_body=package.pr_body,
                pr_url=package.pr_url,
                commit_sha=local_result.commit_sha,
                branch_name=local_result.branch_name or package.branch_name,
                remote_name=remote_name,
                blockers=blockers,
                next_action="inspect_failure",
            )

        root = Path(self.workspace_path)
        branch_name = local_result.branch_name or package.branch_name
        display = f"git push -u {remote_name} {branch_name}"
        completed = _run(
            args=["git", "push", "-u", remote_name, branch_name],
            root=root,
        )
        if completed.returncode != 0:
            return PublishResult(
                mode="push",
                status="blocked",
                summary=f"Branch push failed while running: {display}",
                commands=package.commands,
                executed_commands=local_result.executed_commands,
                pr_title=package.pr_title,
                pr_body=package.pr_body,
                pr_url=package.pr_url,
                commit_sha=local_result.commit_sha,
                branch_name=branch_name,
                remote_name=remote_name,
                blockers=[completed.stderr.strip() or completed.stdout.strip() or "Git push failed."],
                next_action="inspect_failure",
            )

        return PublishResult(
            mode="push",
            status="published",
            summary="Publication branch was pushed to the remote.",
            commands=package.commands,
            executed_commands=[*local_result.executed_commands, display],
            pr_title=package.pr_title,
            pr_body=package.pr_body,
            pr_url=package.pr_url,
            commit_sha=local_result.commit_sha,
            branch_name=branch_name,
            remote_name=remote_name,
            blockers=[],
            next_action="open_pull_request",
        )

    def open_pull_request(
        self,
        package: PublicationPackage,
        push_result: PublishResult,
        *,
        repository: str | None,
        github: GitHubClient | None = None,
        base_branch: str = "main",
    ) -> PublishResult:
        blockers = _pr_blockers(push_result=push_result, repository=repository)
        if blockers:
            return PublishResult(
                mode="pr",
                status="blocked",
                summary="Pull request creation found blockers to inspect.",
                commands=package.commands,
                executed_commands=push_result.executed_commands,
                pr_title=package.pr_title,
                pr_body=package.pr_body,
                pr_url=package.pr_url,
                commit_sha=push_result.commit_sha,
                branch_name=push_result.branch_name or package.branch_name,
                remote_name=push_result.remote_name,
                blockers=blockers,
                next_action="inspect_failure",
            )

        branch_name = push_result.branch_name or package.branch_name
        client = github or GitHubClient()
        try:
            pull_request = client.create_pull_request(
                repo=repository or "",
                title=package.pr_title,
                body=package.pr_body,
                head=branch_name,
                base=base_branch,
            )
        except GitHubError as exc:
            return PublishResult(
                mode="pr",
                status="blocked",
                summary="Pull request creation failed.",
                commands=package.commands,
                executed_commands=push_result.executed_commands,
                pr_title=package.pr_title,
                pr_body=package.pr_body,
                pr_url=package.pr_url,
                commit_sha=push_result.commit_sha,
                branch_name=branch_name,
                remote_name=push_result.remote_name,
                blockers=[str(exc)],
                next_action="inspect_failure",
            )

        return PublishResult(
            mode="pr",
            status="published",
            summary="Pull request was opened successfully.",
            commands=package.commands,
            executed_commands=push_result.executed_commands,
            pr_title=package.pr_title,
            pr_body=package.pr_body,
            pr_url=pull_request.url,
            commit_sha=push_result.commit_sha,
            branch_name=branch_name,
            remote_name=push_result.remote_name,
            pull_request=pull_request,
            blockers=[],
            next_action="review_pull_request",
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


def _push_blockers(local_result: PublishResult) -> list[str]:
    blockers: list[str] = []
    if local_result.mode != "local" or local_result.status != "published":
        blockers.append("Local publication must complete before pushing.")
    if not local_result.branch_name:
        blockers.append("Published branch name is missing.")
    if not local_result.commit_sha:
        blockers.append("Published commit SHA is missing.")
    return blockers


def _pr_blockers(push_result: PublishResult, repository: str | None) -> list[str]:
    blockers: list[str] = []
    if push_result.mode != "push" or push_result.status != "published":
        blockers.append("Branch push must complete before opening a pull request.")
    if not push_result.branch_name:
        blockers.append("Pushed branch name is missing.")
    if not push_result.commit_sha:
        blockers.append("Pushed commit SHA is missing.")
    if not repository:
        blockers.append("GitHub repository is required to open a pull request.")
    return blockers


def _run(args: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _current_branch(root: Path) -> str | None:
    completed = _run(args=["git", "branch", "--show-current"], root=root)
    if completed.returncode != 0:
        return None
    branch = completed.stdout.strip()
    return branch or None


def _branch_exists(root: Path, branch_name: str) -> bool:
    completed = _run(args=["git", "rev-parse", "--verify", branch_name], root=root)
    return completed.returncode == 0


def _recover_existing_local_commit(
    *,
    root: Path,
    package: PublicationPackage,
    executed: list[str],
) -> PublishResult | None:
    current_branch = _current_branch(root)
    if current_branch != package.branch_name:
        return None

    subject = _run(args=["git", "log", "-1", "--pretty=%s"], root=root)
    if subject.returncode != 0 or subject.stdout.strip() != package.commit_message:
        return None

    sha = _run(args=["git", "rev-parse", "HEAD"], root=root)
    commit_sha = sha.stdout.strip() if sha.returncode == 0 else None
    if not commit_sha:
        return None

    return PublishResult(
        mode="local",
        status="published",
        summary="Local publication was already completed. Reusing the existing commit.",
        commands=package.commands,
        executed_commands=executed,
        pr_title=package.pr_title,
        pr_body=package.pr_body,
        pr_url=package.pr_url,
        commit_sha=commit_sha,
        branch_name=package.branch_name,
        blockers=[],
        next_action="push_branch",
    )
