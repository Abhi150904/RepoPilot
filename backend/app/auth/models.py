from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class GitHubUser:
    github_user_id: int
    login: str
    avatar_url: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class AuthSession:
    session_id: str
    user: GitHubUser
    oauth_access_token: str
    csrf_token: str
    created_at: datetime
    expires_at: datetime

    def expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at


@dataclass(frozen=True)
class AuthorizedRepository:
    full_name: str
    installation_id: int
    default_branch: str | None = None
    private: bool | None = None


@dataclass(frozen=True)
class RunOwner:
    github_user_id: int
    github_login: str
    installation_id: int | None = None
    repository: str | None = None

    def actor_context(self) -> dict[str, object]:
        context: dict[str, object] = {
            "github_user_id": self.github_user_id,
            "github_login": self.github_login,
        }
        if self.installation_id is not None:
            context["installation_id"] = self.installation_id
        if self.repository is not None:
            context["repository"] = self.repository
        return context

    def can_access(self, other: RunOwner | None) -> bool:
        return other is not None and other.github_user_id == self.github_user_id
