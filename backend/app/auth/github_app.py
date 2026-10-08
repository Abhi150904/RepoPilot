from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from typing import Any

import httpx
import jwt

from app.auth.models import AuthorizedRepository
from app.core.config import Settings


class GitHubAppError(RuntimeError):
    """Raised when GitHub App repository authorization fails."""


class GitHubAppService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = "https://api.github.com"
        self._token_cache: dict[int, tuple[str, datetime]] = {}

    def app_configured(self) -> bool:
        return bool(self._settings.github_app_id and self._settings.github_app_private_key)

    def installation_url(self) -> str | None:
        if not self._settings.github_app_name:
            return None
        return f"https://github.com/apps/{self._settings.github_app_name}/installations/new"

    def list_user_installations(self, *, oauth_access_token: str) -> list[dict[str, Any]]:
        data = self._user_request("GET", "/user/installations", oauth_access_token=oauth_access_token)
        installations = data.get("installations", [])
        return [item for item in installations if isinstance(item, dict)]

    def list_installation_repositories(
        self,
        *,
        oauth_access_token: str,
        installation_id: int,
    ) -> list[AuthorizedRepository]:
        data = self._user_request(
            "GET",
            f"/user/installations/{installation_id}/repositories",
            oauth_access_token=oauth_access_token,
        )
        repositories = []
        for item in data.get("repositories", []):
            if not isinstance(item, dict) or not isinstance(item.get("full_name"), str):
                continue
            repositories.append(
                AuthorizedRepository(
                    full_name=item["full_name"],
                    installation_id=installation_id,
                    default_branch=item.get("default_branch") if isinstance(item.get("default_branch"), str) else None,
                    private=item.get("private") if isinstance(item.get("private"), bool) else None,
                )
            )
        return repositories

    def list_authorized_repositories(self, *, oauth_access_token: str) -> list[AuthorizedRepository]:
        repositories: list[AuthorizedRepository] = []
        for installation in self.list_user_installations(oauth_access_token=oauth_access_token):
            installation_id = installation.get("id")
            if isinstance(installation_id, int):
                repositories.extend(
                    self.list_installation_repositories(
                        oauth_access_token=oauth_access_token,
                        installation_id=installation_id,
                    )
                )
        return repositories

    def authorize_repository(
        self,
        *,
        oauth_access_token: str,
        repository: str,
    ) -> AuthorizedRepository | None:
        normalized = repository.lower()
        for candidate in self.list_authorized_repositories(oauth_access_token=oauth_access_token):
            if candidate.full_name.lower() == normalized:
                return candidate
        return None

    def installation_access_token(self, *, installation_id: int) -> str:
        cached = self._token_cache.get(installation_id)
        if cached and cached[1] > datetime.now(timezone.utc) + timedelta(seconds=30):
            return cached[0]

        jwt_token = self._app_jwt()
        response = httpx.post(
            f"{self._base_url}/app/installations/{installation_id}/access_tokens",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {jwt_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=20.0,
        )
        if response.status_code >= 400:
            raise GitHubAppError("GitHub App installation token request failed.")
        data = response.json()
        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise GitHubAppError("GitHub App installation token response was invalid.")
        expires_at = _parse_github_datetime(data.get("expires_at"))
        self._token_cache[installation_id] = (token, expires_at)
        return token

    def _app_jwt(self) -> str:
        if not self._settings.github_app_id or not self._settings.github_app_private_key:
            raise GitHubAppError("GitHub App credentials are not configured.")
        now = int(time.time())
        return jwt.encode(
            {
                "iat": now - 60,
                "exp": now + 540,
                "iss": self._settings.github_app_id,
            },
            self._settings.github_app_private_key,
            algorithm="RS256",
        )

    def _user_request(self, method: str, path: str, *, oauth_access_token: str) -> dict[str, Any]:
        response = httpx.request(
            method,
            f"{self._base_url}{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {oauth_access_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=20.0,
        )
        if response.status_code >= 400:
            raise GitHubAppError("GitHub App authorization request failed.")
        return response.json()


def _parse_github_datetime(value: object) -> datetime:
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc) + timedelta(minutes=50)
