from __future__ import annotations

import argparse
import json
import shlex
from typing import Any, Sequence

from app.core.config import get_settings
from app.graph.workflow import build_workflow
from app.tools.github import GitHubError


EXAMPLE_ISSUE = "Login endpoint returns 500 when email is missing."


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = build_workflow().invoke(_workflow_input(args))
    except GitHubError as exc:
        raise SystemExit(f"GitHub error: {exc}") from exc

    if args.json:
        print(json.dumps(result, indent=2))
        return _exit_code(result)

    if args.verbose:
        _print_result(result)
    else:
        _print_summary(result)
    return _exit_code(result)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="repopilot",
        description="Run the RepoPilot issue-to-change workflow.",
        epilog=(
            "Examples:\n"
            "  repopilot run --repo Abhi150904/Wandr --issue 16\n"
            "  repopilot run --repo Abhi150904/Wandr --issue 16 --apply --test\n"
            "  repopilot run --repo Abhi150904/Wandr --issue 16 --apply --test --approve --dry-run\n"
            "  repopilot run --issue-text \"Login fails when email is missing\" --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="repopilot 0.1.0")

    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser(
        "run",
        help="Run RepoPilot for an issue.",
        epilog=parser.epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_run_arguments(run_parser)
    _add_run_arguments(parser)

    args = parser.parse_args(argv)
    if args.command not in (None, "run"):
        parser.error(f"Unknown command: {args.command}")
    return args


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", help="GitHub repository in owner/name format.")
    parser.add_argument("--issue", type=int, help="GitHub issue number.")
    parser.add_argument(
        "--issue-text",
        help="Plain issue text for local planning mode. Defaults to a sample issue.",
    )
    parser.add_argument(
        "--apply",
        "--apply-changes",
        dest="apply_changes",
        action="store_true",
        help="Apply structured code changes to a workspace.",
    )
    parser.add_argument(
        "--workspace",
        help="Local workspace path. Optional in GitHub mode because RepoPilot can create one.",
    )
    parser.add_argument(
        "--test",
        "--run-tests",
        dest="run_tests",
        action="store_true",
        help="Run tests for the workspace.",
    )
    parser.add_argument(
        "--test-command",
        nargs=argparse.REMAINDER,
        help="Command tokens to run, for example: --test-command python -m pytest.",
    )
    parser.add_argument(
        "--max-repair-attempts",
        type=int,
        default=1,
        help="Maximum automated repair retries after test failures.",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Mark the reviewed patch as explicitly approved for publication.",
    )
    parser.add_argument(
        "--publish",
        choices=["dry-run", "local", "push", "pr"],
        help="Publication mode to run after approval.",
    )
    parser.add_argument(
        "--publish-dry-run",
        action="store_true",
        help="Validate the publication package without git or GitHub side effects.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias for --publish dry-run.",
    )
    parser.add_argument(
        "--publish-local",
        action="store_true",
        help="Create the publication branch and local commit.",
    )
    parser.add_argument(
        "--publish-push",
        action="store_true",
        help="Create the local publication commit and push its branch.",
    )
    parser.add_argument(
        "--publish-pr",
        action="store_true",
        help="Create the local commit, push its branch, and open a GitHub PR.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full workflow result as JSON.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed workflow sections instead of the compact summary.",
    )


def _workflow_input(args: argparse.Namespace) -> dict[str, Any]:
    data: dict[str, Any] = {"issue": args.issue_text or EXAMPLE_ISSUE}
    github_mode = bool(args.repo or args.issue)

    if github_mode:
        if not args.repo or not args.issue:
            raise SystemExit("Both --repo and --issue are required for GitHub mode.")
        data = {"repository": args.repo, "issue_number": args.issue}

    if args.workspace and not (args.apply_changes or args.run_tests):
        raise SystemExit("--workspace can only be used with --apply or --test.")
    if args.max_repair_attempts < 0:
        raise SystemExit("--max-repair-attempts cannot be negative.")

    if args.apply_changes:
        if not args.workspace and not github_mode:
            raise SystemExit("--workspace is required with --apply.")
        data["apply_changes"] = True
        if args.workspace:
            data["workspace_path"] = args.workspace

    if args.run_tests:
        if not args.workspace and not github_mode:
            raise SystemExit("--workspace is required with --test.")
        data["run_tests"] = True
        data["max_repair_attempts"] = args.max_repair_attempts
        if args.workspace:
            data["workspace_path"] = args.workspace

    if args.test_command:
        if not args.run_tests:
            raise SystemExit("--test-command can only be used with --test.")
        data["test_command"] = args.test_command
    elif args.run_tests:
        data["test_command"] = _default_test_command()

    publish_mode = _publish_mode(args)
    if args.approve:
        data["approved"] = True
    if publish_mode:
        if not args.approve:
            raise SystemExit("Publication mode requires --approve.")
        if publish_mode != "dry-run" and not args.workspace and not github_mode:
            raise SystemExit("--publish requires --workspace outside GitHub mode.")
        if publish_mode == "pr" and not args.repo:
            raise SystemExit("--publish pr requires --repo.")
        data[_publish_state_key(publish_mode)] = True

    return data


def _publish_mode(args: argparse.Namespace) -> str | None:
    explicit_modes = [
        mode
        for mode, enabled in [
            ("dry-run", args.dry_run),
            ("dry-run", args.publish_dry_run),
            ("local", args.publish_local),
            ("push", args.publish_push),
            ("pr", args.publish_pr),
        ]
        if enabled
    ]
    if args.publish:
        explicit_modes.append(args.publish)
    if len(explicit_modes) > 1:
        raise SystemExit("Choose only one publication mode.")
    return explicit_modes[0] if explicit_modes else None


def _default_test_command() -> list[str]:
    command = get_settings().default_test_command.strip()
    if not command:
        raise SystemExit("Default test command cannot be empty.")
    return shlex.split(command)


def _publish_state_key(mode: str) -> str:
    return {
        "dry-run": "publish_dry_run",
        "local": "publish_local",
        "push": "publish_push",
        "pr": "publish_pr",
    }[mode]


def _print_result(result: dict[str, Any]) -> None:
    _print_section("Issue", result.get("issue"))
    _print_section("GitHub Issue", result.get("issue_url"))
    _print_json_section("Analysis", result.get("analysis"))
    _print_json_section("Repository Context", result.get("repository_context"))
    _print_json_section("Implementation Plan", result.get("plan"))
    _print_json_section("Code Changes", result.get("code_changes"))
    _print_json_section("Modified Files", result.get("modified_files"))
    _print_json_section("Run Workspace", result.get("run_workspace"))
    _print_section("Diff", result.get("diff"))
    _print_json_section("Test Result", result.get("test_result"))
    _print_json_section("Test Analysis", result.get("test_analysis"))
    _print_json_section("Repair Decision", result.get("repair_decision"))
    _print_json_section("Repair Context", result.get("repair_context"))
    _print_json_section("Review Result", result.get("review_result"))
    _print_json_section("Approval Decision", result.get("approval_decision"))

    package = result.get("publication_package")
    if isinstance(package, dict):
        _print_json_section("Publication Package", package)
        _print_publication_summary(package)

    publish_result = result.get("publish_result")
    if isinstance(publish_result, dict):
        _print_json_section("Publish Result", publish_result)
        _print_publish_result(publish_result)

    _print_section("Repair Attempts", result.get("repair_attempts"))
    _print_json_section("Run Summary", result.get("run_summary"))


def _print_summary(result: dict[str, Any]) -> None:
    summary = result.get("run_summary")
    summary_data = summary if isinstance(summary, dict) else {}
    artifacts = _summary_artifacts(result=result, summary=summary_data)

    print("RepoPilot run complete")
    print()
    print(f"Status: {summary_data.get('status', 'unknown')}")
    print(f"Summary: {summary_data.get('summary', 'No summary available.')}")
    print(f"Next action: {summary_data.get('next_action', 'inspect_failure')}")

    issue_url = result.get("issue_url")
    if isinstance(issue_url, str) and issue_url:
        print(f"Issue: {issue_url}")

    changed_files = artifacts["changed_files"]
    if changed_files:
        print()
        print("Changed files:")
        for path in changed_files:
            print(f"- {path}")

    tests = artifacts["tests"]
    if tests:
        print()
        print(f"Tests: {tests}")

    branch_name = artifacts["branch_name"]
    if branch_name:
        print(f"Branch: {branch_name}")

    pr_url = artifacts["pr_url"]
    if pr_url:
        print(f"PR: {pr_url}")

    publish_status = artifacts["publish_status"]
    if publish_status:
        print(f"Publish: {publish_status}")


def _summary_artifacts(
    *,
    result: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    publish_result = _dict_or_none(result.get("publish_result"))
    run_workspace = _dict_or_none(result.get("run_workspace"))
    publication_package = _dict_or_none(result.get("publication_package"))
    changed_files = _string_list(result.get("modified_files"))
    tests = _tests_summary(result=result, summary=summary)

    return {
        "changed_files": changed_files,
        "tests": tests,
        "branch_name": _first_string(
            publish_result.get("branch_name") if publish_result else None,
            run_workspace.get("branch_name") if run_workspace else None,
            publication_package.get("branch_name") if publication_package else None,
        ),
        "pr_url": _first_string(
            publish_result.get("pr_url") if publish_result else None,
            publication_package.get("pr_url") if publication_package else None,
        ),
        "publish_status": _publish_status(publish_result),
    }


def _tests_summary(*, result: dict[str, Any], summary: dict[str, Any]) -> str | None:
    tests_passed = summary.get("tests_passed")
    if tests_passed is True:
        return "passed"
    if tests_passed is False:
        return "failed"

    test_analysis = _dict_or_none(result.get("test_analysis"))
    if test_analysis:
        status = test_analysis.get("status")
        if isinstance(status, str) and status:
            return status
    return None


def _publish_status(publish_result: dict[str, Any] | None) -> str | None:
    if not publish_result:
        return None
    status = publish_result.get("status")
    summary = publish_result.get("summary")
    if isinstance(status, str) and isinstance(summary, str):
        return f"{status}: {summary}"
    if isinstance(status, str):
        return status
    return None


def _exit_code(result: dict[str, Any]) -> int:
    summary = _dict_or_none(result.get("run_summary"))
    status = summary.get("status") if summary else None
    if status in {"review_failed", "repair_failed", "needs_human"}:
        return 2

    publish_result = _dict_or_none(result.get("publish_result"))
    if publish_result and publish_result.get("status") == "blocked":
        return 2

    test_analysis = _dict_or_none(result.get("test_analysis"))
    if test_analysis and test_analysis.get("status") in {"failed", "timed_out", "error"}:
        return 2

    return 0


def _print_section(title: str, value: object) -> None:
    if value in (None, "", []):
        return
    print(title + ":")
    print(value)
    print()


def _print_json_section(title: str, value: object) -> None:
    if value in (None, "", []):
        return
    print(title + ":")
    print(json.dumps(value, indent=2))
    print()


def _print_publication_summary(package: dict[str, object]) -> None:
    commands = package.get("commands")
    if isinstance(commands, list) and commands:
        print("Publication Commands:")
        for command in commands:
            print(command)
        print()

    print("Pull Request:")
    print(f"Title: {package['pr_title']}")
    print("Body:")
    print(package["pr_body"])
    print()

    _print_section("PR URL", package.get("pr_url"))
    _print_section("GitHub CLI Command", package.get("pr_command"))

    git_safety = package.get("git_safety")
    if isinstance(git_safety, dict):
        print("Git Safety:")
        print(f"Status: {git_safety['status']}")
        print(git_safety["summary"])
        warnings = git_safety.get("warnings", [])
        if warnings:
            print("Warnings:")
            for warning in warnings:
                print(f"- {warning}")
        print()


def _print_publish_result(result: dict[str, object]) -> None:
    print("Publish Status:")
    print(f"{result['status']}: {result['summary']}")
    blockers = result.get("blockers", [])
    if blockers:
        print("Blockers:")
        for blocker in blockers:
            print(f"- {blocker}")
    print()


def _dict_or_none(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _first_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None
