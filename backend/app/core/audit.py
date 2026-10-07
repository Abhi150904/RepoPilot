from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from typing import Any


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
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("repopilot.audit")

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
        self._logger.info(json.dumps(event.safe_payload(), sort_keys=True))
        return event


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
