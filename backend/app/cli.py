from __future__ import annotations

import argparse
import json
import logging
import shlex
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError, OperationalError

from app.api.runs import RunStore
from app.api.schemas import PublishRequest, RunRequest, RunStatusResponse
from app.auth.github_app import GitHubAppService
from app.core.audit import AuditLogger
from app.core.config import (
    deployment_issues,
    deployment_warnings,
    get_settings,
    inline_run_execution_enabled,
)
from app.core.llm_usage import LLMUsageRecorder
from app.evals import retrieval as retrieval_eval
from app.evals import runner as eval_runner
from app.evals.service import EvaluationService
from app.evals.store import EvaluationStore
from app.services.run_service import RepoPilotRunService, RunServiceError


EXAMPLE_ISSUE = "Login endpoint returns 500 when email is missing."


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "config":
        report = _config_report()
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            _print_config_report(report)
        return 0 if report["valid"] else 1
    if args.command == "eval":
        return _run_eval_command(args)
    if args.command == "worker":
        return _run_worker_command(args)

    try:
        request = RunRequest.model_validate(_workflow_input(args))
    except ValidationError as exc:
        raise SystemExit(_validation_message(exc)) from exc

    run = _execute_run(request=request, args=args)
    if run.lifecycle_status == "failed":
        return _print_failed_run(run=run, json_output=args.json)
    if run.response is None:
        raise SystemExit(f"Run ended without a response: {run.lifecycle_status}")

    result = run.response.result

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
    config_parser = subparsers.add_parser("config", help="Inspect RepoPilot configuration.")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    validate_parser = config_subparsers.add_parser(
        "validate",
        help="Validate local RepoPilot configuration.",
    )
    validate_parser.add_argument(
        "--json",
        action="store_true",
        help="Print configuration status as JSON.",
    )
    eval_parser = subparsers.add_parser(
        "eval",
        help="Run RepoPilot eval suites.",
        description="Run workflow eval cases or retrieval benchmarks.",
    )
    eval_parser.add_argument(
        "eval_suite",
        nargs="?",
        choices=["workflow", "retrieval"],
        default="workflow",
        help="Eval suite to run. Defaults to workflow.",
    )
    eval_parser.add_argument(
        "paths",
        nargs="*",
        help="Workflow eval case files or directories. Defaults to backend/tests/fixtures/evals.",
    )
    eval_parser.add_argument(
        "--benchmark",
        default=str(retrieval_eval.DEFAULT_BENCHMARK_PATH),
        help="Retrieval benchmark JSON file.",
    )
    eval_parser.add_argument(
        "--limit",
        type=int,
        default=retrieval_eval.DEFAULT_RETRIEVAL_LIMIT,
        help="Maximum retrieval results to request from each retriever.",
    )
    eval_parser.add_argument(
        "--json",
        action="store_true",
        help="Print eval results as JSON.",
    )
    worker_parser = subparsers.add_parser(
        "worker",
        help="Run queued RepoPilot work from durable storage.",
    )
    worker_subparsers = worker_parser.add_subparsers(dest="worker_command", required=True)
    worker_once_parser = worker_subparsers.add_parser(
        "run-once",
        help="Claim and execute one queued run, then exit.",
    )
    worker_once_parser.add_argument(
        "--json",
        action="store_true",
        help="Print worker result as JSON.",
    )
    eval_once_parser = worker_subparsers.add_parser(
        "eval-once",
        help="Claim and execute one queued evaluation run, then exit.",
    )
    eval_once_parser.add_argument(
        "--json",
        action="store_true",
        help="Print eval worker result as JSON.",
    )
    worker_run_parser = worker_subparsers.add_parser(
        "run",
        help="Continuously claim and execute queued runs.",
    )
    worker_run_parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Seconds to wait between empty queue polls.",
    )
    worker_run_parser.add_argument(
        "--max-runs",
        type=int,
        default=None,
        help="Optional limit for controlled worker runs.",
    )
    worker_run_parser.add_argument(
        "--json",
        action="store_true",
        help="Print worker result as JSON when the loop exits.",
    )
    eval_run_parser = worker_subparsers.add_parser(
        "eval-run",
        help="Continuously claim and execute queued evaluation runs.",
    )
    eval_run_parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Seconds to wait between empty eval queue polls.",
    )
    eval_run_parser.add_argument(
        "--max-runs",
        type=int,
        default=None,
        help="Optional limit for controlled eval worker runs.",
    )
    eval_run_parser.add_argument(
        "--json",
        action="store_true",
        help="Print eval worker result as JSON when the loop exits.",
    )
    _add_run_arguments(parser)

    args = parser.parse_args(argv)
    if args.command not in (None, "run", "config", "eval", "worker"):
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
    if publish_mode:
        if not args.approve:
            raise SystemExit("Publication mode requires --approve.")
        if publish_mode != "dry-run" and not args.workspace and not github_mode:
            raise SystemExit("--publish requires --workspace outside GitHub mode.")
        if publish_mode == "pr" and not args.repo:
            raise SystemExit("--publish pr requires --repo.")

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


