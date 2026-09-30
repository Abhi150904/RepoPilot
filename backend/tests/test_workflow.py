from __future__ import annotations

from pathlib import Path
import shutil
from uuid import uuid4

from app.graph.workflow import build_workflow
from app.schemas.code_change import CodeChangeSet, FileChange
from app.schemas.execution import TestResult as ExecutionResult
from app.schemas.issue import GitHubIssue
from app.schemas.repository import RepositoryFile
from app.tools.github import GitHubError


def _make_workspace_dir() -> Path:
    root = Path(".test-workspaces") / uuid4().hex
    root.mkdir(parents=True)
    return root


def _remove_workspace_dir(root: Path) -> None:
    shutil.rmtree(root, ignore_errors=True)


def test_version_zero_workflow_produces_analysis_and_plan() -> None:
    workflow = build_workflow()

    result = workflow.invoke(
        {"issue": "Login endpoint returns 500 when email is missing."}
    )

    assert result["analysis"]["risk_level"] == "medium"
    assert "email" in result["analysis"]["summary"]
    assert result["plan"]["steps"]
    assert result["plan"]["tests_required"]
    assert "modified_files" not in result


def test_github_issue_workflow_fetches_issue_and_repository_context(monkeypatch) -> None:
    class FakeGitHubClient:
        def get_issue(self, repo: str, issue_number: int) -> GitHubIssue:
            assert repo == "example/demo"
            assert issue_number == 7
            return GitHubIssue(
                number=7,
                title="Login endpoint returns 500 when email is missing",
                body="Posting no email should return a validation error.",
                url="https://github.com/example/demo/issues/7",
            )

        def list_repository_files(self, repo: str) -> list[RepositoryFile]:
            assert repo == "example/demo"
            return [
                RepositoryFile(path="src/routes/login.py", size=250),
                RepositoryFile(path="tests/test_login.py", size=500),
                RepositoryFile(path="README.md", size=1000),
            ]

        def read_file(self, repo: str, path: str) -> str:
            assert repo == "example/demo"
            return f"# contents for {path}\n"

        def search_code(self, repo: str, query: str) -> list[str]:
            assert repo == "example/demo"
            return ["src/routes/login.py"]

    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "GitHubClient", FakeGitHubClient)
    workflow = build_workflow()

    result = workflow.invoke({"repository": "example/demo", "issue_number": 7})

    assert result["issue_url"] == "https://github.com/example/demo/issues/7"
    assert result["repository_context"]["repository"] == "example/demo"
    assert result["repository_context"]["matched_files"]
    assert "src/routes/login.py" in result["plan"]["files_to_inspect"]
    assert result["code_changes"]["changes"]
    assert result["diff"]
    assert "modified_files" not in result


def test_github_issue_workflow_rejects_pull_request_numbers(monkeypatch) -> None:
    class FakeGitHubClient:
        def get_issue(self, repo: str, issue_number: int) -> GitHubIssue:
            raise GitHubError("#1 in example/demo is a pull request, not an issue.")

    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "GitHubClient", FakeGitHubClient)
    workflow = build_workflow()

    try:
        workflow.invoke({"repository": "example/demo", "issue_number": 1})
    except GitHubError as exc:
        assert "pull request" in str(exc)
    else:
        raise AssertionError("Expected pull request numbers to be rejected.")


def test_workflow_applies_code_changes_only_when_explicitly_enabled(monkeypatch) -> None:
    root = _make_workspace_dir()
    target_file = root / "src" / "example.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("old value\n", encoding="utf-8")

    class FakeCodeWriter:
        def propose_changes(self, issue, plan, repository_context=None):
            return CodeChangeSet(
                summary="Update example",
                changes=[
                    FileChange(
                        path="src/example.py",
                        action="modify",
                        explanation="Update local test file",
                        proposed_content="new value\n",
                    )
                ],
            )

    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "CodeWriter", FakeCodeWriter)
    workflow = build_workflow()

    try:
        result = workflow.invoke(
            {
                "issue": "CLI writes old value",
                "apply_changes": True,
                "workspace_path": str(root),
            }
        )

        assert result["modified_files"] == ["src/example.py"]
        assert target_file.read_text(encoding="utf-8") == "new value\n"
        assert "-old value" in result["diff"]
        assert "+new value" in result["diff"]
    finally:
        _remove_workspace_dir(root)


def test_workflow_requires_workspace_path_when_applying_changes(monkeypatch) -> None:
    class FakeCodeWriter:
        def propose_changes(self, issue, plan, repository_context=None):
            return CodeChangeSet(
                summary="Noop",
                changes=[],
            )

    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "CodeWriter", FakeCodeWriter)
    workflow = build_workflow()

    try:
        workflow.invoke({"issue": "Need edit", "apply_changes": True})
    except ValueError as exc:
        assert "workspace_path" in str(exc)
    else:
        raise AssertionError("Expected workspace_path to be required.")


def test_workflow_runs_tests_when_explicitly_enabled(monkeypatch) -> None:
    called = {}

    def fake_run_tests_in_docker(workspace_path, command):
        called["workspace_path"] = workspace_path
        called["command"] = command
        return ExecutionResult(
            exit_code=0,
            passed=3,
            failed=0,
            stdout="===== 3 passed in 0.12s =====",
            command=command,
        )

    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "run_tests_in_docker", fake_run_tests_in_docker)
    workflow = build_workflow()

    result = workflow.invoke(
        {
            "issue": "Login endpoint needs validation",
            "run_tests": True,
            "workspace_path": ".",
            "test_command": ["python", "-m", "pytest"],
        }
    )

    assert called == {
        "workspace_path": ".",
        "command": ["python", "-m", "pytest"],
    }
    assert result["test_result"]["exit_code"] == 0
    assert result["test_result"]["passed"] == 3
    assert result["test_result"]["failed"] == 0


def test_workflow_runs_tests_after_applying_changes(monkeypatch) -> None:
    root = _make_workspace_dir()
    target_file = root / "src" / "example.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("old value\n", encoding="utf-8")
    events = []

    class FakeCodeWriter:
        def propose_changes(self, issue, plan, repository_context=None):
            return CodeChangeSet(
                summary="Update example",
                changes=[
                    FileChange(
                        path="src/example.py",
                        action="modify",
                        explanation="Update local test file",
                        proposed_content="new value\n",
                    )
                ],
            )

    def fake_run_tests_in_docker(workspace_path, command):
        events.append(("test", Path(workspace_path, "src", "example.py").read_text()))
        return ExecutionResult(
            exit_code=0,
            passed=1,
            failed=0,
            stdout="===== 1 passed in 0.10s =====",
            command=command,
        )

    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "CodeWriter", FakeCodeWriter)
    monkeypatch.setattr(workflow_module, "run_tests_in_docker", fake_run_tests_in_docker)
    workflow = build_workflow()

    try:
        result = workflow.invoke(
            {
                "issue": "CLI writes old value",
                "apply_changes": True,
                "run_tests": True,
                "workspace_path": str(root),
            }
        )

        assert result["modified_files"] == ["src/example.py"]
        assert result["test_result"]["passed"] == 1
        assert events == [("test", "new value\n")]
    finally:
        _remove_workspace_dir(root)


def test_workflow_requires_workspace_path_when_running_tests() -> None:
    workflow = build_workflow()

    try:
        workflow.invoke({"issue": "Need tests", "run_tests": True})
    except ValueError as exc:
        assert "workspace_path" in str(exc)
    else:
        raise AssertionError("Expected workspace_path to be required.")
