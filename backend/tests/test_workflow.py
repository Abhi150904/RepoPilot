from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

import pytest

from app.core.llm import MockLLMProvider
from app.graph.workflow import build_workflow
from app.schemas.code_change import CodeChangeSet, FileChange
from app.schemas.execution import GitSafetyReport, PublishResult, TestResult as ExecutionResult
from app.schemas.issue import GitHubIssue
from app.schemas.plan import ImplementationPlan
from app.schemas.repository import RepositoryFile
from app.tools.github import GitHubError


@pytest.fixture(autouse=True)
def use_mock_llm_provider(monkeypatch) -> None:
    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "get_llm", lambda role: MockLLMProvider())


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
    assert result["run_summary"]["status"] == "planned_only"
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
            if path == "src/routes/login.py":
                return (
                    "def login(payload):\n"
                    "    email = payload[\"email\"]\n"
                    "    return {\"email\": email}\n"
                )
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
        def __init__(self, llm=None):
            pass

        def propose_changes(
            self, issue, analysis=None, plan=None, target_files=None, repository_context=None, repair_context=None
        ):
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
        def __init__(self, llm=None):
            pass

        def propose_changes(
            self, issue, analysis=None, plan=None, target_files=None, repository_context=None, repair_context=None
        ):
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
    assert result["test_analysis"]["status"] == "passed"
    assert result["test_analysis"]["next_action"] == "ready_for_review"
    assert result["repair_decision"]["should_retry"] is False
    assert result["repair_decision"]["next_action"] == "ready_for_review"
    assert result["review_result"]["approved"] is False
    assert result["run_summary"]["status"] == "review_failed"
    assert result["run_summary"]["tests_passed"] is True


def test_workflow_runs_tests_after_applying_changes(monkeypatch) -> None:
    root = _make_workspace_dir()
    target_file = root / "src" / "example.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("old value\n", encoding="utf-8")
    events = []

    class FakeCodeWriter:
        def __init__(self, llm=None):
            pass

        def propose_changes(
            self, issue, analysis=None, plan=None, target_files=None, repository_context=None, repair_context=None
        ):
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
        assert result["test_analysis"]["status"] == "passed"
        assert result["repair_decision"]["next_action"] == "ready_for_review"
        assert result["review_result"]["approved"] is True
        assert result["approval_decision"]["status"] == "awaiting_approval"
        assert result["approval_decision"]["next_action"] == "human_review"
        assert result["run_summary"]["status"] == "awaiting_approval"
        assert events == [("test", "new value\n")]
    finally:
        _remove_workspace_dir(root)


def test_workflow_marks_reviewed_changes_approved_with_explicit_approval(
    monkeypatch,
) -> None:
    root = _make_workspace_dir()
    target_file = root / "src" / "example.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("old value\n", encoding="utf-8")

    class FakeCodeWriter:
        def __init__(self, llm=None):
            pass

        def propose_changes(
            self,
            issue,
            analysis=None,
            plan=None,
            target_files=None,
            repository_context=None,
            repair_context=None,
        ):
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
    monkeypatch.setattr(
        workflow_module,
        "inspect_git_safety",
        lambda workspace_path, expected_changed_files: GitSafetyReport(
            status="safe",
            summary="Git safety check found only RepoPilot-applied changes.",
            current_branch="07-human-approval-pr",
            warnings=[],
        ),
    )

    class FakePublishExecutor:
        def __init__(self, workspace_path=None):
            self.workspace_path = workspace_path

        def publish_local(self, package):
            assert self.workspace_path == str(root)
            return PublishResult(
                mode="local",
                status="published",
                summary="Local publication completed.",
                commands=package.commands,
                executed_commands=package.commands[:3],
                pr_title=package.pr_title,
                pr_body=package.pr_body,
                branch_name=package.branch_name,
                commit_sha="abc123",
                next_action="push_branch",
            )

        def push_branch(self, package, local_result):
            assert local_result.mode == "local"
            return PublishResult(
                mode="push",
                status="published",
                summary="Publication branch was pushed.",
                commands=package.commands,
                executed_commands=[*local_result.executed_commands, "git push -u origin cli-writes-old-value"],
                pr_title=package.pr_title,
                pr_body=package.pr_body,
                branch_name=package.branch_name,
                commit_sha=local_result.commit_sha,
                remote_name="origin",
                next_action="open_pull_request",
            )

    monkeypatch.setattr(workflow_module, "PublishExecutor", FakePublishExecutor)
    workflow = build_workflow()

    try:
        result = workflow.invoke(
            {
                "issue": "CLI writes old value",
                "apply_changes": True,
                "run_tests": True,
                "approved": True,
                "publish_push": True,
                "workspace_path": str(root),
            }
        )

        assert result["review_result"]["approved"] is True
        assert result["approval_decision"]["approved"] is True
        assert result["approval_decision"]["status"] == "approved"
        assert result["publication_package"]["status"] == "ready_to_publish"
        assert result["publication_package"]["branch_name"] == "cli-writes-old-value"
        assert result["publication_package"]["commit_message"] == "cli writes old value"
        assert result["publication_package"]["pr_title"] == "CLI writes old value"
        assert result["publication_package"]["changed_files"] == ["src/example.py"]
        assert result["publication_package"]["commands"] == [
            'git checkout -b "cli-writes-old-value"',
            'git add "src/example.py"',
            'git commit -m "cli writes old value"',
            'git push -u origin "cli-writes-old-value"',
        ]
        assert result["publication_package"]["pr_url"] is None
        assert result["publication_package"]["pr_command"].startswith("gh pr create")
        assert "GitHub repository page" in result["publication_package"]["pr_instructions"][2]
        assert result["publication_package"]["git_safety"]["status"] == "safe"
        assert result["publication_package"]["next_action"] == "create_pull_request"
        assert result["publish_result"]["mode"] == "push"
        assert result["publish_result"]["status"] == "published"
        assert result["publish_result"]["commit_sha"] == "abc123"
        assert result["publish_result"]["remote_name"] == "origin"
        assert result["publish_result"]["next_action"] == "open_pull_request"
        assert result["run_summary"]["status"] == "approved"
        assert result["run_summary"]["next_action"] == "commit_changes"
    finally:
        _remove_workspace_dir(root)


