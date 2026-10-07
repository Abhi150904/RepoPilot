from __future__ import annotations

import subprocess

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.core.config import Settings
from app.schemas.execution import GitSafetyReport
import app.services.run_service as service_module
from app.tools.github import GitHubError
from app.tools.workspace import WorkspaceError


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "repopilot"}


def test_api_returns_request_id_header() -> None:
    client = TestClient(create_app())

    response = client.get("/health", headers={"x-request-id": "trace-123"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "trace-123"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"


def test_ready_endpoint_reports_local_readiness() -> None:
    client = TestClient(create_app(settings=Settings(_env_file=None)))

    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["service"] == "repopilot"
    assert body["hosted_mode"] is False
    assert body["checks"]["cors_configured"] is True


def test_ready_endpoint_warns_about_unsafe_hosted_token() -> None:
    client = TestClient(
        create_app(
            settings=Settings(
                hosted_mode=True,
                github_token="github-secret",
                cors_origins="*",
                _env_file=None,
            )
        )
    )

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["status"] == "degraded"
    assert "github-secret" not in response.text
    assert any("GitHub App/OAuth" in warning for warning in body["warnings"])
    assert any("Wildcard CORS" in warning for warning in body["warnings"])


def test_api_allows_configured_cors_origin() -> None:
    client = TestClient(
        create_app(
            settings=Settings(
                cors_origins="http://frontend.test",
                _env_file=None,
            )
        )
    )

    response = client.options(
        "/runs",
        headers={
            "Origin": "http://frontend.test",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://frontend.test"


def test_api_allows_next_fallback_dev_port_by_default() -> None:
    client = TestClient(create_app(settings=Settings(_env_file=None)))

    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3001",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3001"


def test_openapi_includes_run_request_examples() -> None:
    client = TestClient(create_app(settings=Settings(_env_file=None)))

    schema = client.get("/openapi.json").json()

    examples = schema["components"]["schemas"]["RunRequest"]["examples"]
    summaries = {example["summary"] for example in examples}
    assert "Plan from issue text" in summaries
    assert "Analyze a GitHub issue" in summaries
    assert "Apply changes and run tests for a GitHub issue" in summaries
    assert "Approved PR publication flow" in summaries


def test_openapi_includes_error_response_schema() -> None:
    client = TestClient(create_app(settings=Settings(_env_file=None)))

    schema = client.get("/openapi.json").json()

    assert "ErrorResponse" in schema["components"]["schemas"]
    assert "RunError" in schema["components"]["schemas"]


def test_create_run_invokes_workflow(monkeypatch) -> None:
    import app.api.app as api_module

    captured = {}

    class FakeWorkflow:
        def invoke(self, workflow_input):
            captured["workflow_input"] = workflow_input
            return {
                "issue": "Login endpoint returns 500 when email is missing.",
                "repository": "example/demo",
                "issue_number": 16,
                "issue_url": "https://github.com/example/demo/issues/16",
                "workspace_path": ".repopilot/workspaces/example__demo/runs/repopilot/issue-16",
                "run_workspace": {
                    "repo": "example/demo",
                    "source_path": ".repopilot/workspaces/example__demo",
                    "path": ".repopilot/workspaces/example__demo/runs/repopilot/issue-16",
                    "branch_name": "repopilot/issue-16-login",
                    "base_ref": "HEAD",
                },
                "modified_files": ["app.py"],
                "diff": "--- app.py\n+++ app.py\n",
                "test_result": {
                    "passed": 1,
                    "failed": 0,
                    "exit_code": 0,
                    "stdout": "1 passed",
                    "stderr": "",
                    "timed_out": False,
                    "command": ["python", "-m", "pytest"],
                },
                "test_analysis": {
                    "status": "passed",
                    "summary": "Tests passed.",
                    "failure_reason": None,
                    "next_action": "ready_for_review",
                },
                "review_result": {
                    "approved": True,
                    "summary": "Patch looks good.",
                    "findings": [],
                    "next_action": "await_human_approval",
                },
                "publish_result": {
                    "mode": "pr",
                    "status": "published",
                    "summary": "Pull request was opened successfully.",
                    "commands": [],
                    "executed_commands": [],
                    "pr_title": "Fix #16: Login endpoint returns 500 when email is missing",
                    "pr_body": "## Summary",
                    "pr_url": "https://github.com/example/demo/pull/17",
                    "commit_sha": "abc123",
                    "branch_name": "repopilot/issue-16-login",
                    "remote_name": "origin",
                    "pull_request": {
                        "number": 17,
                        "url": "https://github.com/example/demo/pull/17",
                        "title": "Fix #16: Login endpoint returns 500 when email is missing",
                        "head": "repopilot/issue-16-login",
                        "base": "main",
                    },
                    "blockers": [],
                    "next_action": "review_pull_request",
                },
                "run_summary": {
                    "status": "awaiting_approval",
                    "summary": "Tests passed and automated review approved the patch.",
                    "tests_passed": True,
                    "repair_attempts": 0,
                    "metrics": {
                        "llm_call_count": 3,
                        "total_tokens": 42,
                    },
                    "next_action": "human_review",
                },
                "run_metrics": {
                    "llm_call_count": 3,
                    "total_tokens": 42,
                },
            }

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    client = TestClient(api_module.create_app())

    response = client.post(
        "/runs",
        json={
            "repository": "example/demo",
            "issue_number": 16,
            "apply_changes": True,
            "run_tests": True,
            "test_runner": "local",
            "test_command": ["python", "-m", "pytest"],
            "max_repair_attempts": 2,
        },
    )

    assert response.status_code == 202
    assert captured["workflow_input"] == {
        "repository": "example/demo",
        "issue_number": 16,
        "apply_changes": True,
        "run_tests": True,
        "test_runner": "local",
        "test_command": ["python", "-m", "pytest"],
        "max_repair_attempts": 2,
    }
    start_body = response.json()
    assert start_body["run_id"]
    assert start_body["lifecycle_status"] == "queued"
    assert start_body["request"] == captured["workflow_input"]
    assert start_body["response"] is None
    assert start_body["error"] is None

    get_response = client.get(f"/runs/{start_body['run_id']}")

    assert get_response.status_code == 200
    body = get_response.json()["response"]
    assert get_response.json()["lifecycle_status"] == "completed"
    assert body["status"] == "awaiting_approval"
    assert body["next_action"] == "human_review"
    assert body["summary"] == "Tests passed and automated review approved the patch."
    assert body["artifacts"] == {
        "issue_url": "https://github.com/example/demo/issues/16",
        "workspace_path": ".repopilot/workspaces/example__demo/runs/repopilot/issue-16",
        "branch_name": "repopilot/issue-16-login",
        "changed_files": ["app.py"],
        "diff": "--- app.py\n+++ app.py\n",
        "tests_passed": True,
        "test_result": {
            "passed": 1,
            "failed": 0,
            "exit_code": 0,
            "stdout": "1 passed",
            "stderr": "",
            "timed_out": False,
            "command": ["python", "-m", "pytest"],
        },
        "test_analysis": {
            "status": "passed",
            "summary": "Tests passed.",
            "failure_reason": None,
            "next_action": "ready_for_review",
        },
        "review_result": {
            "approved": True,
            "summary": "Patch looks good.",
            "findings": [],
            "next_action": "await_human_approval",
        },
        "publication_package": None,
        "publish_result": {
            "mode": "pr",
            "status": "published",
            "summary": "Pull request was opened successfully.",
            "commands": [],
            "executed_commands": [],
            "pr_title": "Fix #16: Login endpoint returns 500 when email is missing",
            "pr_body": "## Summary",
            "pr_url": "https://github.com/example/demo/pull/17",
            "commit_sha": "abc123",
            "branch_name": "repopilot/issue-16-login",
            "remote_name": "origin",
            "pull_request": {
                "number": 17,
                "url": "https://github.com/example/demo/pull/17",
                "title": "Fix #16: Login endpoint returns 500 when email is missing",
                "head": "repopilot/issue-16-login",
                "base": "main",
            },
            "blockers": [],
            "next_action": "review_pull_request",
        },
        "pr_url": "https://github.com/example/demo/pull/17",
    }
    assert body["result"]["modified_files"] == ["app.py"]

    result_response = client.get(f"/runs/{start_body['run_id']}/result")
    assert result_response.status_code == 200
    assert result_response.json()["status"] == "awaiting_approval"

    metrics_response = client.get(f"/runs/{start_body['run_id']}/metrics")
    assert metrics_response.status_code == 200
    assert metrics_response.json()["metrics"] == {
        "llm_call_count": 3,
        "total_tokens": 42,
    }


def test_get_run_returns_404_for_unknown_run() -> None:
    client = TestClient(create_app())

    response = client.get("/runs/missing", headers={"x-request-id": "trace-404"})

    assert response.status_code == 404
    assert response.headers["x-request-id"] == "trace-404"
    assert response.json() == {
        "error": {
            "code": "run_not_found",
            "message": "Run not found.",
            "type": "run_not_found",
            "details": {"request_id": "trace-404"},
        }
    }


def test_approve_run_updates_completed_run(monkeypatch) -> None:
    import app.api.app as api_module

    class FakeWorkflow:
        def invoke(self, workflow_input):
            return _reviewed_run_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    client = TestClient(api_module.create_app())
    started = client.post("/runs", json={"issue": "Login endpoint fails"})

    response = client.post(f"/runs/{started.json()['run_id']}/approve", json={"note": "ship it"})

    assert response.status_code == 200
    run = response.json()
    assert run["lifecycle_status"] == "completed"
    assert run["response"]["status"] == "approved"
    assert run["response"]["next_action"] == "commit_changes"
    assert run["response"]["result"]["approval_decision"]["approved"] is True
    assert run["response"]["result"]["approval_note"] == "ship it"


def test_reject_run_updates_completed_run(monkeypatch) -> None:
    import app.api.app as api_module

    class FakeWorkflow:
        def invoke(self, workflow_input):
            return _reviewed_run_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    client = TestClient(api_module.create_app())
    started = client.post("/runs", json={"issue": "Login endpoint fails"})

    response = client.post(
        f"/runs/{started.json()['run_id']}/reject",
        json={"reason": "Need a safer test plan."},
    )

    assert response.status_code == 200
    run = response.json()
    assert run["response"]["status"] == "needs_human"
    assert run["response"]["next_action"] == "inspect_failure"
    assert run["response"]["result"]["approval_decision"]["approved"] is False
    assert run["response"]["result"]["rejection_reason"] == "Need a safer test plan."


def test_publish_requires_approval(monkeypatch) -> None:
    import app.api.app as api_module

    class FakeWorkflow:
        def invoke(self, workflow_input):
            return _reviewed_run_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    client = TestClient(api_module.create_app())
    started = client.post("/runs", json={"issue": "Login endpoint fails"})

    response = client.post(f"/runs/{started.json()['run_id']}/publish", json={"mode": "dry_run"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "approval_required"


def test_publish_dry_run_updates_run_after_approval(monkeypatch) -> None:
    import app.api.app as api_module

    class FakeWorkflow:
        def invoke(self, workflow_input):
            result = _reviewed_run_result()
            result["workspace_path"] = "."
            result["modified_files"] = ["app.py"]
            return result

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    monkeypatch.setattr(
        service_module,
        "inspect_git_safety",
        lambda workspace_path, expected_changed_files: GitSafetyReport(
            status="safe",
            summary="Git safety check found only RepoPilot-applied changes.",
        ),
    )
    client = TestClient(api_module.create_app())
    started = client.post("/runs", json={"issue": "Login endpoint fails"})
    client.post(f"/runs/{started.json()['run_id']}/approve", json={})

    response = client.post(f"/runs/{started.json()['run_id']}/publish", json={"mode": "dry_run"})

    assert response.status_code == 200
    publish_result = response.json()["response"]["result"]["publish_result"]
    assert publish_result["mode"] == "dry_run"
    assert publish_result["status"] == "ready"
    assert response.json()["response"]["artifacts"]["publish_result"]["mode"] == "dry_run"


def test_publish_rejects_workspace_changed_after_approval(tmp_path, monkeypatch) -> None:
    import app.api.app as api_module

    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "RepoPilot Test")
    (tmp_path / "app.py").write_text("print('before')\n", encoding="utf-8")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-m", "initial")
    (tmp_path / "app.py").write_text("print('approved')\n", encoding="utf-8")

    class FakeWorkflow:
        def invoke(self, workflow_input):
            result = _reviewed_run_result()
            result["workspace_path"] = str(tmp_path)
            result["modified_files"] = ["app.py"]
            return result

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    client = TestClient(api_module.create_app())
    started = client.post("/runs", json={"issue": "Login endpoint fails"})
    client.post(f"/runs/{started.json()['run_id']}/approve", json={})

    (tmp_path / "app.py").write_text("print('changed after approval')\n", encoding="utf-8")
    response = client.post(f"/runs/{started.json()['run_id']}/publish", json={"mode": "dry_run"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "approval_binding_stale"


def test_create_run_validates_required_issue_input() -> None:
    client = TestClient(create_app())

    response = client.post("/runs", json={}, headers={"x-request-id": "trace-validation"})

    assert response.status_code == 422
    assert response.headers["x-request-id"] == "trace-validation"
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]["request_id"] == "trace-validation"
    assert "Either issue or repository and issue_number" in response.json()["error"]["message"]


def test_create_run_rejects_local_apply_without_workspace() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/runs",
        json={"issue": "Login endpoint fails", "apply_changes": True},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert (
        "workspace_path is required for local apply_changes or run_tests"
        in response.json()["error"]["message"]
    )


def test_create_run_rejects_empty_test_command() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/runs",
        json={
            "repository": "example/demo",
            "issue_number": 16,
            "run_tests": True,
            "test_command": [],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "test_command cannot be empty" in response.json()["error"]["message"]


def test_create_run_rejects_blank_command_token() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/runs",
        json={
            "repository": "example/demo",
            "issue_number": 16,
            "run_tests": True,
            "test_command": ["python", " "],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "test_command tokens cannot be blank" in response.json()["error"]["message"]


def test_create_run_rejects_publication_without_apply_and_tests() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/runs",
        json={
            "repository": "example/demo",
            "issue_number": 16,
            "approved": True,
            "publish_dry_run": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "publication requires apply_changes=true" in response.json()["error"]["message"]


def test_create_run_rejects_publish_push_without_local_publish() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/runs",
        json={
            "repository": "example/demo",
            "issue_number": 16,
            "apply_changes": True,
            "run_tests": True,
            "approved": True,
            "publish_push": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "publish_push requires publish_local=true" in response.json()["error"]["message"]


def test_create_run_rejects_publish_pr_without_push() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/runs",
        json={
            "repository": "example/demo",
            "issue_number": 16,
            "apply_changes": True,
            "run_tests": True,
            "approved": True,
            "publish_pr": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "publish_pr requires publish_push=true" in response.json()["error"]["message"]


def test_create_run_stores_github_errors(monkeypatch) -> None:
    import app.api.app as api_module

    class FakeWorkflow:
        def invoke(self, workflow_input):
            raise GitHubError("GitHub request failed: 401 Bad credentials")

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    client = TestClient(api_module.create_app())

    response = client.post(
        "/runs",
        json={"repository": "example/demo", "issue_number": 1},
    )

    assert response.status_code == 202
    run = client.get(f"/runs/{response.json()['run_id']}").json()
    assert run["lifecycle_status"] == "failed"
    assert run["error"]["code"] == "github_error"
    assert run["error"]["type"] == "GitHubError"
    assert run["error"]["message"] == (
        "GitHub operation failed. Check repository access and token configuration."
    )
    assert "Bad credentials" not in run["error"]["message"]


def test_create_run_stores_workspace_errors(monkeypatch) -> None:
    import app.api.app as api_module

    class FakeWorkflow:
        def invoke(self, workflow_input):
            raise WorkspaceError("Run workspace already exists")

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    client = TestClient(api_module.create_app())

    response = client.post(
        "/runs",
        json={"repository": "example/demo", "issue_number": 1, "apply_changes": True},
    )

    assert response.status_code == 202
    run = client.get(f"/runs/{response.json()['run_id']}").json()
    assert run["lifecycle_status"] == "failed"
    assert run["error"]["code"] == "workspace_error"
    assert run["error"]["type"] == "WorkspaceError"
    assert run["error"]["message"] == (
        "Workspace operation failed. Check workspace state and permissions."
    )
    assert "already exists" not in run["error"]["message"]


def test_failed_run_error_keeps_request_id_and_hides_raw_exception(monkeypatch) -> None:
    import app.api.app as api_module

    class FakeWorkflow:
        def invoke(self, workflow_input):
            raise RuntimeError("secret-token leaked in exception")

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    client = TestClient(api_module.create_app())

    response = client.post(
        "/runs",
        json={"issue": "Login endpoint fails"},
        headers={"x-request-id": "trace-run-failed"},
    )

    assert response.status_code == 202
    run = client.get(f"/runs/{response.json()['run_id']}").json()
    assert run["lifecycle_status"] == "failed"
    assert run["error"]["code"] == "internal_error"
    assert run["error"]["type"] == "RuntimeError"
    assert run["error"]["details"]["request_id"] == "trace-run-failed"
    assert run["error"]["message"] == (
        "Run failed unexpectedly. Check server logs with the request or run ID."
    )
    assert "secret-token" not in str(run)


def _reviewed_run_result() -> dict[str, object]:
    return {
        "issue": "Login endpoint returns 500 when email is missing.",
        "modified_files": ["app.py"],
        "diff": "--- app.py\n+++ app.py\n",
        "test_analysis": {
            "status": "passed",
            "summary": "Tests passed.",
            "failure_reason": None,
            "next_action": "ready_for_review",
        },
        "review_result": {
            "approved": True,
            "summary": "Patch looks good.",
            "findings": [],
            "next_action": "await_human_approval",
        },
        "run_summary": {
            "status": "awaiting_approval",
            "summary": "Tests passed and automated review approved the patch.",
            "tests_passed": True,
            "repair_attempts": 0,
            "metrics": None,
            "next_action": "human_review",
        },
    }


def _git(path, *args: str) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

