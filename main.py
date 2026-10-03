from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


BACKEND_PATH = Path(__file__).resolve().parent / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app.graph.workflow import build_workflow
from app.tools.github import GitHubError


EXAMPLE_ISSUE = "Login endpoint returns 500 when email is missing."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the RepoPilot workflow.")
    parser.add_argument("--repo", help="GitHub repository in owner/name format.")
    parser.add_argument("--issue", type=int, help="GitHub issue number.")
    parser.add_argument(
        "--apply-changes",
        action="store_true",
        help="Apply structured code changes to a local workspace.",
    )
    parser.add_argument(
        "--workspace",
        help="Local workspace path used with --apply-changes.",
    )
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run tests in a Docker sandbox for the given workspace.",
    )
    parser.add_argument(
        "--test-command",
        nargs="+",
        help="Command tokens to run inside the sandbox, for example: python -m pytest.",
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
        help="Mark the reviewed patch as explicitly approved for later publication steps.",
    )
    parser.add_argument(
        "--publish-dry-run",
        action="store_true",
        help="Validate the publication package without running git or GitHub commands.",
    )
    parser.add_argument(
        "--publish-local",
        action="store_true",
        help="Create the publication branch and local commit without pushing or opening a PR.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workflow = build_workflow()
    initial_state = {"issue": EXAMPLE_ISSUE}

    if args.repo or args.issue:
        if not args.repo or not args.issue:
            raise SystemExit("Both --repo and --issue are required for GitHub mode.")
        initial_state = {"repository": args.repo, "issue_number": args.issue}

    if args.workspace and not (args.apply_changes or args.run_tests):
        raise SystemExit("--workspace can only be used with --apply-changes or --run-tests.")
    if args.apply_changes:
        if not args.workspace:
            raise SystemExit("--workspace is required with --apply-changes.")
        initial_state["apply_changes"] = True
        initial_state["workspace_path"] = args.workspace
    if args.run_tests:
        if not args.workspace:
            raise SystemExit("--workspace is required with --run-tests.")
        if args.max_repair_attempts < 0:
            raise SystemExit("--max-repair-attempts cannot be negative.")
        initial_state["run_tests"] = True
        initial_state["workspace_path"] = args.workspace
        initial_state["max_repair_attempts"] = args.max_repair_attempts
    if args.test_command:
        if not args.run_tests:
            raise SystemExit("--test-command can only be used with --run-tests.")
        initial_state["test_command"] = args.test_command
    if args.approve:
        initial_state["approved"] = True
    if args.publish_dry_run:
        if not args.approve:
            raise SystemExit("--publish-dry-run requires --approve.")
        initial_state["publish_dry_run"] = True
    if args.publish_local:
        if not args.approve:
            raise SystemExit("--publish-local requires --approve.")
        if args.publish_dry_run:
            raise SystemExit("--publish-local cannot be combined with --publish-dry-run.")
        if not args.workspace:
            raise SystemExit("--publish-local requires --workspace.")
        initial_state["publish_local"] = True

    try:
        result = workflow.invoke(initial_state)
    except GitHubError as exc:
        raise SystemExit(f"GitHub error: {exc}") from exc

    print("Issue:")
    print(result["issue"])
    print()

    if "issue_url" in result:
        print("GitHub Issue:")
        print(result["issue_url"])
        print()

    print("Analysis:")
    print(json.dumps(result["analysis"], indent=2))
    print()

    if "repository_context" in result:
        print("Repository Context:")
        print(json.dumps(result["repository_context"], indent=2))
        print()

    print("Implementation Plan:")
    print(json.dumps(result["plan"], indent=2))

    if "code_changes" in result:
        print()
        print("Code Changes:")
        print(json.dumps(result["code_changes"], indent=2))

    if "modified_files" in result:
        print()
        print("Modified Files:")
        print(json.dumps(result["modified_files"], indent=2))

    if result.get("diff"):
        print()
        print("Diff:")
        print(result["diff"])

    if "test_result" in result:
        print()
        print("Test Result:")
        print(json.dumps(result["test_result"], indent=2))

    if "test_analysis" in result:
        print()
        print("Test Analysis:")
        print(json.dumps(result["test_analysis"], indent=2))

    if "repair_decision" in result:
        print()
        print("Repair Decision:")
        print(json.dumps(result["repair_decision"], indent=2))

    if "repair_context" in result:
        print()
        print("Repair Context:")
        print(json.dumps(result["repair_context"], indent=2))

    if "review_result" in result:
        print()
        print("Review Result:")
        print(json.dumps(result["review_result"], indent=2))

    if "approval_decision" in result:
        print()
        print("Approval Decision:")
        print(json.dumps(result["approval_decision"], indent=2))

    if "publication_package" in result:
        print()
        print("Publication Package:")
        print(json.dumps(result["publication_package"], indent=2))
        _print_publication_summary(result["publication_package"])

    if "publish_result" in result:
        print()
        print("Publish Dry Run:")
        print(json.dumps(result["publish_result"], indent=2))
        _print_publish_result(result["publish_result"])

    if "repair_attempts" in result:
        print()
        print("Repair Attempts:")
        print(result["repair_attempts"])

    if "run_summary" in result:
        print()
        print("Run Summary:")
        print(json.dumps(result["run_summary"], indent=2))


def _print_publication_summary(package: dict[str, object]) -> None:
    print()
    print("Publication Commands:")
    for command in package.get("commands", []):
        print(command)

    print()
    print("Pull Request:")
    print(f"Title: {package['pr_title']}")
    print("Body:")
    print(package["pr_body"])

    if package.get("pr_url"):
        print()
        print("PR URL:")
        print(package["pr_url"])

    if package.get("pr_command"):
        print()
        print("GitHub CLI Command:")
        print(package["pr_command"])

    git_safety = package.get("git_safety")
    if isinstance(git_safety, dict):
        print()
        print("Git Safety:")
        print(f"Status: {git_safety['status']}")
        print(git_safety["summary"])
        warnings = git_safety.get("warnings", [])
        if warnings:
            print("Warnings:")
            for warning in warnings:
                print(f"- {warning}")


def _print_publish_result(result: dict[str, object]) -> None:
    print()
    print("Publish Status:")
    print(f"{result['status']}: {result['summary']}")
    blockers = result.get("blockers", [])
    if blockers:
        print("Blockers:")
        for blocker in blockers:
            print(f"- {blocker}")


if __name__ == "__main__":
    main()
