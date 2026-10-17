from __future__ import annotations

import os
import io
import logging
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
from threading import Thread
from uuid import uuid4

from app.schemas.execution import TestResult
from app.core.config import get_settings


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
    settings = get_settings()
    if settings.sandbox_docker_host:
        return _run_remote_tests(
            workspace, command,
            settings.sandbox_image if image == DEFAULT_DOCKER_IMAGE else image,
            settings.sandbox_docker_host, timeout_seconds, output_limit,
        )
    docker_command = build_docker_command(
        workspace_path=workspace,
        command=command,
        image=get_settings().sandbox_image if image == DEFAULT_DOCKER_IMAGE else image,
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


def _workspace_archive(workspace: Path) -> bytes:
    # Never transfer Git credentials, local secrets, links, or special files.
    excluded = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".pytest_tmp"}
    output = io.BytesIO()
    count = 0
    size = 0
    with tarfile.open(fileobj=output, mode="w") as archive:
        for root, directories, files in os.walk(workspace, followlinks=False):
            directories[:] = sorted(name for name in directories if name not in excluded
                                     and not (Path(root) / name).is_symlink())
            for name in sorted(files):
                path = Path(root) / name
                if name == ".env" or name.startswith(".env.") or path.suffix in {".pem", ".key"}:
                    continue
                if path.is_symlink() or not path.is_file():
                    raise SandboxError("Sandbox workspace contains a link or special file.")
                info = archive.gettarinfo(str(path), arcname=path.relative_to(workspace).as_posix())
                if not info.isfile():
                    raise SandboxError("Sandbox workspace contains a non-regular file.")
                count += 1
                size += info.size
                if count > 10_000 or size > 64 * 1024 * 1024:
                    raise SandboxError("Sandbox workspace exceeds the 64 MiB / 10000 file transfer limit.")
                info.uid = info.gid = 65534
                info.uname = info.gname = ""
                info.mode = 0o755 if info.mode & 0o111 else 0o644
                with path.open("rb") as source:
                    archive.addfile(info, source)
    return output.getvalue()


def _run_remote_tests(
    workspace: Path, command: list[str], image: str, host: str,
    timeout_seconds: int, output_limit: int,
) -> TestResult:
    payload = _workspace_archive(workspace)
    name = f"repopilot-test-{uuid4().hex}"
    docker = ["docker", "--host", host]
    # Extraction runs in the sandbox, never on either host. Images must have Python 3.12+.
    bootstrap = (
        "import os,sys,tarfile; "
        "tarfile.open(fileobj=sys.stdin.buffer,mode='r|').extractall('/workspace',filter='data'); "
        "os.execvp(sys.argv[1],sys.argv[1:])"
    )
    args = [*docker, "run", "--rm", "--name", name, "--label", "repopilot.sandbox=true",
            "--pull=never", "--network", "none", "--cpus", "1", "--memory", "1g",
            "--memory-swap", "1g", "--pids-limit", "128", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--read-only", "--user", "65534:65534",
            "--tmpfs", "/workspace:rw,nosuid,nodev,size=256m,mode=1777",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
            "--log-driver", "none", "-e", "HOME=/tmp", "-e", "CI=true",
            "-e", "PYTHONDONTWRITEBYTECODE=1", "-w", "/workspace", "-i",
            "--entrypoint", "python", image, "-c", bootstrap, *command]
    try:
        completed = _run_bounded(args, payload, timeout_seconds, output_limit)
        stdout = _truncate_output(_coerce_output(completed.stdout), output_limit)
        return TestResult(exit_code=completed.returncode, stdout=stdout,
                          stderr=_truncate_output(_coerce_output(completed.stderr), output_limit),
                          timed_out=False, command=command, **_count_pytest_results(stdout))
    except subprocess.TimeoutExpired as exc:
        return TestResult(exit_code=124, stdout=_truncate_output(_coerce_output(exc.stdout), output_limit),
                          stderr=_truncate_output(_coerce_output(exc.stderr), output_limit),
                          timed_out=True, command=command)
    finally:
        # Killing the SSH client alone does not stop its remote container.
        try:
            cleanup = subprocess.run([*docker, "rm", "--force", name], capture_output=True,
                                     timeout=20, check=False)
            if cleanup.returncode and "No such container" not in _coerce_output(cleanup.stderr):
                logging.getLogger(__name__).warning("Remote sandbox cleanup failed; inspect execution host.")
        except (OSError, subprocess.TimeoutExpired):
            logging.getLogger(__name__).warning("Remote sandbox cleanup failed; inspect execution host.")


def _run_bounded(args: list[str], payload: bytes, timeout: int, limit: int) -> subprocess.CompletedProcess:
    buffers = [bytearray(), bytearray()]
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def drain(stream, buffer: bytearray) -> None:
        try:
            while chunk := stream.read(8192):
                buffer.extend(chunk[:max(0, limit + 1 - len(buffer))])
        finally:
            stream.close()

    def feed() -> None:
        try:
            process.stdin.write(payload)
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    threads = [Thread(target=drain, args=(process.stdout, buffers[0]), daemon=True),
               Thread(target=drain, args=(process.stderr, buffers[1]), daemon=True),
               Thread(target=feed, daemon=True)]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        for thread in threads:
            thread.join(timeout=2)
    stdout, stderr = (bytes(buffer) for buffer in buffers)
    if timed_out:
        raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


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
        "--pids-limit",
        "128",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
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