def _execute_run(*, request: RunRequest, args: argparse.Namespace) -> RunStatusResponse:
    service = RepoPilotRunService()
    run = service.create_run(request)
    service.execute_run(run.run_id)
    run = service.get_run(run.run_id)
    if run.lifecycle_status == "failed":
        return run

    try:
        if args.approve:
            run = service.approve_run(run.run_id)
        publish_mode = _publish_mode(args)
        if publish_mode:
            run = service.publish_run(
                run.run_id,
                PublishRequest(mode=_publish_request_mode(publish_mode)),
            )
    except RunServiceError as exc:
        raise SystemExit(f"{exc.code}: {exc.message}") from exc
    return run


def _publish_request_mode(mode: str) -> str:
    return "dry_run" if mode == "dry-run" else mode


def _run_worker_command(args: argparse.Namespace) -> int:
    if args.worker_command == "run-once":
        worker = _persistent_run_service()
        worker.recover_stale_runs()
        executed = _worker_run_once(worker)
        _print_worker_result(executed=executed, json_output=args.json)
        return 0
    if args.worker_command == "eval-once":
        worker = _persistent_eval_service()
        worker.recover_interrupted_runs()
        executed = _eval_worker_run_once(worker)
        _print_eval_worker_result(executed=executed, json_output=args.json)
        return 0
    if args.worker_command == "run":
        worker = _persistent_run_service()
        executed = _worker_loop(
            poll_interval=args.poll_interval,
            max_runs=args.max_runs,
            service=worker,
        )
        _print_worker_result(executed=executed, json_output=args.json)
        return 0
    if args.worker_command == "eval-run":
        worker = _persistent_eval_service()
        executed = _eval_worker_loop(
            poll_interval=args.poll_interval,
            max_runs=args.max_runs,
            service=worker,
        )
        _print_eval_worker_result(executed=executed, json_output=args.json)
        return 0
    raise SystemExit(f"Unknown worker command: {args.worker_command}")


def _worker_run_once(service: RepoPilotRunService | None = None) -> RunStatusResponse | None:
    worker = service or _persistent_run_service()
    return worker.execute_next_queued()


def _worker_loop(
    *,
    poll_interval: float,
    max_runs: int | None,
    service: RepoPilotRunService | None = None,
) -> list[RunStatusResponse]:
    if poll_interval < 0:
        raise SystemExit("--poll-interval cannot be negative.")
    if max_runs is not None and max_runs < 1:
        raise SystemExit("--max-runs must be at least 1.")

    worker = service or _persistent_run_service()
    return _poll_worker(
        execute_next=worker.execute_next_queued,
        recover=getattr(worker, "recover_stale_runs", lambda: None),
        poll_interval=poll_interval,
        max_runs=max_runs,
    )


def _eval_worker_run_once(service: EvaluationService | None = None):
    worker = service or _persistent_eval_service()
    return worker.execute_next_queued()


def _eval_worker_loop(
    *,
    poll_interval: float,
    max_runs: int | None,
    service: EvaluationService | None = None,
) -> list:
    if poll_interval < 0:
        raise SystemExit("--poll-interval cannot be negative.")
    if max_runs is not None and max_runs < 1:
        raise SystemExit("--max-runs must be at least 1.")

    worker = service or _persistent_eval_service()
    return _poll_worker(
        execute_next=worker.execute_next_queued,
        recover=getattr(worker, "recover_interrupted_runs", lambda: None),
        poll_interval=poll_interval,
        max_runs=max_runs,
    )


