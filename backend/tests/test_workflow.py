from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

import pytest

from app.core.llm import LLMProviderError, MockLLMProvider
from app.graph.workflow import build_workflow
from app.schemas.code_change import CodeChangeSet, FileChange
from app.schemas.execution import (
    GitSafetyReport,
    LLMUsageEvent,
    PublishResult,
    TestResult as ExecutionResult,
)
from app.schemas.issue import GitHubIssue
from app.schemas.plan import ImplementationPlan
from app.schemas.repository import RepositoryFile
from app.tools.github import GitHubError
from app.tools.workspace import RunWorkspace


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


class MeteredMockLLM(MockLLMProvider):
    def __init__(self, role: str, model: str = "metered-model") -> None:
        self.role = role
        self.model = model
        self._usage_events = []

    @property
    def usage_events(self):
        return list(self._usage_events)

    def _record(self, total_tokens: int = 10, retry_count: int = 0) -> None:
        self._usage_events.append(
            LLMUsageEvent(
                role=self.role,
                provider="test",
                model=self.model,
                prompt_tokens=total_tokens - 3,
                output_tokens=3,
                total_tokens=total_tokens,
                duration_ms=1.0,
                success=True,
                retry_count=retry_count,
            )
        )

    def analyze_issue(self, issue):
        self._record(total_tokens=11)
        return super().analyze_issue(issue)

    def create_plan(self, issue, analysis, repository_context=None):
        self._record(total_tokens=13)
        return super().create_plan(issue, analysis, repository_context)

    def propose_code_changes(
        self,
        issue,
        analysis,
        plan,
        target_files,
        repair_context=None,
    ):
        self._record(total_tokens=17, retry_count=1 if repair_context else 0)
        return super().propose_code_changes(
            issue,
            analysis,
            plan,
            target_files,
            repair_context,
        )

    def review_changes(
        self,
        issue,
        plan,
        change_set,
        diff,
        test_analysis,
        repair_attempts=0,
    ):
        self._record(total_tokens=19)
        return super().review_changes(
            issue,
            plan,
            change_set,
            diff,
            test_analysis,
            repair_attempts,
        )


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


def test_workflow_collects_llm_usage_and_run_metrics(monkeypatch) -> None:
    import app.graph.workflow as workflow_module

    monkeypatch.setattr(
        workflow_module,
        "get_llm",
        lambda role: MeteredMockLLM(role=role, model=f"{role}-model"),
    )
    workflow = build_workflow()

    result = workflow.invoke(
        {"issue": "Login endpoint returns 500 when email is missing."}
    )

    assert [event["role"] for event in result["llm_usage"]] == [
        "analyzer",
        "planner",
        "coder",
    ]
    assert result["run_metrics"]["llm_call_count"] == 3
    assert result["run_metrics"]["total_tokens"] == 41
    assert result["run_metrics"]["models_by_role"] == {
        "analyzer": ["analyzer-model"],
        "planner": ["planner-model"],
        "coder": ["coder-model"],
    }
    assert result["run_summary"]["metrics"]["llm_call_count"] == 3
    assert {timing["stage"] for timing in result["stage_timings"]} == {
        "analyzer",
        "planner",
        "coder",
    }


def test_workflow_summarizes_analyzer_provider_failure(monkeypatch) -> None:
    import app.graph.workflow as workflow_module

    def failing_get_llm(role):
        raise LLMProviderError("Gemini returned malformed JSON.")

    monkeypatch.setattr(workflow_module, "get_llm", failing_get_llm)
    workflow = build_workflow()

    result = workflow.invoke(
        {"issue": "Login endpoint returns 500 when email is missing."}
    )

    assert result["llm_error"]["stage"] == "analyzer"
    assert result["llm_error"]["type"] == "LLMProviderError"
    assert "malformed JSON" in result["llm_error"]["message"]
    assert result["run_summary"]["status"] == "needs_human"
    assert result["run_summary"]["next_action"] == "inspect_failure"
    assert "analysis" not in result


