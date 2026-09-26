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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workflow = build_workflow()
    initial_state = {"issue": EXAMPLE_ISSUE}

    if args.repo or args.issue:
        if not args.repo or not args.issue:
            raise SystemExit("Both --repo and --issue are required for GitHub mode.")
        initial_state = {"repository": args.repo, "issue_number": args.issue}

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

    if result.get("diff"):
        print()
        print("Diff:")
        print(result["diff"])


if __name__ == "__main__":
    main()
