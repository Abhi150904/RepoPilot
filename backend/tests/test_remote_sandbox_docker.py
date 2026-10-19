"""Opt-in transport-independent container smoke tests; no cloud or provider calls."""
import os

import pytest

from app.tools.sandbox import _run_remote_tests


pytestmark = pytest.mark.skipif(
    not os.environ.get("REPOPILOT_TEST_DOCKER_HOST"), reason="Local Docker smoke test is opt-in"
)


def test_archive_bootstrap_and_container_boundary(tmp_path):
    (tmp_path / "test_example.py").write_text("def test_ok():\n    assert True\n")
    (tmp_path / ".env").write_text("DO_NOT_TRANSFER=secret\n")
    command = ["python", "-c", (
        "import os,pathlib,subprocess; "
        "assert os.getuid()==65534; "
        "assert not pathlib.Path('/workspace/.env').exists(); "
        "assert not pathlib.Path('/var/run/docker.sock').exists(); "
        "assert 'OPENAI_API_KEY' not in os.environ; "
        "assert pathlib.Path('/workspace/test_example.py').exists(); "
        "raise SystemExit(subprocess.call(['python','-m','pytest','-q']))"
    )]
    result = _run_remote_tests(tmp_path, command, "repopilot-sandbox:staging-check",
                               os.environ["REPOPILOT_TEST_DOCKER_HOST"], 30, 2000)
    assert result.exit_code == 0, result.stderr
    assert result.passed == 1


def test_real_timeout_is_cleaned_up(tmp_path):
    result = _run_remote_tests(tmp_path, ["python", "-c", "import time; time.sleep(30)"],
                               "repopilot-sandbox:staging-check",
                               os.environ["REPOPILOT_TEST_DOCKER_HOST"], 2, 1000)
    assert result.timed_out