def test_workflow_can_run_publish_dry_run(monkeypatch) -> None:
    root = _make_workspace_dir()
    target_file = root / "src" / "example.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("old value\n", encoding="utf-8")

    class FakeCodeWriter:
        def __init__(self, llm=None):
            pass

        def propose_changes(
            self,
            issue,
            analysis=None,
            plan=None,
            target_files=None,
            repository_context=None,
            repair_context=None,
        ):
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
    monkeypatch.setattr(
        workflow_module,
        "inspect_git_safety",
        lambda workspace_path, expected_changed_files: GitSafetyReport(
            status="safe",
            summary="Git safety check found only RepoPilot-applied changes.",
            warnings=[],
        ),
    )
    workflow = build_workflow()

    try:
        result = workflow.invoke(
            {
                "issue": "CLI writes old value",
                "apply_changes": True,
                "run_tests": True,
                "approved": True,
                "publish_dry_run": True,
                "workspace_path": str(root),
            }
        )

        assert result["publish_result"]["mode"] == "dry_run"
        assert result["publish_result"]["status"] == "ready"
        assert result["publish_result"]["next_action"] == "run_publication_commands"
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


def test_workflow_decides_repair_for_failed_tests(monkeypatch) -> None:
    def fake_run_tests_in_docker(workspace_path, command):
        return ExecutionResult(
            exit_code=1,
            passed=1,
            failed=1,
            stdout="FAILED tests/test_login.py::test_missing_email",
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
        }
    )

    assert result["test_analysis"]["status"] == "failed"
    assert result["repair_decision"]["should_retry"] is True
    assert result["repair_decision"]["next_action"] == "repair"


def test_workflow_runs_one_bounded_repair_attempt(monkeypatch) -> None:
    root = _make_workspace_dir()
    target_file = root / "src" / "example.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("old value\n", encoding="utf-8")
    code_writer_calls = []
    test_calls = []

    class FakeCodeWriter:
        def __init__(self, llm=None):
            pass

        def propose_changes(
            self, issue, analysis=None, plan=None, target_files=None, repository_context=None, repair_context=None
        ):
            code_writer_calls.append(repair_context)
            content = f"new value {len(code_writer_calls)}\n"
            return CodeChangeSet(
                summary="Update example",
                changes=[
                    FileChange(
                        path="src/example.py",
                        action="modify",
                        explanation="Update local test file",
                        proposed_content=content,
                    )
                ],
            )

    def fake_run_tests_in_docker(workspace_path, command):
        test_calls.append(Path(workspace_path, "src", "example.py").read_text())
        if len(test_calls) == 1:
            return ExecutionResult(
                exit_code=1,
                passed=0,
                failed=1,
                stdout="FAILED tests/test_example.py::test_example",
                command=command,
            )
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
                "max_repair_attempts": 1,
            }
        )

        assert len(code_writer_calls) == 2
        assert code_writer_calls[0] is None
        assert code_writer_calls[1].attempt == 1
        assert code_writer_calls[1].test_status == "failed"
        assert code_writer_calls[1].failure_reason == "FAILED tests/test_example.py::test_example"
        assert "-old value" in code_writer_calls[1].previous_diff
        assert test_calls == ["new value 1\n", "new value 2\n"]
        assert result["repair_attempts"] == 1
        assert result["repair_context"]["attempt"] == 1
        assert result["repair_context"]["failure_reason"] == "FAILED tests/test_example.py::test_example"
        assert result["test_analysis"]["status"] == "passed"
        assert result["repair_decision"]["next_action"] == "ready_for_review"
        assert result["review_result"]["approved"] is True
        assert result["approval_decision"]["status"] == "awaiting_approval"
        assert result["run_summary"]["status"] == "awaiting_approval"
        assert result["run_summary"]["repair_attempts"] == 1
        assert target_file.read_text(encoding="utf-8") == "new value 2\n"
    finally:
        _remove_workspace_dir(root)


