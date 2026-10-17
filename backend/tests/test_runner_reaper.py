import importlib.util
import json
from pathlib import Path
import subprocess


def test_reaper_only_removes_expired_labelled_containers(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "runner_reaper", Path(__file__).resolve().parents[2] / "deploy" / "runner_reaper.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[1] == "ps":
            return subprocess.CompletedProcess(args, 0, "aaaaaaaaaaaa\nbbbbbbbbbbbb\nnot-an-id\n")
        if args[1] == "inspect":
            label = "true" if args[-1] == "aaaaaaaaaaaa" else "false"
            return subprocess.CompletedProcess(args, 0, json.dumps([{
                "Created": "2000-01-01T00:00:00Z", "Config": {"Labels": {"repopilot.sandbox": label}}
            }]))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(module.subprocess, "run", run)
    module.reap()
    assert [args for args in calls if args[1] == "rm"] == [["docker", "rm", "--force", "aaaaaaaaaaaa"]]