def test_workflow_summarizes_coder_provider_failure(monkeypatch) -> None:
    class FailingCoderLLM(MockLLMProvider):
        def propose_code_changes(
            self,
            issue,
            analysis,
            plan,
            target_files,
            repair_context=None,
        ):
            raise LLMProviderError("Gemini returned JSON that does not match CodeChangeSet.")

    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "get_llm", lambda role: FailingCoderLLM())
    workflow = build_workflow()

    result = workflow.invoke(
        {"issue": "Login endpoint returns 500 when email is missing."}
    )

    assert result["analysis"]
    assert result["plan"]
    assert result["llm_error"]["stage"] == "coder"
    assert "CodeChangeSet" in result["llm_error"]["message"]
    assert result["run_summary"]["status"] == "needs_human"
    assert result["run_summary"]["next_action"] == "inspect_failure"
    assert "code_changes" not in result


def test_workflow_summarizes_reviewer_provider_failure(monkeypatch) -> None:
    class FailingReviewerLLM:
        @property
        def usage_events(self):
            return []

        def analyze_issue(self, issue):
            return MockLLMProvider().analyze_issue(issue)

        def create_plan(self, issue, analysis, repository_context=None):
            return MockLLMProvider().create_plan(issue, analysis, repository_context)

        def propose_code_changes(
            self,
            issue,
            analysis,
            plan,
            target_files,
            repair_context=None,
        ):
            return MockLLMProvider().propose_code_changes(
                issue,
                analysis,
                plan,
                target_files,
                repair_context,
            )

        def review_changes(
            self,
            issue,
            plan,
            change_set,
            diff,
            test_analysis,
            repair_attempts=0,
        ):
            raise LLMProviderError("Gemini returned JSON that does not match ReviewResult.")

    def fake_run_tests_in_docker(workspace_path, command):
        return ExecutionResult(
            exit_code=0,
            passed=1,
            failed=0,
            stdout="===== 1 passed in 0.10s =====",
            command=command,
        )

    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "get_llm", lambda role: FailingReviewerLLM())
    monkeypatch.setattr(workflow_module, "run_tests_in_docker", fake_run_tests_in_docker)
    workflow = build_workflow()

    result = workflow.invoke(
        {
            "issue": "Login endpoint returns 500 when email is missing.",
            "run_tests": True,
            "workspace_path": ".",
        }
    )

    assert result["test_analysis"]["status"] == "passed"
    assert result["llm_error"]["stage"] == "reviewer"
    assert "ReviewResult" in result["llm_error"]["message"]
    assert result["run_summary"]["status"] == "needs_human"
    assert "review_result" not in result


def test_workflow_uses_deterministic_reviewer_when_provider_is_mock(monkeypatch) -> None:
    class PoisonedMockReviewerLLM(MockLLMProvider):
        def review_changes(
            self,
            issue,
            plan,
            change_set,
            diff,
            test_analysis,
            repair_attempts=0,
        ):
            raise AssertionError("Mock provider reviewer should not be used by workflow.")

    def fake_run_tests_in_docker(workspace_path, command):
        return ExecutionResult(
            exit_code=0,
            passed=1,
            failed=0,
            stdout="===== 1 passed in 0.10s =====",
            command=command,
        )

    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "get_llm", lambda role: PoisonedMockReviewerLLM())
    monkeypatch.setattr(workflow_module, "run_tests_in_docker", fake_run_tests_in_docker)
    workflow = build_workflow()

    result = workflow.invoke(
        {
            "issue": "Login endpoint returns 500 when email is missing.",
            "run_tests": True,
            "workspace_path": ".",
        }
    )

    assert result["review_result"]["approved"] is False
    assert result["run_summary"]["status"] == "review_failed"


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


