from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

from app.core.config import Settings


def _minimal_result() -> dict[str, object]:
    return {
        "issue": "Login endpoint returns 500 when email is missing.",
        "analysis": {
            "summary": "Missing email is not validated.",
            "suspected_area": "request validation",
            "likely_cause": "Missing guard clause.",
            "risk_level": "medium",
        },
        "plan": {
            "summary": "Add missing email validation.",
            "steps": ["Add a guard clause."],
            "files_to_inspect": ["app.py"],
            "tests_required": ["missing email returns 400"],
        },
        "run_summary": {
            "status": "changes_applied",
            "summary": "Code changes were applied.",
            "tests_passed": None,
            "repair_attempts": 0,
            "metrics": None,
            "next_action": "commit_changes",
        },
    }


def _failed_result() -> dict[str, object]:
    result = _minimal_result()
    result["test_analysis"] = {
        "status": "failed",
        "summary": "Tests failed.",
        "failure_reason": "Assertion failed.",
        "next_action": "rerun_tests",
    }
    result["run_summary"] = {
        "status": "repair_failed",
        "summary": "Tests still fail after repair attempts.",
        "tests_passed": False,
        "repair_attempts": 1,
        "metrics": None,
        "next_action": "inspect_failure",
    }
    return result


def test_cli_run_subcommand_builds_github_apply_state(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")
    captured = {}

    class FakeWorkflow:
        def invoke(self, state):
            captured["state"] = state
            return {
                **_minimal_result(),
                "run_workspace": {
                    "repo": "example/demo",
                    "source_path": ".repopilot/workspaces/example__demo",
                    "path": ".repopilot/workspaces/example__demo/runs/repopilot/issue-16",
                    "branch_name": "repopilot/issue-16",
                    "base_ref": "HEAD",
                },
            }

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--repo", "example/demo", "--issue", "16", "--apply"])

    assert captured["state"] == {
        "repository": "example/demo",
        "issue_number": 16,
        "apply_changes": True,
        "max_repair_attempts": 1,
        "_run_id": captured["state"]["_run_id"],
    }
    assert captured["state"]["_run_id"]
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "RepoPilot run complete" in output
    assert "Status: changes_applied" in output
    assert "Branch: repopilot/issue-16" in output
    assert "Run Workspace:" not in output


def test_cli_legacy_root_flags_still_work(monkeypatch) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")
    captured = {}

    class FakeWorkflow:
        def invoke(self, state):
            captured["state"] = state
            return _minimal_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(
        [
            "--repo",
            "example/demo",
            "--issue",
            "16",
            "--run-tests",
            "--test-command",
            "python",
            "-m",
            "pytest",
        ]
    )

    assert exit_code == 0
    assert captured["state"] == {
        "repository": "example/demo",
        "issue_number": 16,
        "run_tests": True,
        "test_runner": "local",
        "max_repair_attempts": 1,
        "test_command": ["python", "-m", "pytest"],
        "_run_id": captured["state"]["_run_id"],
    }
    assert captured["state"]["_run_id"]


def test_cli_local_apply_requires_workspace() -> None:
    cli = importlib.import_module("app.cli")

    try:
        cli.main(["run", "--apply"])
    except SystemExit as exc:
        assert "--workspace is required with --apply" in str(exc)
    else:
        raise AssertionError("Expected local apply runs to require --workspace.")


def test_cli_publish_shorthand_uses_hardened_service_lifecycle(monkeypatch) -> None:
    cli = importlib.import_module("app.cli")
    captured = {}

    def completed_run(result: dict[str, object] | None = None):
        return SimpleNamespace(
            run_id="run-1",
            lifecycle_status="completed",
            response=SimpleNamespace(result=result or _minimal_result()),
            error=None,
        )

    class FakeService:
        def create_run(self, request):
            captured["request"] = request
            return SimpleNamespace(run_id="run-1")

        def execute_run(self, run_id):
            captured["executed"] = run_id

        def get_run(self, run_id):
            captured["got"] = run_id
            return completed_run()

        def approve_run(self, run_id):
            captured["approved"] = run_id
            return completed_run()

        def publish_run(self, run_id, request):
            captured["published"] = (run_id, request.mode)
            result = {
                **_minimal_result(),
                "publish_result": {
                    "status": "published",
                    "summary": "Dry run passed.",
                    "mode": request.mode,
                },
            }
            return completed_run(result)

    monkeypatch.setattr(cli, "RepoPilotRunService", FakeService)

    exit_code = cli.main(
        [
            "run",
            "--repo",
            "example/demo",
            "--issue",
            "16",
            "--apply",
            "--test",
            "--approve",
            "--publish",
            "dry-run",
        ]
    )

    assert exit_code == 0
    request = captured["request"]
    assert request.repository == "example/demo"
    assert request.issue_number == 16
    assert request.apply_changes is True
    assert request.run_tests is True
    assert request.approved is False
    assert request.publish_dry_run is False
    assert request.publish_local is False
    assert request.publish_push is False
    assert request.publish_pr is False
    assert captured["executed"] == "run-1"
    assert captured["approved"] == "run-1"
    assert captured["published"] == ("run-1", "dry_run")


def test_cli_test_uses_configured_default_command(monkeypatch) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")
    captured = {}

    class FakeWorkflow:
        def invoke(self, state):
            captured["state"] = state
            return _minimal_result()

    monkeypatch.setenv("REPO_PILOT_DEFAULT_TEST_COMMAND", "pytest -q")
    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--repo", "example/demo", "--issue", "16", "--test"])

    assert exit_code == 0
    assert captured["state"]["test_command"] == ["pytest", "-q"]


def test_cli_dry_run_alias_uses_publish_service_mode(monkeypatch) -> None:
    cli = importlib.import_module("app.cli")
    captured = {}

    def completed_run():
        return SimpleNamespace(
            run_id="run-1",
            lifecycle_status="completed",
            response=SimpleNamespace(result=_minimal_result()),
            error=None,
        )

    class FakeService:
        def create_run(self, request):
            captured["request"] = request
            return SimpleNamespace(run_id="run-1")

        def execute_run(self, run_id):
            pass

        def get_run(self, run_id):
            return completed_run()

        def approve_run(self, run_id):
            captured["approved"] = run_id
            return completed_run()

        def publish_run(self, run_id, request):
            captured["published"] = request.mode
            return completed_run()

    monkeypatch.setattr(cli, "RepoPilotRunService", FakeService)

    exit_code = cli.main(
        [
            "run",
            "--repo",
            "example/demo",
            "--issue",
            "16",
            "--apply",
            "--test",
            "--approve",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    request = captured["request"]
    assert request.approved is False
    assert request.publish_dry_run is False
    assert captured["approved"] == "run-1"
    assert captured["published"] == "dry_run"


def test_cli_rejects_publication_without_approval() -> None:
    cli = importlib.import_module("app.cli")

    try:
        cli.main(["run", "--repo", "example/demo", "--issue", "16", "--dry-run"])
    except SystemExit as exc:
        assert "Publication mode requires --approve" in str(exc)
    else:
        raise AssertionError("Expected publication mode to require approval.")


def test_cli_json_output_prints_full_result(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")

    class FakeWorkflow:
        def invoke(self, state):
            return _minimal_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--issue-text", "Fix login validation", "--json"])

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body["issue"] == "Login endpoint returns 500 when email is missing."
    assert body["run_summary"]["next_action"] == "commit_changes"


def test_cli_verbose_output_prints_detailed_sections(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")

    class FakeWorkflow:
        def invoke(self, state):
            return _minimal_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--issue-text", "Fix login validation", "--verbose"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Analysis:" in output
    assert "Implementation Plan:" in output


def test_cli_returns_nonzero_for_failed_run(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    service_module = importlib.import_module("app.services.run_service")

    class FakeWorkflow:
        def invoke(self, state):
            return _failed_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())

    exit_code = cli.main(["run", "--issue-text", "Fix login validation"])

    output = capsys.readouterr().out
    assert exit_code == 2
    assert "Status: repair_failed" in output
    assert "Tests: failed" in output


def test_main_wrapper_run_help_smoke() -> None:
    completed = subprocess.run(
        [sys.executable, "main.py", "run", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "usage: repopilot run" in completed.stdout
    assert "--dry-run" in completed.stdout
    assert "Examples:" in completed.stdout


def test_packaging_exposes_console_script_and_backend_package() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["repopilot"] == "app.cli:main"
    assert pyproject["project"]["scripts"]["repopilot-api-dev"] == "app.dev_server:main"
    assert pyproject["tool"]["setuptools"]["package-dir"] == {"": "backend"}
    assert pyproject["tool"]["setuptools"]["packages"]["find"]["where"] == ["backend"]


def test_cli_config_validate_prints_human_report(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")

    monkeypatch.setenv("REPO_PILOT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("REPO_PILOT_LLM_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.delenv("REPO_PILOT_HOSTED_MODE", raising=False)
    monkeypatch.delenv("REPOPILOT_HOSTED_MODE", raising=False)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(cli.shutil, "which", lambda command: "C:/tools/repopilot.exe")

    exit_code = cli.main(["config", "validate"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "RepoPilot config" in output
    assert "Status: valid" in output
    assert "Environment: local" in output
    assert "Hosted mode: disabled" in output
    assert "LLM provider: openai" in output
    assert "LLM model: gpt-5.4-mini" in output
    assert "OpenAI API key: configured" in output
    assert "GitHub token: configured" in output
    assert "Database: missing" in output
    assert "Inline run execution: enabled" in output
    assert "CLI install: available" in output


def test_cli_config_validate_json_reports_settings(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")

    monkeypatch.setenv("REPO_PILOT_LLM_PROVIDER", "openai")
    monkeypatch.setenv("REPO_PILOT_LLM_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.delenv("REPO_PILOT_HOSTED_MODE", raising=False)
    monkeypatch.delenv("REPOPILOT_HOSTED_MODE", raising=False)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(cli.shutil, "which", lambda command: None)

    exit_code = cli.main(["config", "validate", "--json"])

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body["valid"] is True
    assert body["issues"] == []
    assert body["warnings"] == []
    assert body["deployment_environment"] == "local"
    assert body["hosted_mode"] is False
    assert body["public_base_url"] is None
    assert body["llm_provider"] == "openai"
    assert body["llm_model"] == "gpt-5.4-mini"
    assert body["openai_api_key"] == {
        "required": True,
        "configured": True,
        "status": "configured",
    }
    assert body["github_token"]["status"] == "configured"
    assert body["database"] == {
        "required": False,
        "configured": False,
        "status": "missing",
    }
    assert body["worker"] == {
        "required": False,
        "command": "repopilot worker run",
        "eval_command": "repopilot worker eval-run",
        "queue_configured": True,
    }
    assert body["inline_run_execution"] == {
        "enabled": True,
        "source": "default",
    }
    assert body["cli_install"] == {"available": False, "path": None}


def test_cli_config_validate_reports_hosted_worker_shape(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    monkeypatch.setenv("REPO_PILOT_LLM_PROVIDER", "mock")

    monkeypatch.setenv("REPO_PILOT_HOSTED_MODE", "true")
    monkeypatch.setenv("REPO_PILOT_PUBLIC_BASE_URL", "https://repopilot.example")
    monkeypatch.setenv("REPO_PILOT_CORS_ORIGINS", "https://repopilot.example")
    monkeypatch.setenv("REPOPILOT_DATABASE_URL", "postgresql+psycopg://example")
    monkeypatch.setenv("REPO_PILOT_GITHUB_CLIENT_ID", "client-id")
    monkeypatch.setenv("REPO_PILOT_GITHUB_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("REPO_PILOT_GITHUB_APP_ID", "123")
    monkeypatch.setenv("REPO_PILOT_GITHUB_APP_PRIVATE_KEY", "private-key")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("REPOPILOT_GITHUB_TOKEN", raising=False)

    exit_code = cli.main(["config", "validate", "--json"])

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body["valid"] is True
    assert body["database"]["status"] == "configured"
    assert body["worker"] == {
        "required": True,
        "command": "repopilot worker run",
        "eval_command": "repopilot worker eval-run",
        "queue_configured": True,
    }
    assert body["inline_run_execution"] == {
        "enabled": False,
        "source": "default",
    }
    assert any("separate worker process" in warning for warning in body["warnings"])


def test_cli_config_validate_returns_nonzero_for_missing_required_openai_key(
    monkeypatch,
    capsys,
) -> None:
    cli = importlib.import_module("app.cli")

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: SimpleNamespace(
            llm_provider="openai",
            llm_model="gpt-5.4-mini",
            openai_api_key=None,
            github_token=None,
            deployment_environment="local",
            hosted_mode=False,
            public_base_url=None,
            database_url=None,
            inline_run_execution=None,
            cors_origins="http://localhost:3000",
            workspace_root=".repopilot/workspaces",
            default_test_command="python -m pytest",
        ),
    )

    exit_code = cli.main(["config", "validate"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Status: invalid" in output
    assert "OPENAI_API_KEY is required" in output


def test_cli_config_validate_rejects_hosted_personal_token(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")

    monkeypatch.setenv("REPO_PILOT_HOSTED_MODE", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")

    exit_code = cli.main(["config", "validate", "--json"])

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert body["valid"] is False
    assert "github-secret" not in json.dumps(body)
    assert any("personal GitHub token" in issue for issue in body["issues"])
    assert any("GitHub App/OAuth" in warning for warning in body["warnings"])


def test_cli_config_validate_rejects_hosted_wildcard_cors(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")

    monkeypatch.setenv("REPO_PILOT_HOSTED_MODE", "true")
    monkeypatch.setenv("REPO_PILOT_CORS_ORIGINS", "*")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("REPOPILOT_GITHUB_TOKEN", raising=False)

    exit_code = cli.main(["config", "validate"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Status: invalid" in output
    assert "REPO_PILOT_CORS_ORIGINS cannot include * in hosted mode." in output


def test_cli_worker_run_once_reports_no_queued_runs(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")

    class FakeService:
        def recover_stale_runs(self):
            return 0

        def execute_next_queued(self):
            return None

    monkeypatch.setattr(cli, "_persistent_run_service", lambda: FakeService())

    exit_code = cli.main(["worker", "run-once"])

    assert exit_code == 0
    assert "No queued runs." in capsys.readouterr().out


def test_cli_worker_run_once_claims_one_run(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")

    class FakeService:
        def recover_stale_runs(self):
            return 0

        def execute_next_queued(self):
            return SimpleNamespace(
                run_id="run-1",
                lifecycle_status="completed",
                publication_status="not_started",
            )

    monkeypatch.setattr(cli, "_persistent_run_service", lambda: FakeService())

    exit_code = cli.main(["worker", "run-once", "--json"])

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body == {
        "executed": 1,
        "runs": [
            {
                "run_id": "run-1",
                "lifecycle_status": "completed",
                "publication_status": "not_started",
            }
        ],
    }


def test_cli_worker_run_loop_respects_max_runs(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    calls = {"count": 0}

    class FakeService:
        def recover_stale_runs(self):
            return 0

        def execute_next_queued(self):
            calls["count"] += 1
            return SimpleNamespace(
                run_id=f"run-{calls['count']}",
                lifecycle_status="completed",
                publication_status="not_started",
            )

    monkeypatch.setattr(cli, "_persistent_run_service", lambda: FakeService())

    exit_code = cli.main(["worker", "run", "--max-runs", "2"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert calls["count"] == 2
    assert "Executed run run-1: completed" in output
    assert "Executed run run-2: completed" in output


def test_cli_eval_worker_run_once_claims_one_eval(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")

    class FakeService:
        def recover_interrupted_runs(self):
            return 0

        def execute_next_queued(self):
            return SimpleNamespace(
                id="eval-1",
                status="completed",
                suite_name="retrieval-core-v1",
            )

    monkeypatch.setattr(cli, "_persistent_eval_service", lambda: FakeService())

    exit_code = cli.main(["worker", "eval-once", "--json"])

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body == {
        "executed": 1,
        "eval_runs": [
            {
                "eval_run_id": "eval-1",
                "status": "completed",
                "suite": "retrieval-core-v1",
            }
        ],
    }


def test_cli_eval_worker_run_loop_respects_max_runs(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    calls = {"count": 0}

    class FakeService:
        def recover_interrupted_runs(self):
            return 0

        def execute_next_queued(self):
            calls["count"] += 1
            return SimpleNamespace(
                id=f"eval-{calls['count']}",
                status="completed",
                suite_name="retrieval-core-v1",
            )

    monkeypatch.setattr(cli, "_persistent_eval_service", lambda: FakeService())

    exit_code = cli.main(["worker", "eval-run", "--max-runs", "2"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert calls["count"] == 2
    assert "Executed evaluation run eval-1: completed" in output
    assert "Executed evaluation run eval-2: completed" in output


def test_persistent_run_worker_wires_usage_recorder(monkeypatch) -> None:
    cli = importlib.import_module("app.cli")
    captured = {}
    settings = SimpleNamespace(database_url="postgresql+psycopg://example")

    class FakeGitHubApp:
        def __init__(self, settings):
            captured["github_settings"] = settings

    class FakeUsageRecorder:
        def __init__(self, database_url):
            captured["usage_database_url"] = database_url

    class FakeRunStore:
        def __init__(self, database_url):
            captured["run_store_database_url"] = database_url

    class FakeAuditLogger:
        def __init__(self, database_url):
            captured["audit_database_url"] = database_url

    class FakeRunService:
        def __init__(self, **kwargs):
            captured["run_service_kwargs"] = kwargs

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "GitHubAppService", FakeGitHubApp)
    monkeypatch.setattr(cli, "LLMUsageRecorder", FakeUsageRecorder)
    monkeypatch.setattr(cli, "RunStore", FakeRunStore)
    monkeypatch.setattr(cli, "AuditLogger", FakeAuditLogger)
    monkeypatch.setattr(cli, "RepoPilotRunService", FakeRunService)

    cli._persistent_run_service()

    assert captured["usage_database_url"] == settings.database_url
    assert isinstance(captured["run_service_kwargs"]["llm_usage_recorder"], FakeUsageRecorder)


def test_persistent_eval_worker_wires_usage_recorder(monkeypatch) -> None:
    cli = importlib.import_module("app.cli")
    captured = {}
    settings = SimpleNamespace(database_url="postgresql+psycopg://example")

    class FakeUsageRecorder:
        def __init__(self, database_url):
            captured["usage_database_url"] = database_url

    class FakeEvaluationStore:
        def __init__(self, database_url):
            captured["eval_store_database_url"] = database_url

    class FakeEvaluationService:
        def __init__(self, **kwargs):
            captured["eval_service_kwargs"] = kwargs

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "LLMUsageRecorder", FakeUsageRecorder)
    monkeypatch.setattr(cli, "EvaluationStore", FakeEvaluationStore)
    monkeypatch.setattr(cli, "EvaluationService", FakeEvaluationService)

    cli._persistent_eval_service()

    assert captured["usage_database_url"] == settings.database_url
    assert isinstance(captured["eval_service_kwargs"]["llm_usage_recorder"], FakeUsageRecorder)


def test_cli_eval_workflow_prints_report(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    eval_runner = importlib.import_module("app.evals.runner")
    eval_models = importlib.import_module("app.evals.models")

    result = eval_models.EvalSuiteResult(
        total=1,
        passed=1,
        failed=0,
        points_earned=1,
        points_possible=1,
        score=1.0,
        category_scores={"outcome": 1.0},
        cases=[
            eval_models.EvalCaseResult(
                id="sample",
                status="passed",
                points_earned=1,
                points_possible=1,
                score=1.0,
                checks=[
                    eval_models.EvalCheck(
                        name="final_status",
                        category="outcome",
                        passed=True,
                        message="Expected final status matched.",
                    )
                ],
            )
        ],
    )

    monkeypatch.setattr(eval_runner, "discover_eval_cases", lambda paths: [Path("case.case.json")])
    monkeypatch.setattr(eval_runner, "run_eval_suite", lambda paths: result)

    exit_code = cli.main(["eval"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Eval cases: 1/1 passed" in output
    assert "- sample: passed" in output


def test_cli_eval_workflow_json_prints_result(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    eval_runner = importlib.import_module("app.evals.runner")
    eval_models = importlib.import_module("app.evals.models")

    result = eval_models.EvalSuiteResult(
        total=1,
        passed=1,
        failed=0,
        points_earned=0,
        points_possible=0,
        score=1.0,
        cases=[
            eval_models.EvalCaseResult(
                id="sample",
                status="passed",
                checks=[],
            )
        ],
    )

    monkeypatch.setattr(eval_runner, "discover_eval_cases", lambda paths: [Path("case.case.json")])
    monkeypatch.setattr(eval_runner, "run_eval_suite", lambda paths: result)

    exit_code = cli.main(["eval", "--json"])

    body = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert body["total"] == 1
    assert body["cases"][0]["id"] == "sample"


def test_cli_eval_workflow_returns_nonzero_when_cases_fail(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    eval_runner = importlib.import_module("app.evals.runner")
    eval_models = importlib.import_module("app.evals.models")

    result = eval_models.EvalSuiteResult(
        total=1,
        passed=0,
        failed=1,
        points_earned=0,
        points_possible=1,
        score=0.0,
        cases=[
            eval_models.EvalCaseResult(
                id="sample",
                status="failed",
                points_earned=0,
                points_possible=1,
                score=0.0,
                checks=[
                    eval_models.EvalCheck(
                        name="final_status",
                        category="outcome",
                        passed=False,
                        message="Expected final status did not match.",
                    )
                ],
            )
        ],
    )

    monkeypatch.setattr(eval_runner, "discover_eval_cases", lambda paths: [Path("case.case.json")])
    monkeypatch.setattr(eval_runner, "run_eval_suite", lambda paths: result)

    exit_code = cli.main(["eval"])

    assert exit_code == 1
    assert "Eval cases: 0/1 passed" in capsys.readouterr().out


def test_cli_eval_retrieval_prints_report(monkeypatch, capsys) -> None:
    cli = importlib.import_module("app.cli")
    retrieval_eval = importlib.import_module("app.evals.retrieval")

    result = retrieval_eval.RetrievalBenchmarkResult(
        total_cases=1,
        summaries=[
            retrieval_eval.RetrieverSummary(
                retriever="hybrid",
                cases=1,
                avg_recall_at_k={1: 1.0},
                avg_precision_at_k={1: 1.0},
                hit_rate_at_k={1: 1.0},
                avg_mrr=1.0,
                avg_duration_ms=0.1,
            )
        ],
        cases=[],
    )

    monkeypatch.setattr(retrieval_eval, "load_retrieval_benchmark", lambda path: object())
    monkeypatch.setattr(
        retrieval_eval,
        "run_retrieval_benchmark",
        lambda benchmark, limit: result,
    )

    exit_code = cli.main(["eval", "retrieval", "--limit", "3"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Retrieval benchmark cases: 1" in output
    assert "- hybrid:" in output
