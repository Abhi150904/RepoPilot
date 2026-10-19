from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from typing import Any

from sqlalchemy import DateTime, Integer, String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker
from sqlalchemy.types import JSON

from app.api.runs import Base


SENSITIVE_KEY_PARTS = ("token", "secret", "password", "authorization", "api_key", "apikey", "key")
MAX_STRING_LENGTH = 500
MAX_LIST_ITEMS = 20
MAX_DICT_ITEMS = 40

RUN_CREATED = "run.created"
RUN_STARTED = "run.started"
RUN_COMPLETED = "run.completed"
RUN_FAILED = "run.failed"
RUN_APPROVED = "run.approved"
RUN_REJECTED = "run.rejected"
RUN_PUBLISHED = "run.published"


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class AuditEvent:
    event_type: str
    actor: str = "system"
    actor_context: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def safe_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event_type": self.event_type,
            "actor": self.actor,
            "created_at": self.created_at,
            "metadata": _sanitize(self.metadata),
        }
        if self.actor_context:
            payload["actor_context"] = _sanitize(self.actor_context)
        if self.run_id:
            payload["run_id"] = self.run_id
        return payload


class AuditLogger:
    def __init__(
        self,
        logger: logging.Logger | None = None,
        *,
        database_url: str | None = None,
        engine: Engine | None = None,
    ) -> None:
        self._logger = logger or logging.getLogger("repopilot.audit")
        self._engine = engine or (create_engine(database_url, future=True, pool_pre_ping=True, pool_recycle=300) if database_url else None)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False) if self._engine else None
        if self._engine and (engine is not None or (database_url and database_url.startswith("sqlite"))):
            Base.metadata.create_all(self._engine)

    def record(
        self,
        event_type: str,
        *,
        run_id: str | None = None,
        actor: str = "system",
        actor_context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            actor=actor,
            actor_context=actor_context or {},
            run_id=run_id,
            metadata=metadata or {},
        )
        payload = event.safe_payload()
        self._logger.info(json.dumps(payload, sort_keys=True))
        self._persist(payload)
        return event

    def _persist(self, payload: dict[str, Any]) -> None:
        if self._session_factory is None:
            return
        with self._session_factory() as session:
            session.add(
                AuditEventRow(
                    event_type=str(payload["event_type"]),
                    actor=str(payload["actor"]),
                    actor_context=_dict_or_empty(payload.get("actor_context")),
                    run_id=payload.get("run_id") if isinstance(payload.get("run_id"), str) else None,
                    metadata_json=_dict_or_empty(payload.get("metadata")),
                    created_at=_parse_created_at(str(payload["created_at"])),
                )
            )
            session.commit()


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_DICT_ITEMS:
                redacted["_truncated"] = True
                break
            if _is_sensitive_key(str(key)):
                redacted[str(key)] = "[redacted]"
            else:
                redacted[str(key)] = _sanitize(item)
        return redacted
    if isinstance(value, list):
        items = [_sanitize(item) for item in value[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            items.append({"_truncated": True, "remaining": len(value) - MAX_LIST_ITEMS})
        return items
    if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
        return f"{value[:MAX_STRING_LENGTH]}...[truncated {len(value) - MAX_STRING_LENGTH} chars]"
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _dict_or_empty(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _parse_created_at(value: str) -> datetime:
    return datetime.fromisoformat(value)
