from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from app.tools.sandbox import (
    SandboxError,
    _count_pytest_results,
    _resolve_command,
    _truncate_output,
    build_docker_command,
    run_tests_in_docker,
    run_tests_locally,
)


def test_build_docker_command_uses_restricted_container_options() -> None:
    command = build_docker_command(
        workspace_path=Path("C:/repo").resolve(),
        command=["python", "-m", "pytest"],
        image="python:3.11-slim",
    )

    assert command[:2] == ["docker", "run"]
    assert "--network" in command
    assert "none" in command
    assert "--cpus" in command
    assert "--memory" in command
    assert "-w" in command
    assert "/workspace" in command
    assert command[-3:] == ["python", "-m", "pytest"]


def test_build_docker_command_rejects_shell_tokens() -> None:
    with pytest.raises(SandboxError, match="Blocked shell token"):
        build_docker_command(
            workspace_path=Path(".").resolve(),
            command=["python", "-m", "pytest", "&&", "rm", "-rf", "/"],
        )


def test_truncate_output_marks_truncated_text() -> None:
    output = _truncate_output("abcdef", limit=3)

    assert output == "abc\n...[truncated]"


def test_count_pytest_results_from_stdout() -> None:
    assert _count_pytest_results("===== 3 passed, 1 failed in 0.12s =====") == {
        "passed": 3,
        "failed": 1,
    }


def test_run_tests_in_docker_converts_completed_process(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="===== 2 passed, 1 failed in 0.12s =====",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_tests_in_docker(
        workspace_path=Path("."),
        command=["python", "-m", "pytest"],
    )

    assert result.exit_code == 1
    assert result.passed == 2
    assert result.failed == 1
    assert result.timed_out is False


def test_run_tests_in_docker_converts_timeout(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=1,
            output="partial stdout",
            stderr="partial stderr",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_tests_in_docker(
        workspace_path=Path("."),
        command=["python", "-m", "pytest"],
        timeout_seconds=1,
    )

    assert result.exit_code == 124
    assert result.timed_out is True
    assert "partial stdout" in result.stdout
    assert "partial stderr" in result.stderr


def test_run_tests_locally_installs_node_dependencies_when_missing(tmp_path, monkeypatch) -> None:
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest run"}}\n')
    (tmp_path / "package-lock.json").write_text("{}\n")
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1:] == ["ci"]:
            (tmp_path / "node_modules").mkdir()
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="===== 1 passed in 0.10s =====",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_tests_locally(workspace_path=tmp_path, command=["npm", "test"])

    assert [call[1:] for call in calls] == [["ci"], ["test"]]
    assert all(Path(call[0]).name.lower().startswith("npm") for call in calls)
    assert result.exit_code == 0
    assert result.passed == 1


def test_run_tests_locally_returns_install_failure(tmp_path, monkeypatch) -> None:
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest run"}}\n')

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout="",
            stderr="npm install failed",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_tests_locally(workspace_path=tmp_path, command=["npm", "test"])

    assert result.exit_code == 1
    assert result.command == ["npm", "install"]
    assert "npm install failed" in result.stderr


def test_run_tests_locally_returns_command_not_found(tmp_path, monkeypatch) -> None:
    def fake_run(command, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_tests_locally(workspace_path=tmp_path, command=["missing-tool", "test"])

    assert result.exit_code == 127
    assert result.command == ["missing-tool", "test"]
    assert "Command not found: missing-tool" in result.stderr


def test_resolve_command_uses_windows_command_shim(monkeypatch) -> None:
    def fake_which(executable):
        if executable == "npm.cmd":
            return "C:\\Program Files\\nodejs\\npm.cmd"
        return None

    monkeypatch.setattr("app.tools.sandbox.os.name", "nt")
    monkeypatch.setattr("app.tools.sandbox.shutil.which", fake_which)

    assert _resolve_command(["npm", "test"]) == ["C:\\Program Files\\nodejs\\npm.cmd", "test"]