def _poll_worker(*, execute_next: Callable, recover: Callable, poll_interval: float, max_runs: int | None) -> list:
    executed = []
    retry_delay = 1.0
    needs_recovery = True
    last_recovery = 0.0
    try:
        while max_runs is None or len(executed) < max_runs:
            try:
                if needs_recovery or time.monotonic() - last_recovery >= 60:
                    recover()
                    needs_recovery = False
                    last_recovery = time.monotonic()
                run = execute_next()
            except DBAPIError as exc:
                sqlstate = getattr(exc.orig, "sqlstate", None)
                disconnected = exc.connection_invalidated or (
                    isinstance(exc, OperationalError) and (
                        sqlstate is None or sqlstate.startswith("08") or sqlstate in {"57P01", "57P02", "57P03"}
                    )
                )
                if not disconnected:
                    raise
                # Never log connection strings, credentials, or the failed SQL.
                logging.getLogger("repopilot.worker").warning(
                    "Database connection unavailable; retrying queue polling in %.0fs.", retry_delay
                )
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30.0)
                needs_recovery = True
                continue
            retry_delay = 1.0
            if run is None:
                if max_runs is not None:
                    break
                time.sleep(poll_interval)
                continue
            executed.append(run)
    except KeyboardInterrupt:
        pass
    return executed


def _persistent_run_service() -> RepoPilotRunService:
    settings = get_settings()
    github_app = GitHubAppService(settings)
    usage_recorder = LLMUsageRecorder(database_url=settings.database_url)
    return RepoPilotRunService(
        run_store=RunStore(database_url=settings.database_url),
        audit_logger=AuditLogger(database_url=settings.database_url),
        installation_token_resolver=lambda owner: (
            github_app.installation_access_token(installation_id=owner.installation_id)
            if owner.installation_id is not None
            else None
        ),
        llm_usage_recorder=usage_recorder,
    )


def _persistent_eval_service() -> EvaluationService:
    settings = get_settings()
    usage_recorder = LLMUsageRecorder(database_url=settings.database_url)
    return EvaluationService(
        store=EvaluationStore(database_url=settings.database_url),
        settings=settings,
        llm_usage_recorder=usage_recorder,
    )


def _print_worker_result(
    *,
    executed: RunStatusResponse | list[RunStatusResponse] | None,
    json_output: bool,
) -> None:
    runs = executed if isinstance(executed, list) else ([executed] if executed is not None else [])
    if json_output:
        print(
            json.dumps(
                {
                    "executed": len(runs),
                    "runs": [
                        {
                            "run_id": run.run_id,
                            "lifecycle_status": run.lifecycle_status,
                            "publication_status": run.publication_status,
                        }
                        for run in runs
                    ],
                },
                indent=2,
            )
        )
        return
    if not runs:
        print("No queued runs.")
        return
    for run in runs:
        print(f"Executed run {run.run_id}: {run.lifecycle_status}")


def _print_eval_worker_result(
    *,
    executed,
    json_output: bool,
) -> None:
    runs = executed if isinstance(executed, list) else ([executed] if executed is not None else [])
    if json_output:
        print(
            json.dumps(
                {
                    "executed": len(runs),
                    "eval_runs": [
                        {
                            "eval_run_id": run.id,
                            "status": run.status,
                            "suite": run.suite_name,
                        }
                        for run in runs
                    ],
                },
                indent=2,
            )
        )
        return
    if not runs:
        print("No queued evaluation runs.")
        return
    for run in runs:
        print(f"Executed evaluation run {run.id}: {run.status}")


def _run_eval_command(args: argparse.Namespace) -> int:
    if args.eval_suite == "retrieval":
        benchmark = retrieval_eval.load_retrieval_benchmark(Path(args.benchmark))
        result = retrieval_eval.run_retrieval_benchmark(benchmark, limit=args.limit)
        if args.json:
            print(result.model_dump_json(indent=2))
        else:
            retrieval_eval._print_report(result)
        return 0

    input_paths = [Path(path) for path in args.paths] or [eval_runner.DEFAULT_CASE_DIR]
    case_paths = eval_runner.discover_eval_cases(input_paths)
    if not case_paths:
        raise SystemExit("No eval case files found.")

    result = eval_runner.run_eval_suite(case_paths)
    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        eval_runner._print_report(result)
    return 1 if result.failed else 0


def _print_failed_run(*, run: RunStatusResponse, json_output: bool) -> int:
    if json_output:
        print(run.model_dump_json(indent=2))
        return 2

    print("RepoPilot run failed")
    print()
    if run.error is None:
        print("Error: Run failed without an error payload.")
        return 2
    print(f"Code: {run.error.code}")
    print(f"Type: {run.error.type or 'unknown'}")
    print(f"Message: {run.error.message}")
    return 2


