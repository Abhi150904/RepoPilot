from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from uuid import uuid4

from app.auth.models import AuthSession, GitHubUser


class InMemorySessionStore:
    """Small hosted-mode session store for Phase 16.

    This is intentionally not durable. Phase 17 persistence/background work should
    replace it with database-backed sessions and audit storage.
    """

    def __init__(self, session_ttl_minutes: int = 480, oauth_state_ttl_minutes: int = 10) -> None:
        self._session_ttl = timedelta(minutes=session_ttl_minutes)
        self._state_ttl = timedelta(minutes=oauth_state_ttl_minutes)
        self._sessions: dict[str, AuthSession] = {}
        self._oauth_states: dict[str, datetime] = {}
        self._lock = Lock()

    def create_oauth_state(self) -> str:
        state = uuid4().hex
        with self._lock:
            self._oauth_states[state] = _now() + self._state_ttl
        return state

    def consume_oauth_state(self, state: str | None) -> bool:
        if not state:
            return False
        with self._lock:
            expires_at = self._oauth_states.pop(state, None)
        return expires_at is not None and _now() < expires_at

    def create_session(self, *, user: GitHubUser, oauth_access_token: str) -> AuthSession:
        session = AuthSession(
            session_id=uuid4().hex,
            user=user,
            oauth_access_token=oauth_access_token,
            csrf_token=uuid4().hex,
            created_at=_now(),
            expires_at=_now() + self._session_ttl,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str | None) -> AuthSession | None:
        if not session_id:
            return None
        with self._lock:
            session = self._sessions.get(session_id)
            if session and session.expired():
                self._sessions.pop(session_id, None)
                return None
            return session

    def delete_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        with self._lock:
            self._sessions.pop(session_id, None)


def _now() -> datetime:
    return datetime.now(timezone.utc)
