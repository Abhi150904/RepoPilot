from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.auth.models import AuthorizedRepository, GitHubUser
from app.auth.sessions import InMemorySessionStore
from app.core.config import Settings
import app.services.run_service as service_module


def _hosted_settings() -> Settings:
    return Settings(
        hosted_mode=True,
        inline_run_execution=True,
        github_client_id="client-id",
        github_client_secret="client-secret",
        github_app_id="123",
        github_app_name="repopilot-test",
        github_app_private_key=_TEST_PRIVATE_KEY,
        public_base_url="http://frontend.test",
        cors_origins="http://frontend.test",
        github_token=None,
        _env_file=None,
    )


def test_github_login_generates_state_and_redirect() -> None:
    sessions = InMemorySessionStore()
    client = TestClient(
        create_app(
            settings=_hosted_settings(),
            session_store=sessions,
            oauth_client=FakeOAuthClient(),
            github_app_service=FakeGitHubAppService(),
        ),
        base_url="https://api.test",
    )

    response = client.get("/auth/github/login", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://github.test/login?")
    assert "repopilot_oauth_state" in response.cookies


def test_github_callback_rejects_missing_or_invalid_state() -> None:
    client = TestClient(
        create_app(
            settings=_hosted_settings(),
            session_store=InMemorySessionStore(),
            oauth_client=FakeOAuthClient(),
            github_app_service=FakeGitHubAppService(),
        ),
        base_url="https://api.test",
    )

    missing = client.get("/auth/github/callback?code=abc", follow_redirects=False)
    invalid = client.get("/auth/github/callback?code=abc&state=bad", follow_redirects=False)

    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "invalid_oauth_state"
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_oauth_state"


def test_successful_callback_creates_safe_session_and_auth_me() -> None:
    client = TestClient(
        create_app(
            settings=_hosted_settings(),
            session_store=InMemorySessionStore(),
            oauth_client=FakeOAuthClient(access_token="oauth-secret"),
            github_app_service=FakeGitHubAppService(),
        ),
        base_url="https://api.test",
    )
    login = client.get("/auth/github/login", follow_redirects=False)
    state = login.cookies["repopilot_oauth_state"]

    callback = client.get(
        f"/auth/github/callback?code=abc&state={state}",
        follow_redirects=False,
    )
    me = client.get("/auth/me")

    assert callback.status_code == 307
    assert "repopilot_session" in callback.cookies
    assert "oauth-secret" not in callback.text
    assert me.status_code == 200
    body = me.json()
    assert body["authenticated"] is True
    assert body["user"] == {
        "github_user_id": 101,
        "login": "octo",
        "avatar_url": "https://avatar.test/octo.png",
        "name": "Octo Cat",
    }
    assert body["csrf_token"]
    assert "oauth-secret" not in me.text


def test_logout_invalidates_session() -> None:
    client = _authenticated_client()

    assert client.get("/auth/me").json()["authenticated"] is True
    response = client.post("/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "user": None, "csrf_token": None}
    assert client.get("/auth/me").json()["authenticated"] is False


def test_hosted_run_requires_authentication() -> None:
    client = TestClient(
        create_app(
            settings=_hosted_settings(),
            session_store=InMemorySessionStore(),
            oauth_client=FakeOAuthClient(),
            github_app_service=FakeGitHubAppService(),
        ),
        base_url="https://api.test",
    )

    response = client.post("/runs", json={"repository": "octo/repo", "issue_number": 1})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_hosted_run_requires_csrf() -> None:
    client = _authenticated_client()

    response = client.post("/runs", json={"repository": "octo/repo", "issue_number": 1})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


def test_hosted_run_rejects_unauthorized_repository() -> None:
    client = _authenticated_client()
    csrf = client.get("/auth/me").json()["csrf_token"]

    response = client.post(
        "/runs",
        json={"repository": "octo/private", "issue_number": 1},
        headers={"x-csrf-token": csrf},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "repository_forbidden"


def test_hosted_authorized_run_and_ownership(monkeypatch) -> None:
    captured_workflow_input = {}

    class FakeWorkflow:
        def invoke(self, workflow_input):
            captured_workflow_input.update(workflow_input)
            return _run_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    client = _authenticated_client(app_service=FakeGitHubAppService(installation_token="install-secret"))
    csrf = client.get("/auth/me").json()["csrf_token"]

    started = client.post(
        "/runs",
        json={
            "repository": "octo/repo",
            "issue_number": 1,
            "approved": True,
            "publish_pr": True,
            "publish_push": True,
            "publish_local": True,
            "apply_changes": True,
            "run_tests": True,
        },
        headers={"x-csrf-token": csrf},
    )
    run_id = started.json()["run_id"]

    assert started.status_code == 202
    assert captured_workflow_input["_github_token"] == "install-secret"
    assert captured_workflow_input["_run_id"] == run_id
    assert captured_workflow_input.get("approved") is not True
    assert captured_workflow_input.get("publish_pr") is not True
    assert "install-secret" not in started.text
    assert client.get(f"/runs/{run_id}").status_code == 200
    assert "install-secret" not in client.get(f"/runs/{run_id}").text

    other_client = _authenticated_client(user=GitHubUser(github_user_id=202, login="other"))
    assert other_client.get(f"/runs/{run_id}").status_code == 404


def test_hosted_run_actions_require_owner_and_csrf(monkeypatch) -> None:
    class FakeWorkflow:
        def invoke(self, workflow_input):
            return _run_result()

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    client = _authenticated_client()
    csrf = client.get("/auth/me").json()["csrf_token"]
    started = client.post(
        "/runs",
        json={"repository": "octo/repo", "issue_number": 1},
        headers={"x-csrf-token": csrf},
    )
    run_id = started.json()["run_id"]

    no_csrf = client.post(f"/runs/{run_id}/approve", json={})
    assert no_csrf.status_code == 403
    assert no_csrf.json()["error"]["code"] == "csrf_failed"

    other_client = _authenticated_client(user=GitHubUser(github_user_id=202, login="other"))
    other_csrf = other_client.get("/auth/me").json()["csrf_token"]
    forbidden = other_client.post(
        f"/runs/{run_id}/approve",
        json={},
        headers={"x-csrf-token": other_csrf},
    )
    assert forbidden.status_code == 404


def test_github_repository_listing_never_returns_installation_token() -> None:
    client = _authenticated_client(app_service=FakeGitHubAppService(installation_token="install-secret"))

    response = client.get("/github/repositories")

    assert response.status_code == 200
    assert response.json()["repositories"][0]["full_name"] == "octo/repo"
    assert "install-secret" not in response.text


def _authenticated_client(
    *,
    user: GitHubUser | None = None,
    app_service: FakeGitHubAppService | None = None,
) -> TestClient:
    sessions = InMemorySessionStore()
    oauth = FakeOAuthClient(user=user or GitHubUser(101, "octo", "https://avatar.test/octo.png", "Octo Cat"))
    client = TestClient(
        create_app(
            settings=_hosted_settings(),
            session_store=sessions,
            oauth_client=oauth,
            github_app_service=app_service or FakeGitHubAppService(),
        ),
        base_url="https://api.test",
    )
    login = client.get("/auth/github/login", follow_redirects=False)
    state = login.cookies["repopilot_oauth_state"]
    client.get(f"/auth/github/callback?code=abc&state={state}", follow_redirects=False)
    return client


class FakeOAuthClient:
    def __init__(self, access_token: str = "oauth-token", user: GitHubUser | None = None) -> None:
        self.access_token = access_token
        self.user = user or GitHubUser(101, "octo", "https://avatar.test/octo.png", "Octo Cat")

    def login_url(self, *, state: str) -> str:
        return f"https://github.test/login?state={state}"

    def exchange_code(self, *, code: str) -> str:
        return self.access_token

    def get_user(self, *, access_token: str) -> GitHubUser:
        return self.user


class FakeGitHubAppService:
    def __init__(self, installation_token: str = "install-token") -> None:
        self.installation_token = installation_token

    def installation_url(self) -> str:
        return "https://github.com/apps/repopilot-test/installations/new"

    def list_user_installations(self, *, oauth_access_token: str):
        return [{"id": 123, "account": {"login": "octo", "type": "User"}}]

    def list_authorized_repositories(self, *, oauth_access_token: str):
        return [
            AuthorizedRepository(
                full_name="octo/repo",
                installation_id=123,
                default_branch="main",
                private=True,
            )
        ]

    def authorize_repository(self, *, oauth_access_token: str, repository: str):
        for repo in self.list_authorized_repositories(oauth_access_token=oauth_access_token):
            if repo.full_name.lower() == repository.lower():
                return repo
        return None

    def installation_access_token(self, *, installation_id: int) -> str:
        return self.installation_token


def _run_result() -> dict[str, object]:
    return {
        "issue": "Login endpoint returns 500 when email is missing.",
        "repository": "octo/repo",
        "issue_number": 1,
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
            "summary": "Tests passed.",
            "tests_passed": True,
            "repair_attempts": 0,
            "metrics": None,
            "next_action": "human_review",
        },
    }


_TEST_PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEAuZqY0O2/RziS8N9jJ3khm5eGZxqPjZVSWk5w3Qyx0uP4
7p2h+rnStA0d0xTQ4SVQIDAQABAoIBAAKCAQEAuZqY0O2/RziS8N9jJ3kh
-----END RSA PRIVATE KEY-----"""
