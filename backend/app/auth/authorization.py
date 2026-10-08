from __future__ import annotations

from app.auth.github_app import GitHubAppService
from app.auth.models import AuthSession, RunOwner
from app.api.schemas import RunRequest


class AuthorizationError(PermissionError):
    """Raised when a hosted request is not allowed for the current session."""


class RepositoryAuthorizationService:
    def __init__(self, github_app: GitHubAppService) -> None:
        self._github_app = github_app

    def owner_for_run(self, *, session: AuthSession, request: RunRequest) -> RunOwner:
        if not request.repository:
            raise AuthorizationError("Hosted runs must target an authorized GitHub repository.")
        repository = self._github_app.authorize_repository(
            oauth_access_token=session.oauth_access_token,
            repository=request.repository,
        )
        if repository is None:
            raise AuthorizationError("Repository is not authorized for RepoPilot.")
        return RunOwner(
            github_user_id=session.user.github_user_id,
            github_login=session.user.login,
            installation_id=repository.installation_id,
            repository=repository.full_name,
        )