def test_workflow_stops_when_repair_attempts_are_exhausted(monkeypatch) -> None:
    root = _make_workspace_dir()
    target_file = root / "src" / "example.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("old value\n", encoding="utf-8")
    code_writer_calls = []

    class FakeCodeWriter:
        def __init__(self, llm=None):
            pass

        def propose_changes(
            self, issue, analysis=None, plan=None, target_files=None, repository_context=None, repair_context=None
        ):
            code_writer_calls.append(issue)
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
        return ExecutionResult(
            exit_code=1,
            passed=0,
            failed=1,
            stdout="FAILED tests/test_example.py::test_example",
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
                "max_repair_attempts": 0,
            }
        )

        assert len(code_writer_calls) == 1
        assert "repair_attempts" not in result
        assert result["test_analysis"]["status"] == "failed"
        assert result["repair_decision"]["next_action"] == "repair"
    finally:
        _remove_workspace_dir(root)


def test_workflow_summarizes_failed_repair_attempt(monkeypatch) -> None:
    root = _make_workspace_dir()
    target_file = root / "src" / "example.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("old value\n", encoding="utf-8")

    class FakeCodeWriter:
        def __init__(self, llm=None):
            pass

        def propose_changes(
            self, issue, analysis=None, plan=None, target_files=None, repository_context=None, repair_context=None
        ):
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
        return ExecutionResult(
            exit_code=1,
            passed=0,
            failed=1,
            stdout="FAILED tests/test_example.py::test_example",
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
                "max_repair_attempts": 1,
            }
        )

        assert result["repair_attempts"] == 1
        assert result["test_analysis"]["status"] == "failed"
        assert result["run_summary"]["status"] == "repair_failed"
        assert result["run_summary"]["tests_passed"] is False
    finally:
        _remove_workspace_dir(root)


def test_workflow_fixes_broken_python_fixture_end_to_end(monkeypatch) -> None:
    root = _make_workspace_dir()
    app_file = root / "app.py"
    test_file = root / "test_app.py"
    app_file.write_text(
        "def login(payload):\n"
        "    email = payload[\"email\"]\n"
        "    return {\"email\": email}\n",
        encoding="utf-8",
    )
    test_file.write_text(
        "from app import login\n\n"
        "def test_missing_email_returns_validation_error():\n"
        "    response, status = login({})\n"
        "    assert status == 400\n"
        "    assert response == {\"error\": \"email is required\"}\n",
        encoding="utf-8",
    )

    class FakePlanner:
        def __init__(self, llm=None):
            pass

        def create_plan(self, issue, analysis, repository_context=None):
            return ImplementationPlan(
                summary="Validate missing email before reading the payload.",
                steps=["Add an email validation guard."],
                files_to_inspect=["app.py"],
                tests_required=["missing email returns validation error"],
            )

    def run_local_pytest(workspace_path, command):
        completed = subprocess.run(
            ["python", "-m", "pytest", "-p", "no:cacheprovider"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            check=False,
        )
        failed = 1 if completed.returncode else 0
        passed = 1 if completed.returncode == 0 else 0
        return ExecutionResult(
            exit_code=completed.returncode,
            passed=passed,
            failed=failed,
            stdout=completed.stdout,
            stderr=completed.stderr,
            command=command,
        )

    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "Planner", FakePlanner)
    monkeypatch.setattr(workflow_module, "run_tests_in_docker", run_local_pytest)
    workflow = build_workflow()

    try:
        result = workflow.invoke(
            {
                "issue": "Login endpoint returns 500 when email is missing.",
                "apply_changes": True,
                "run_tests": True,
                "workspace_path": str(root),
            }
        )

        updated_source = app_file.read_text(encoding="utf-8")
        assert "payload.get(\"email\")" in updated_source
        assert "email is required" in updated_source
        assert result["modified_files"] == ["app.py"]
        assert result["review_result"]["approved"] is True
        assert result["approval_decision"]["status"] == "awaiting_approval"
        assert result["run_summary"]["status"] == "awaiting_approval"
        assert result["run_summary"]["tests_passed"] is True
    finally:
        _remove_workspace_dir(root)