def test_github_issue_workflow_applies_changes_in_run_worktree(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "source"
    run_path = tmp_path / "runs" / "repopilot" / "issue-16-login"
    source_path.mkdir(parents=True)
    run_path.mkdir(parents=True)
    app_file = run_path / "app.py"
    app_file.write_text(
        "def login(payload):\n"
        "    email = payload[\"email\"]\n"
        "    return {\"email\": email}\n",
        encoding="utf-8",
    )
    created_worktrees = []

    class FakeGitHubClient:
        def get_issue(self, repo: str, issue_number: int) -> GitHubIssue:
            assert repo == "example/demo"
            assert issue_number == 16
            return GitHubIssue(
                number=16,
                title="Login endpoint returns 500 when email is missing",
                body="Posting no email should return a validation error.",
                url="https://github.com/example/demo/issues/16",
            )

        def list_repository_files(self, repo: str) -> list[RepositoryFile]:
            assert repo == "example/demo"
            return [
                RepositoryFile(path="app.py", size=120),
                RepositoryFile(path="tests/test_app.py", size=200),
            ]

        def read_file(self, repo: str, path: str) -> str:
            assert repo == "example/demo"
            if path == "app.py":
                return app_file.read_text(encoding="utf-8")
            return "# test placeholder\n"

        def search_code(self, repo: str, query: str) -> list[str]:
            assert repo == "example/demo"
            return ["app.py"]

    class FakePlanner:
        def __init__(self, llm=None):
            pass

        def create_plan(self, issue, analysis, repository_context=None):
            return ImplementationPlan(
                summary="Validate missing email before reading the payload.",
                steps=["Add a missing email guard."],
                files_to_inspect=["app.py"],
                tests_required=["missing email returns validation error"],
            )

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
            assert target_files
            assert target_files[0].path == "app.py"
            assert 'payload["email"]' in target_files[0].content
            return CodeChangeSet(
                summary="Add missing email validation.",
                changes=[
                    FileChange(
                        path="app.py",
                        action="modify",
                        explanation="Return a validation error before reading email.",
                        proposed_content=(
                            "def login(payload):\n"
                            "    email = payload.get(\"email\")\n"
                            "    if not email:\n"
                            "        return {\"error\": \"email is required\"}, 400\n"
                            "    return {\"email\": email}\n"
                        ),
                    )
                ],
            )

    def fake_create_run_worktree(repo: str, branch_name: str) -> RunWorkspace:
        created_worktrees.append({"repo": repo, "branch_name": branch_name})
        return RunWorkspace(
            repo=repo,
            source_path=source_path,
            path=run_path,
            branch_name=branch_name,
            base_ref="HEAD",
        )

    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "GitHubClient", FakeGitHubClient)
    monkeypatch.setattr(workflow_module, "Planner", FakePlanner)
    monkeypatch.setattr(workflow_module, "CodeWriter", FakeCodeWriter)
    monkeypatch.setattr(workflow_module, "create_run_worktree", fake_create_run_worktree)
    workflow = build_workflow()

    result = workflow.invoke(
        {
            "repository": "example/demo",
            "issue_number": 16,
            "apply_changes": True,
        }
    )

    updated_source = app_file.read_text(encoding="utf-8")
    assert result["workspace_path"] == str(run_path)
    assert result["run_workspace"]["path"] == str(run_path)
    assert result["run_workspace"]["source_path"] == str(source_path)
    assert result["modified_files"] == ["app.py"]
    assert "payload.get(\"email\")" in updated_source
    assert "email is required" in updated_source
    assert created_worktrees == [
        {
            "repo": "example/demo",
            "branch_name": "repopilot/issue-16-login-endpoint-returns-500-when-email-is-missing",
        }
    ]


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

        def open_pull_request(self, package, push_result, repository, github=None):
            assert push_result.mode == "push"
            assert repository is None
            return PublishResult(
                mode="pr",
                status="published",
                summary="Pull request was opened successfully.",
                commands=package.commands,
                executed_commands=push_result.executed_commands,
                pr_title=package.pr_title,
                pr_body=package.pr_body,
                pr_url="https://github.com/example/demo/pull/17",
                branch_name=package.branch_name,
                commit_sha=push_result.commit_sha,
                remote_name=push_result.remote_name,
                pull_request={
                    "number": 17,
                    "url": "https://github.com/example/demo/pull/17",
                    "title": package.pr_title,
                    "head": package.branch_name,
                    "base": "main",
                },
                next_action="review_pull_request",
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
                "publish_pr": True,
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
        assert result["publish_result"]["mode"] == "pr"
        assert result["publish_result"]["status"] == "published"
        assert result["publish_result"]["commit_sha"] == "abc123"
        assert result["publish_result"]["remote_name"] == "origin"
        assert result["publish_result"]["pull_request"]["number"] == 17
        assert result["publish_result"]["pr_url"] == "https://github.com/example/demo/pull/17"
        assert result["publish_result"]["next_action"] == "review_pull_request"
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


def test_prepare_publication_reuses_run_workspace_branch(monkeypatch) -> None:
    import app.graph.workflow as workflow_module

    monkeypatch.setattr(
        workflow_module,
        "inspect_git_safety",
        lambda workspace_path, expected_changed_files: GitSafetyReport(
            status="safe",
            summary="Git safety check found only RepoPilot-applied changes.",
        ),
    )

    result = workflow_module.prepare_publication_node(
        {
            "issue": "App crashes when destination field is empty.",
            "issue_number": 16,
            "repository": "Abhi150904/Wandr",
            "workspace_path": ".repopilot/workspaces/Abhi150904__Wandr/runs/repopilot/issue-16",
            "run_workspace": {
                "repo": "Abhi150904/Wandr",
                "source_path": ".repopilot/workspaces/Abhi150904__Wandr",
                "path": ".repopilot/workspaces/Abhi150904__Wandr/runs/repopilot/issue-16",
                "branch_name": "repopilot/issue-16-app-crashes",
                "base_ref": "HEAD",
            },
            "modified_files": ["src/search.py"],
            "approval_decision": {
                "approved": True,
                "status": "approved",
                "summary": "Human approval was provided for this reviewed patch.",
                "next_action": "commit_changes",
            },
        }
    )

    package = result["publication_package"]
    assert package["branch_name"] == "repopilot/issue-16-app-crashes"
    assert package["commands"] == [
        'git add "src/search.py"',
        'git commit -m "app crashes when destination field is empty"',
        'git push -u origin "repopilot/issue-16-app-crashes"',
    ]
    assert package["pr_url"] == (
        "https://github.com/Abhi150904/Wandr/pull/new/repopilot/issue-16-app-crashes"
    )


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


def test_workflow_records_repair_coder_usage_as_separate_call(monkeypatch) -> None:
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
    coder_calls = {"count": 0}

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

    class RepairingCoderLLM(MeteredMockLLM):
        def propose_code_changes(
            self,
            issue,
            analysis,
            plan,
            target_files,
            repair_context=None,
        ):
            coder_calls["count"] += 1
            self._record(total_tokens=20 + coder_calls["count"], retry_count=0)
            if repair_context is None:
                proposed = (
                    "def login(payload):\n"
                    "    return {\"email\": payload.get(\"email\")}\n"
                )
            else:
                proposed = (
                    "def login(payload):\n"
                    "    email = payload.get(\"email\")\n"
                    "    if not email:\n"
                    "        return {\"error\": \"email is required\"}, 400\n"
                    "    return {\"email\": email}\n"
                )
            return CodeChangeSet(
                summary="Update login validation.",
                changes=[
                    FileChange(
                        path="app.py",
                        action="modify",
                        explanation="Update login behavior.",
                        proposed_content=proposed,
                    )
                ],
            )

    def fake_get_llm(role):
        if role == "coder":
            return RepairingCoderLLM(role="coder", model="coder-model")
        return MeteredMockLLM(role=role, model=f"{role}-model")

    def run_local_pytest(workspace_path, command):
        completed = subprocess.run(
            ["python", "-m", "pytest", "-p", "no:cacheprovider"],
            cwd=workspace_path,
            capture_output=True,
            text=True,
            check=False,
        )
        return ExecutionResult(
            exit_code=completed.returncode,
            passed=1 if completed.returncode == 0 else 0,
            failed=0 if completed.returncode == 0 else 1,
            stdout=completed.stdout,
            stderr=completed.stderr,
            command=command,
        )

    import app.graph.workflow as workflow_module

    monkeypatch.setattr(workflow_module, "Planner", FakePlanner)
    monkeypatch.setattr(workflow_module, "get_llm", fake_get_llm)
    monkeypatch.setattr(workflow_module, "run_tests_in_docker", run_local_pytest)
    workflow = build_workflow()

    try:
        result = workflow.invoke(
            {
                "issue": "Login endpoint returns 500 when email is missing.",
                "apply_changes": True,
                "run_tests": True,
                "workspace_path": str(root),
                "max_repair_attempts": 1,
            }
        )

        coder_usage = [
            event for event in result["llm_usage"]
            if event["role"] == "coder"
        ]
        assert result["run_summary"]["status"] == "awaiting_approval"
        assert len(coder_usage) == 2
        assert coder_usage[0]["repair_attempt"] is None
        assert coder_usage[1]["repair_attempt"] == 1
        assert result["run_metrics"]["llm_call_count"] == len(result["llm_usage"])
        assert result["run_metrics"]["repair_attempts"] == 1
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
