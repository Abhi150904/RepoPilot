from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from app.api.schemas import RunError, RunResponse, RunStatusResponse


LifecycleStatus = Literal["queued", "running", "completed", "failed"]


@dataclass
class RunRecord:
    run_id: str
    lifecycle_status: LifecycleStatus
    created_at: datetime
    updated_at: datetime
    request: dict[str, Any]
    response: RunResponse | None = None
    error: RunError | None = None

    def to_response(self) -> RunStatusResponse:
        return RunStatusResponse(
            run_id=self.run_id,
            lifecycle_status=self.lifecycle_status,
            created_at=self.created_at,
            updated_at=self.updated_at,
            request=self.request,
            response=self.response,
            error=self.error,
        )


class RunStore:
    """Small in-memory run store for the first API-backed workflow model."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = Lock()

    def create(self, request: dict[str, Any]) -> RunStatusResponse:
        now = _now()
        run_id = uuid4().hex
        record = RunRecord(
            run_id=run_id,
            lifecycle_status="queued",
            created_at=now,
            updated_at=now,
            request=dict(request),
        )
        with self._lock:
            self._runs[run_id] = record
        return record.to_response()

    def get(self, run_id: str) -> RunStatusResponse | None:
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return None
            return record.to_response()

    def mark_running(self, run_id: str) -> None:
        self._update(run_id=run_id, lifecycle_status="running")

    def mark_completed(self, run_id: str, response: RunResponse) -> None:
        self._update(run_id=run_id, lifecycle_status="completed", response=response)

    def mark_failed(self, run_id: str, exc: Exception) -> None:
        self._update(
            run_id=run_id,
            lifecycle_status="failed",
            error=RunError(type=exc.__class__.__name__, message=str(exc)),
        )

    def _update(
        self,
        *,
        run_id: str,
        lifecycle_status: LifecycleStatus,
        response: RunResponse | None = None,
        error: RunError | None = None,
    ) -> None:
        with self._lock:
            record = self._runs[run_id]
            record.lifecycle_status = lifecycle_status
            record.updated_at = _now()
            record.response = response
            record.error = error


def _now() -> datetime:
    return datetime.now(timezone.utc)
