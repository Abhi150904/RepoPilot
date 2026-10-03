from __future__ import annotations

import httpx

from app.tools.github import GitHubClient


def test_github_client_creates_pull_request(monkeypatch) -> None:
    captured = {}

    def fake_request(method, url, headers, params, json, timeout):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(
            status_code=201,
            json={
                "number": 17,
                "html_url": "https://github.com/example/demo/pull/17",
                "title": "Fix login validation",
                "head": {"ref": "fix-login-validation"},
                "base": {"ref": "main"},
            },
        )

    monkeypatch.setattr(httpx, "request", fake_request)

    result = GitHubClient().create_pull_request(
        repo="example/demo",
        title="Fix login validation",
        body="## Summary\n- Fix login validation",
        head="fix-login-validation",
        base="main",
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.github.com/repos/example/demo/pulls"
    assert captured["json"] == {
        "title": "Fix login validation",
        "body": "## Summary\n- Fix login validation",
        "head": "fix-login-validation",
        "base": "main",
    }
    assert result.number == 17
    assert result.url == "https://github.com/example/demo/pull/17"
