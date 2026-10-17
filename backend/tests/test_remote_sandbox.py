import io
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest
from pydantic import ValidationError

from app.core.config import Settings, deployment_issues
from app.tools import sandbox


@pytest.mark.parametrize("host", ["tcp://host:2375", "unix:///var/run/docker.sock", "ssh://user:password@host", "ssh://user@host/path", "ssh://host"])
def test_remote_host_rejects_insecure_or_ambiguous_addresses(host):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, sandbox_docker_host=host)


def test_public_deployment_requires_remote_execution():
    issues = deployment_issues(Settings(_env_file=None, deployment_environment="production"))
    assert any("SSH sandbox" in issue for issue in issues)
    assert any("HTTPS" in issue for issue in issues)


def test_archive_excludes_credentials_and_normalizes_permissions(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret")
    for name in [".env", ".env.production", "private.pem", "secret.key", "test_example.py"]:
        (tmp_path / name).write_text("content")
    with tarfile.open(fileobj=io.BytesIO(sandbox._workspace_archive(tmp_path))) as archive:
        assert archive.getnames() == ["test_example.py"]
        assert archive.getmembers()[0].uid == 65534
        assert archive.getmembers()[0].mode in {0o644, 0o755}


def test_archive_rejects_special_files(tmp_path, monkeypatch):
    (tmp_path / "test.py").write_text("test")
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    with pytest.raises(sandbox.SandboxError, match="special file"):
        sandbox._workspace_archive(tmp_path)


def test_archive_rejects_oversize_workspace_before_reading(tmp_path, monkeypatch):
    (tmp_path / "large.bin").write_bytes(b"x")
    original = tarfile.TarFile.gettarinfo

    def oversized(self, *args, **kwargs):
        info = original(self, *args, **kwargs)
        info.size = 65 * 1024 * 1024
        return info

    monkeypatch.setattr(tarfile.TarFile, "gettarinfo", oversized)
    with pytest.raises(sandbox.SandboxError, match="transfer limit"):
        sandbox._workspace_archive(tmp_path)


def test_remote_timeout_removes_container_without_host_mounts(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, sandbox_docker_host="ssh://sandbox@runner", sandbox_image="pytest:prepared")
    monkeypatch.setattr(sandbox, "get_settings", lambda: settings)
    calls = []

    def bounded(args, payload, timeout, limit):
        calls.append(args)
        assert "-v" not in args
        assert "--read-only" in args
        assert "65534:65534" in args
        assert "--pull=never" in args
        raise subprocess.TimeoutExpired(args, timeout, output=b"partial")

    def cleanup(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(sandbox, "_run_bounded", bounded)
    monkeypatch.setattr(sandbox.subprocess, "run", cleanup)
    result = sandbox.run_tests_in_docker(tmp_path, ["python", "-m", "pytest"], timeout_seconds=1)
    assert result.timed_out
    assert result.stdout == "partial"
    assert calls[-1][:5] == ["docker", "--host", "ssh://sandbox@runner", "rm", "--force"]
    assert calls[-1][-1] == calls[0][calls[0].index("--name") + 1]


def test_bounded_capture_drains_large_output_without_retaining_it():
    result = sandbox._run_bounded(
        [sys.executable, "-c", "import sys; sys.stdin.buffer.read(); print('x'*200000); print('y'*200000,file=sys.stderr)"],
        b"input", 10, 100,
    )
    assert result.returncode == 0
    assert len(result.stdout) == len(result.stderr) == 101


def test_bounded_capture_enforces_timeout():
    with pytest.raises(subprocess.TimeoutExpired):
        sandbox._run_bounded([sys.executable, "-c", "import time; time.sleep(10)"], b"", 1, 100)
