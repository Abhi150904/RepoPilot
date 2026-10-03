from __future__ import annotations

import base64
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.schemas.execution import PullRequestResult
from app.schemas.issue import GitHubIssue
from app.schemas.repository import RepositoryFile


class GitHubError(RuntimeError):
    """Raised when a GitHub API request fails."""


class GitHubClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._base_url = "https://api.github.com"

    def get_issue(self, repo: str, issue_number: int) -> GitHubIssue:
        data = self._request("GET", f"/repos/{repo}/issues/{issue_number}")
        if "pull_request" in data:
            raise GitHubError(
                f"#{issue_number} in {repo} is a pull request, not an issue. "
                "Create or choose a GitHub issue for RepoPilot's issue-to-plan flow."
            )
        return GitHubIssue(
            number=data["number"],
            title=data["title"],
            body=data.get("body") or "",
            url=data["html_url"],
            is_pull_request=False,
        )

    def list_repository_files(self, repo: str) -> list[RepositoryFile]:
        data = self._request("GET", f"/repos/{repo}/git/trees/HEAD", recursive="1")
        tree = data.get("tree", [])
        return [
            RepositoryFile(path=item["path"], size=item.get("size"))
            for item in tree
            if item.get("type") == "blob"
        ]

    def read_file(self, repo: str, path: str) -> str:
        data = self._request("GET", f"/repos/{repo}/contents/{path}")
        if data.get("encoding") != "base64" or "content" not in data:
            raise GitHubError(f"GitHub did not return base64 file content for {path}.")
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    def search_code(self, repo: str, query: str) -> list[str]:
        data = self._request("GET", "/search/code", q=f"{query} repo:{repo}")
        return [item["path"] for item in data.get("items", []) if "path" in item]

    def create_pull_request(
        self,
        *,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> PullRequestResult:
        data = self._request(
            "POST",
            f"/repos/{repo}/pulls",
            json={
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            },
        )
        return PullRequestResult(
            number=data["number"],
            url=data["html_url"],
            title=data["title"],
            head=data["head"]["ref"],
            base=data["base"]["ref"],
        )

    def _request(self, method: str, path: str, **params: str) -> dict[str, Any]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._settings.github_token:
            headers["Authorization"] = f"Bearer {self._settings.github_token}"

        url = f"{self._base_url}{path}"
        json_body = params.pop("json", None)
        try:
            response = httpx.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=20.0,
            )
        except httpx.HTTPError as exc:
            raise GitHubError(f"GitHub request failed for {path}: {exc}") from exc

        if response.status_code >= 400:
            message = _extract_error_message(response)
            raise GitHubError(
                f"GitHub request failed for {path}: "
                f"{response.status_code} {message}"
            )

        return response.json()


def _extract_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text
    return str(data.get("message", response.text))
