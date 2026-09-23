from __future__ import annotations

from app.graph.workflow import build_workflow
from app.schemas.issue import GitHubIssue
from app.schemas.repository import RepositoryFile
from app.tools.github import GitHubError


def test_version_zero_workflow_produces_analysis_and_plan() -> None:
    workflow = build_workflow()

    result = workflow.invoke(
        {"issue": "Login endpoint returns 500 when email is missing."}
    )

    assert result["analysis"]["risk_level"] == "medium"
    assert "email" in result["analysis"]["summary"]
    assert result["plan"]["steps"]
    assert result["plan"]["tests_required"]


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
