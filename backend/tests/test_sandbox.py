from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from app.tools.sandbox import (
    SandboxError,
    _count_pytest_results,
    _truncate_output,
    build_docker_command,
    run_tests_in_docker,
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
