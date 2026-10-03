from __future__ import annotations

from pathlib import Path
import re
import subprocess

from app.schemas.execution import TestResult


class SandboxError(ValueError):
    """Raised when sandbox execution input is invalid."""


DEFAULT_DOCKER_IMAGE = "python:3.11-slim"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_OUTPUT_LIMIT = 12_000


def run_tests_in_docker(
    workspace_path: str | Path,
    command: list[str],
    image: str = DEFAULT_DOCKER_IMAGE,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
) -> TestResult:
    workspace = _resolve_workspace(workspace_path)
    _validate_command(command)
    docker_command = build_docker_command(
        workspace_path=workspace,
        command=command,
        image=image,
    )

    try:
        completed = subprocess.run(
            docker_command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout = _truncate_output(completed.stdout, output_limit)
        stderr = _truncate_output(completed.stderr, output_limit)
        return TestResult(
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            command=command,
            **_count_pytest_results(stdout),
        )
    except subprocess.TimeoutExpired as exc:
        return TestResult(
            exit_code=124,
            stdout=_truncate_output(_coerce_output(exc.stdout), output_limit),
            stderr=_truncate_output(_coerce_output(exc.stderr), output_limit),
            timed_out=True,
            command=command,
        )


def run_tests_locally(
    workspace_path: str | Path,
    command: list[str],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
) -> TestResult:
    workspace = _resolve_workspace(workspace_path)
    _validate_command(command)

    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout = _truncate_output(completed.stdout, output_limit)
        stderr = _truncate_output(completed.stderr, output_limit)
        return TestResult(
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            command=command,
            **_count_pytest_results(stdout),
        )
    except subprocess.TimeoutExpired as exc:
        return TestResult(
            exit_code=124,
            stdout=_truncate_output(_coerce_output(exc.stdout), output_limit),
            stderr=_truncate_output(_coerce_output(exc.stderr), output_limit),
            timed_out=True,
            command=command,
        )


def build_docker_command(
    workspace_path: Path,
    command: list[str],
    image: str = DEFAULT_DOCKER_IMAGE,
) -> list[str]:
    _validate_command(command)
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--cpus",
        "1",
        "--memory",
        "1g",
        "-v",
        f"{workspace_path}:/workspace:rw",
        "-w",
        "/workspace",
        image,
        *command,
    ]


def _resolve_workspace(workspace_path: str | Path) -> Path:
    workspace = Path(workspace_path).resolve()
    if not workspace.exists() or not workspace.is_dir():
        raise SandboxError(f"Workspace does not exist or is not a directory: {workspace}")
    return workspace


def _validate_command(command: list[str]) -> None:
    if not command:
        raise SandboxError("Sandbox command cannot be empty.")
    if any(not token or not token.strip() for token in command):
        raise SandboxError("Sandbox command tokens cannot be empty.")
    blocked_tokens = {"&&", "||", ";", "|", ">", ">>", "<", "$(", "`"}
    for token in command:
        if token in blocked_tokens:
            raise SandboxError(f"Blocked shell token in sandbox command: {token}")


def _truncate_output(output: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(output) <= limit:
        return output
    return output[:limit] + "\n...[truncated]"


def _coerce_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _count_pytest_results(stdout: str) -> dict[str, int]:
    passed = 0
    failed = 0

    passed_match = re.search(r"(\d+)\s+passed", stdout)
    failed_match = re.search(r"(\d+)\s+failed", stdout)

    if passed_match:
        passed = int(passed_match.group(1))
    if failed_match:
        failed = int(failed_match.group(1))

    return {"passed": passed, "failed": failed}
