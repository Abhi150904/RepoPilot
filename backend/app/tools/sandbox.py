from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess

from app.schemas.execution import TestResult


class SandboxError(ValueError):
    """Raised when sandbox execution input is invalid."""


DEFAULT_DOCKER_IMAGE = "python:3.11-slim"
DEFAULT_TIMEOUT_SECONDS = 300
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
    finally:
        _cleanup_local_test_artifacts(workspace=workspace, command=command)


def run_tests_locally(
    workspace_path: str | Path,
    command: list[str],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
) -> TestResult:
    workspace = _resolve_workspace(workspace_path)
    _validate_command(command)
    setup_result = _prepare_local_dependencies(
        workspace=workspace,
        timeout_seconds=timeout_seconds,
        output_limit=output_limit,
    )
    if setup_result is not None:
        return setup_result

    try:
        completed = subprocess.run(
            _resolve_command(command),
            cwd=workspace,
            env=_test_environment(),
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
    except FileNotFoundError:
        return _command_not_found_result(command)
    finally:
        _cleanup_local_test_artifacts(workspace=workspace, command=command)


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


def _prepare_local_dependencies(
    *,
    workspace: Path,
    timeout_seconds: int,
    output_limit: int,
) -> TestResult | None:
    if not (workspace / "package.json").exists() or _node_dependencies_ready(workspace):
        return None

    command = ["npm", "ci"] if (workspace / "package-lock.json").exists() else ["npm", "install"]
    try:
        completed = subprocess.run(
            _resolve_command(command),
            cwd=workspace,
            env=_test_environment(),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return TestResult(
            exit_code=124,
            stdout=_truncate_output(_coerce_output(exc.stdout), output_limit),
            stderr=_truncate_output(_coerce_output(exc.stderr), output_limit),
            timed_out=True,
            command=command,
        )
    except FileNotFoundError:
        return _command_not_found_result(command)

    if completed.returncode == 0:
        return None

    return TestResult(
        exit_code=completed.returncode,
        stdout=_truncate_output(completed.stdout, output_limit),
        stderr=_truncate_output(completed.stderr, output_limit),
        timed_out=False,
        command=command,
    )


def _node_dependencies_ready(workspace: Path) -> bool:
    node_modules = workspace / "node_modules"
    if not node_modules.exists():
        return False
    return (node_modules / ".bin").exists()


def _resolve_command(command: list[str]) -> list[str]:
    executable = command[0]
    resolved = shutil.which(executable)
    if resolved:
        return [resolved, *command[1:]]
    if os.name == "nt" and not executable.lower().endswith((".exe", ".cmd", ".bat")):
        for candidate in (f"{executable}.cmd", f"{executable}.exe", f"{executable}.bat"):
            resolved_candidate = shutil.which(candidate)
            if resolved_candidate:
                return [resolved_candidate, *command[1:]]
        npm_cmd = Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "nodejs" / f"{executable}.cmd"
        if executable.lower() == "npm" and npm_cmd.exists():
            return [str(npm_cmd), *command[1:]]
    return command


def _test_environment() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("CI", "true")
    env.setdefault("NO_COLOR", "1")
    return env


def _command_not_found_result(command: list[str]) -> TestResult:
    return TestResult(
        exit_code=127,
        stdout="",
        stderr=(
            f"Command not found: {command[0]}. "
            "Install it or add it to the PATH used by the RepoPilot backend process."
        ),
        timed_out=False,
        command=command,
    )


def _cleanup_local_test_artifacts(*, workspace: Path, command: list[str]) -> None:
    if not _uses_repo_pytest_temp(command):
        return
    artifact_path = (workspace / ".pytest_tmp").resolve()
    try:
        artifact_path.relative_to(workspace)
    except ValueError:
        return
    if artifact_path.exists():
        shutil.rmtree(artifact_path, ignore_errors=True)


def _uses_repo_pytest_temp(command: list[str]) -> bool:
    for index, token in enumerate(command):
        if token == "--basetemp=.pytest_tmp" or token == "--basetemp=./.pytest_tmp":
            return True
        if token == "--basetemp" and index + 1 < len(command):
            return command[index + 1] in {".pytest_tmp", "./.pytest_tmp"}
    return False
