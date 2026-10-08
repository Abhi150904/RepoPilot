from __future__ import annotations

from urllib.parse import urlencode

import httpx

from app.auth.models import GitHubUser
from app.core.config import Settings


class OAuthError(RuntimeError):
    """Raised when GitHub OAuth authentication fails."""


class GitHubOAuthClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def login_url(self, *, state: str) -> str:
        if not self._settings.github_client_id:
            raise OAuthError("GitHub OAuth client ID is not configured.")
        params = {
            "client_id": self._settings.github_client_id,
            "state": state,
            "scope": "read:user",
        }
        if self._settings.github_oauth_callback_url:
            params["redirect_uri"] = self._settings.github_oauth_callback_url
        return f"https://github.com/login/oauth/authorize?{urlencode(params)}"

    def exchange_code(self, *, code: str) -> str:
        if not self._settings.github_client_id or not self._settings.github_client_secret:
            raise OAuthError("GitHub OAuth client credentials are not configured.")
        response = httpx.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": self._settings.github_client_id,
                "client_secret": self._settings.github_client_secret,
                "code": code,
            },
            timeout=20.0,
        )
        if response.status_code >= 400:
            raise OAuthError("GitHub OAuth token exchange failed.")
        data = response.json()
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise OAuthError("GitHub OAuth token exchange did not return an access token.")
        return token

    def get_user(self, *, access_token: str) -> GitHubUser:
        response = httpx.get(
            "https://api.github.com/user",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=20.0,
        )
        if response.status_code >= 400:
            raise OAuthError("GitHub user lookup failed.")
        data = response.json()
        return GitHubUser(
            github_user_id=int(data["id"]),
            login=str(data["login"]),
            avatar_url=data.get("avatar_url") if isinstance(data.get("avatar_url"), str) else None,
            name=data.get("name") if isinstance(data.get("name"), str) else None,
        )