def _validation_message(exc: ValidationError) -> str:
    error = exc.errors()[0] if exc.errors() else {}
    message = error.get("msg")
    if isinstance(message, str) and message:
        return message
    return "Invalid run request."


def _config_report() -> dict[str, Any]:
    settings = get_settings()
    provider = settings.llm_provider
    openai_required = provider.lower() == "openai"
    openai_configured = bool(getattr(settings, "openai_api_key", None))
    github_configured = bool(settings.github_token)
    database_configured = bool(getattr(settings, "database_url", None))
    inline_run_execution = inline_run_execution_enabled(settings)
    issues = []
    if openai_required and not openai_configured:
        issues.append("OPENAI_API_KEY is required when REPO_PILOT_LLM_PROVIDER=openai.")
    if provider.lower() not in {"mock", "openai"}:
        issues.append("LLM provider must be openai or mock.")
    issues.extend(deployment_issues(settings))
    warnings = deployment_warnings(settings)

    return {
        "valid": not issues,
        "issues": issues,
        "warnings": warnings,
        "deployment_environment": settings.deployment_environment,
        "hosted_mode": settings.hosted_mode,
        "public_base_url": settings.public_base_url,
        "llm_provider": provider,
        "llm_model": settings.llm_model,
        "openai_api_key": {
            "required": openai_required,
            "configured": openai_configured,
            "status": "configured" if openai_configured else "missing",
        },
        "github_token": {
            "configured": github_configured,
            "status": "configured" if github_configured else "missing",
        },
        "database": {
            "required": settings.hosted_mode,
            "configured": database_configured,
            "status": "configured" if database_configured else "missing",
        },
        "worker": {
            "required": settings.hosted_mode,
            "command": "repopilot worker run",
            "eval_command": "repopilot worker eval-run",
            "queue_configured": database_configured if settings.hosted_mode else True,
        },
        "inline_run_execution": {
            "enabled": inline_run_execution,
            "source": "explicit" if getattr(settings, "inline_run_execution", None) is not None else "default",
        },
        "workspace_root": settings.workspace_root,
        "default_test_command": settings.default_test_command,
        "cli_install": {
            "available": shutil.which("repopilot") is not None,
            "path": shutil.which("repopilot"),
        },
    }


def _print_config_report(report: dict[str, Any]) -> None:
    openai = _dict_or_none(report.get("openai_api_key")) or {}
    github = _dict_or_none(report.get("github_token")) or {}
    database = _dict_or_none(report.get("database")) or {}
    worker = _dict_or_none(report.get("worker")) or {}
    inline_execution = _dict_or_none(report.get("inline_run_execution")) or {}
    cli_install = _dict_or_none(report.get("cli_install")) or {}

    print("RepoPilot config")
    print()
    print(f"Status: {'valid' if report['valid'] else 'invalid'}")
    print(f"Environment: {report['deployment_environment']}")
    print(f"Hosted mode: {'enabled' if report['hosted_mode'] else 'disabled'}")
    if report.get("public_base_url"):
        print(f"Public URL: {report['public_base_url']}")
    print(f"LLM provider: {report['llm_provider']}")
    print(f"LLM model: {report['llm_model']}")
    print(f"OpenAI API key: {openai.get('status', 'unknown')}")
    print(f"GitHub token: {github.get('status', 'unknown')}")
    print(f"Database: {database.get('status', 'unknown')}")
    print(f"Inline run execution: {'enabled' if inline_execution.get('enabled') else 'disabled'}")
    if worker.get("required"):
        print(f"Worker command: {worker.get('command', 'unknown')}")
        print(f"Eval worker command: {worker.get('eval_command', 'unknown')}")
    print(f"Workspace root: {report['workspace_root']}")
    print(f"Default test command: {report['default_test_command']}")
    cli_status = "available" if cli_install.get("available") else "missing"
    print(f"CLI install: {cli_status}")
    if cli_install.get("path"):
        print(f"CLI path: {cli_install['path']}")
    issues = report.get("issues")
    if isinstance(issues, list) and issues:
        print()
        print("Issues:")
        for issue in issues:
            print(f"- {issue}")
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        print()
        print("Warnings:")
        for warning in warnings:
            print(f"- {warning}")


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


if __name__ == "__main__":
    raise SystemExit(main())
