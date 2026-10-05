from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.core.config import Settings
from app.tools.github import GitHubError
from app.tools.workspace import WorkspaceError


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "repopilot"}


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
                    "status": "approved",
                    "summary": "Tests passed and pull request was opened.",
                    "tests_passed": True,
                    "repair_attempts": 0,
                    "metrics": None,
                    "next_action": "commit_changes",
                },
            }

    monkeypatch.setattr(api_module, "build_workflow", lambda: FakeWorkflow())
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
    assert body["status"] == "approved"
    assert body["next_action"] == "commit_changes"
    assert body["summary"] == "Tests passed and pull request was opened."
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


def test_get_run_returns_404_for_unknown_run() -> None:
    client = TestClient(create_app())

    response = client.get("/runs/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "type": "http_error",
            "message": "Run not found.",
        }
    }


def test_create_run_validates_required_issue_input() -> None:
    client = TestClient(create_app())

    response = client.post("/runs", json={})

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "validation_error"
    assert "Either issue or repository and issue_number" in response.json()["error"]["message"]


def test_create_run_rejects_local_apply_without_workspace() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/runs",
        json={"issue": "Login endpoint fails", "apply_changes": True},
    )

    assert response.status_code == 422
    assert response.json()["error"]["type"] == "validation_error"
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
    assert response.json()["error"]["type"] == "validation_error"
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
    assert response.json()["error"]["type"] == "validation_error"
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
    assert response.json()["error"]["type"] == "validation_error"
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
    assert response.json()["error"]["type"] == "validation_error"
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
    assert response.json()["error"]["type"] == "validation_error"
    assert "publish_pr requires publish_push=true" in response.json()["error"]["message"]


def test_create_run_stores_github_errors(monkeypatch) -> None:
    import app.api.app as api_module

    class FakeWorkflow:
        def invoke(self, workflow_input):
            raise GitHubError("GitHub request failed: 401 Bad credentials")

    monkeypatch.setattr(api_module, "build_workflow", lambda: FakeWorkflow())
    client = TestClient(api_module.create_app())

    response = client.post(
        "/runs",
        json={"repository": "example/demo", "issue_number": 1},
    )

    assert response.status_code == 202
    run = client.get(f"/runs/{response.json()['run_id']}").json()
    assert run["lifecycle_status"] == "failed"
    assert run["error"]["type"] == "GitHubError"
    assert "Bad credentials" in run["error"]["message"]


def test_create_run_stores_workspace_errors(monkeypatch) -> None:
    import app.api.app as api_module

    class FakeWorkflow:
        def invoke(self, workflow_input):
            raise WorkspaceError("Run workspace already exists")

    monkeypatch.setattr(api_module, "build_workflow", lambda: FakeWorkflow())
    client = TestClient(api_module.create_app())

    response = client.post(
        "/runs",
        json={"repository": "example/demo", "issue_number": 1, "apply_changes": True},
    )

    assert response.status_code == 202
    run = client.get(f"/runs/{response.json()['run_id']}").json()
    assert run["lifecycle_status"] == "failed"
    assert run["error"]["type"] == "WorkspaceError"
    assert "already exists" in run["error"]["message"]
