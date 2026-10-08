from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import JSON

from app.api.schemas import RunError, RunResponse, RunStatusResponse
from app.auth.models import RunOwner


LifecycleStatus = Literal["queued", "running", "completed", "failed", "interrupted"]
PublicationStatus = Literal["not_started", "ready", "publishing", "published", "failed"]
logger = logging.getLogger(__name__)


class IdempotencyConflict(Exception):
    pass


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_runs_idempotency_key"),)

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False)
    publication_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_started")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_github_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_github_login: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_installation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_repository: Mapped[str | None] = mapped_column(String(512), nullable=True)


class RunEventRow(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)


@dataclass
class RunRecord:
    run_id: str
    lifecycle_status: LifecycleStatus
    created_at: datetime
    updated_at: datetime
    request: dict[str, Any]
    publication_status: PublicationStatus = "not_started"
    response: RunResponse | None = None
    error: RunError | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    request_id: str | None = None
    idempotency_key: str | None = None
    payload_hash: str | None = None
    owner: RunOwner | None = None

    def to_response(self) -> RunStatusResponse:
        return RunStatusResponse(
            run_id=self.run_id,
            lifecycle_status=self.lifecycle_status,
            publication_status=self.publication_status,
            created_at=self.created_at,
            updated_at=self.updated_at,
            request=self.request,
            events=self.events,
            response=self.response,
            error=self.error,
        )


@dataclass(frozen=True)
class CreateRunResult:
    run: RunStatusResponse
    created: bool


class RunStore:
    """Run storage with an in-memory default and optional SQL-backed durability."""

    def __init__(self, database_url: str | None = None, engine: Engine | None = None) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = Lock()
        self._engine = engine or (create_engine(database_url, future=True) if database_url else None)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False) if self._engine else None
        if self._engine:
            if engine is not None or (database_url and database_url.startswith("sqlite")):
                Base.metadata.create_all(self._engine)
            try:
                self.interrupt_running_runs()
            except SQLAlchemyError:
                logger.exception("RepoPilot run store could not complete startup recovery.")

    def create(
        self,
        request: dict[str, Any],
        *,
        request_id: str | None = None,
        owner: RunOwner | None = None,
        idempotency_key: str | None = None,
    ) -> RunStatusResponse:
        return self.create_result(
            request,
            request_id=request_id,
            owner=owner,
            idempotency_key=idempotency_key,
        ).run

    def create_result(
        self,
        request: dict[str, Any],
        *,
        request_id: str | None = None,
        owner: RunOwner | None = None,
        idempotency_key: str | None = None,
    ) -> CreateRunResult:
        now = _now()
        payload_hash = _payload_hash(request)
        if self._session_factory:
            with self._session_factory() as session:
                existing = self._existing_idempotent_run(
                    session=session,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                )
                if existing:
                    return CreateRunResult(run=existing.to_response(), created=False)
                record = RunRecord(
                    run_id=uuid4().hex,
                    lifecycle_status="queued",
                    publication_status="not_started",
                    created_at=now,
                    updated_at=now,
                    request=dict(request),
                    request_id=request_id,
                    owner=owner,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash if idempotency_key else None,
                )
                session.add(_row_from_record(record))
                _add_event(session, record.run_id, "run.created", now, {"request_id": request_id})
                _add_event(session, record.run_id, "run.queued", now, {})
                session.commit()
                return CreateRunResult(run=self.get(record.run_id) or record.to_response(), created=True)

        record = RunRecord(
            run_id=uuid4().hex,
            lifecycle_status="queued",
            publication_status="not_started",
            created_at=now,
            updated_at=now,
            request=dict(request),
            request_id=request_id,
            owner=owner,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash if idempotency_key else None,
        )
        with self._lock:
            if idempotency_key:
                for existing in self._runs.values():
                    if existing.idempotency_key == idempotency_key:
                        if existing.payload_hash != payload_hash:
                            raise IdempotencyConflict("Idempotency-Key was reused with a different payload.")
                        return CreateRunResult(run=existing.to_response(), created=False)
            record.events.append(_event(record.run_id, "run.created", now, {"request_id": request_id}))
            record.events.append(_event(record.run_id, "run.queued", now, {}))
            self._runs[record.run_id] = record
        return CreateRunResult(run=record.to_response(), created=True)

    def get(self, run_id: str) -> RunStatusResponse | None:
        if self._session_factory:
            with self._session_factory() as session:
                row = session.get(RunRow, run_id)
                if row is None:
                    return None
                return _record_from_row(row, _events_for_run(session, run_id)).to_response()
        with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return None
            return record.to_response()

    def get_request_id(self, run_id: str) -> str | None:
        record = self._record(run_id)
        return record.request_id if record else None

    def get_owner(self, run_id: str) -> RunOwner | None:
        record = self._record(run_id)
        return record.owner if record else None

    def list(self, *, owner: RunOwner | None = None, limit: int = 50) -> list[RunStatusResponse]:
        if self._session_factory:
            with self._session_factory() as session:
                statement = select(RunRow).order_by(RunRow.updated_at.desc()).limit(limit)
                if owner is not None:
                    statement = statement.where(RunRow.owner_github_user_id == owner.github_user_id)
                rows = list(session.scalars(statement))
                return [
                    _record_from_row(row, _events_for_run(session, row.run_id)).to_response()
                    for row in rows
                ]
        with self._lock:
            records = list(self._runs.values())
            if owner is not None:
                records = [
                    record
                    for record in records
                    if record.owner is not None and record.owner.github_user_id == owner.github_user_id
                ]
            return [
                record.to_response()
                for record in sorted(records, key=lambda record: record.updated_at, reverse=True)[:limit]
            ]

    def mark_running(self, run_id: str) -> None:
        self._update(run_id=run_id, lifecycle_status="running", event_type="run.started")

    def mark_completed(self, run_id: str, response: RunResponse) -> None:
        self._update(
            run_id=run_id,
            lifecycle_status="completed",
            response=response,
            publication_status=_publication_status(response),
            event_type="run.completed",
        )

    def mark_failed(self, run_id: str, exc: Exception, *, request_id: str | None = None) -> None:
        details = {"request_id": request_id} if request_id else {}
        self._update(
            run_id=run_id,
            lifecycle_status="failed",
            error=RunError(
                code=_error_code(exc),
                type=exc.__class__.__name__,
                message=_safe_error_message(exc),
                details=details,
            ),
            publication_status="not_started",
            event_type="run.failed",
            event_metadata={"error_type": exc.__class__.__name__, "error_code": _error_code(exc)},
        )

    def update_response(self, run_id: str, response: RunResponse) -> RunStatusResponse:
        self._update(
            run_id=run_id,
            lifecycle_status="completed",
            response=response,
            publication_status=_publication_status(response),
            event_type="run.updated",
        )
        updated = self.get(run_id)
        if updated is None:
            raise KeyError(run_id)
        return updated

    def mark_publication_status(
        self,
        run_id: str,
        status: PublicationStatus,
        *,
        event_type: str,
        event_metadata: dict[str, Any] | None = None,
    ) -> RunStatusResponse:
        self._update_publication(
            run_id=run_id,
            publication_status=status,
            event_type=event_type,
            event_metadata=event_metadata or {},
        )
        updated = self.get(run_id)
        if updated is None:
            raise KeyError(run_id)
        return updated

    def interrupt_running_runs(self) -> int:
        now = _now()
        if self._session_factory:
            with self._session_factory() as session:
                rows = list(session.scalars(select(RunRow).where(RunRow.lifecycle_status == "running")))
                for row in rows:
                    row.lifecycle_status = "interrupted"
                    row.updated_at = now
                    row.error = RunError(
                        code="run_interrupted",
                        type="RunInterrupted",
                        message="Run was interrupted before completion because the backend restarted.",
                    ).model_dump(mode="json")
                    _add_event(session, row.run_id, "run.interrupted", now, {"reason": "backend_restart"})
                session.commit()
                return len(rows)
        with self._lock:
            rows = [record for record in self._runs.values() if record.lifecycle_status == "running"]
            for record in rows:
                record.lifecycle_status = "interrupted"
                record.updated_at = now
                record.error = RunError(
                    code="run_interrupted",
                    type="RunInterrupted",
                    message="Run was interrupted before completion because the backend restarted.",
                )
                record.events.append(_event(record.run_id, "run.interrupted", now, {"reason": "backend_restart"}))
            return len(rows)

    def claim_next_queued(self) -> RunStatusResponse | None:
        """Atomically claim one queued run for worker execution."""
        now = _now()
        if self._session_factory:
            with self._session_factory() as session:
                statement = (
                    select(RunRow)
                    .where(RunRow.lifecycle_status == "queued")
                    .order_by(RunRow.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                row = session.scalars(statement).first()
                if row is None:
                    return None
                row.lifecycle_status = "running"
                row.updated_at = now
                _add_event(session, row.run_id, "run.claimed", now, {})
                _add_event(session, row.run_id, "run.started", now, {})
                run_id = row.run_id
                session.commit()
                return self.get(run_id)
        with self._lock:
            queued = sorted(
                (record for record in self._runs.values() if record.lifecycle_status == "queued"),
                key=lambda record: record.created_at,
            )
            if not queued:
                return None
            record = queued[0]
            record.lifecycle_status = "running"
            record.updated_at = now
            record.events.append(_event(record.run_id, "run.claimed", now, {}))
            record.events.append(_event(record.run_id, "run.started", now, {}))
            return record.to_response()

    def close(self) -> None:
        if self._engine:
            self._engine.dispose()

    def _existing_idempotent_run(
        self,
        *,
        session: Session,
        idempotency_key: str | None,
        payload_hash: str,
    ) -> RunRecord | None:
        if not idempotency_key:
            return None
        row = session.scalars(select(RunRow).where(RunRow.idempotency_key == idempotency_key)).first()
        if row is None:
            return None
        if row.payload_hash != payload_hash:
            raise IdempotencyConflict("Idempotency-Key was reused with a different payload.")
        return _record_from_row(row, _events_for_run(session, row.run_id))

    def _record(self, run_id: str) -> RunRecord | None:
        if self._session_factory:
            with self._session_factory() as session:
                row = session.get(RunRow, run_id)
                if row is None:
                    return None
                return _record_from_row(row, _events_for_run(session, run_id))
        with self._lock:
            return self._runs.get(run_id)

    def _update(
        self,
        *,
        run_id: str,
        lifecycle_status: LifecycleStatus,
        response: RunResponse | None = None,
        error: RunError | None = None,
        publication_status: PublicationStatus | None = None,
        event_type: str,
        event_metadata: dict[str, Any] | None = None,
    ) -> None:
        now = _now()
        if self._session_factory:
            with self._session_factory() as session:
                row = session.get(RunRow, run_id)
                if row is None:
                    raise KeyError(run_id)
                row.lifecycle_status = lifecycle_status
                row.publication_status = publication_status or row.publication_status
                row.updated_at = now
                row.response = response.model_dump(mode="json") if response else row.response
                row.error = error.model_dump(mode="json") if error else None
                _add_event(session, run_id, event_type, now, event_metadata or {})
                session.commit()
                return

        with self._lock:
            record = self._runs[run_id]
            record.lifecycle_status = lifecycle_status
            record.publication_status = publication_status or record.publication_status
            record.updated_at = now
            record.response = response or record.response
            record.error = error
            record.events.append(_event(run_id, event_type, now, event_metadata or {}))

    def _update_publication(
        self,
        *,
        run_id: str,
        publication_status: PublicationStatus,
        event_type: str,
        event_metadata: dict[str, Any],
    ) -> None:
        now = _now()
        if self._session_factory:
            with self._session_factory() as session:
                row = session.get(RunRow, run_id)
                if row is None:
                    raise KeyError(run_id)
                row.publication_status = publication_status
                row.updated_at = now
                _add_event(session, run_id, event_type, now, event_metadata)
                session.commit()
                return

        with self._lock:
            record = self._runs[run_id]
            record.publication_status = publication_status
            record.updated_at = now
            record.events.append(_event(run_id, event_type, now, event_metadata))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _payload_hash(request: dict[str, Any]) -> str:
    payload = json.dumps(request, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _row_from_record(record: RunRecord) -> RunRow:
    return RunRow(
        run_id=record.run_id,
        lifecycle_status=record.lifecycle_status,
        publication_status=record.publication_status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        request=dict(record.request),
        response=record.response.model_dump(mode="json") if record.response else None,
        error=record.error.model_dump(mode="json") if record.error else None,
        request_id=record.request_id,
        idempotency_key=record.idempotency_key,
        payload_hash=record.payload_hash,
        owner_github_user_id=record.owner.github_user_id if record.owner else None,
        owner_github_login=record.owner.github_login if record.owner else None,
        owner_installation_id=record.owner.installation_id if record.owner else None,
        owner_repository=record.owner.repository if record.owner else None,
    )


def _record_from_row(row: RunRow, events: list[dict[str, Any]]) -> RunRecord:
    owner = None
    if row.owner_github_user_id is not None and row.owner_github_login:
        owner = RunOwner(
            github_user_id=row.owner_github_user_id,
            github_login=row.owner_github_login,
            installation_id=row.owner_installation_id,
            repository=row.owner_repository,
        )
    return RunRecord(
        run_id=row.run_id,
        lifecycle_status=row.lifecycle_status,  # type: ignore[arg-type]
        publication_status=row.publication_status,  # type: ignore[arg-type]
        created_at=row.created_at,
        updated_at=row.updated_at,
        request=dict(row.request),
        response=RunResponse.model_validate(row.response) if row.response else None,
        error=RunError.model_validate(row.error) if row.error else None,
        events=events,
        request_id=row.request_id,
        idempotency_key=row.idempotency_key,
        payload_hash=row.payload_hash,
        owner=owner,
    )


def _add_event(
    session: Session,
    run_id: str,
    event_type: str,
    created_at: datetime,
    metadata: dict[str, Any],
) -> None:
    session.add(
        RunEventRow(
            run_id=run_id,
            event_type=event_type,
            created_at=created_at,
            metadata_json={key: value for key, value in metadata.items() if value is not None},
        )
    )


def _events_for_run(session: Session, run_id: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(RunEventRow).where(RunEventRow.run_id == run_id).order_by(RunEventRow.created_at, RunEventRow.id)
    )
    return [
        _event(row.run_id, row.event_type, row.created_at, dict(row.metadata_json or {}))
        for row in rows
    ]


def _event(run_id: str, event_type: str, created_at: datetime, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "event_type": event_type,
        "created_at": created_at.isoformat(),
        "metadata": {key: value for key, value in metadata.items() if value is not None},
    }


def _publication_status(response: RunResponse) -> PublicationStatus:
    publish_result = response.result.get("publish_result")
    if not isinstance(publish_result, dict):
        approval = response.result.get("approval_decision")
        if isinstance(approval, dict) and approval.get("approved") is True:
            return "ready"
        return "not_started"
    status = publish_result.get("status")
    if status == "published":
        return "published"
    if status == "ready":
        return "ready"
    if status == "blocked":
        return "failed"
    return "not_started"


def _error_code(exc: Exception) -> str:
    name = exc.__class__.__name__.lower()
    if "github" in name:
        return "github_error"
    if "workspace" in name:
        return "workspace_error"
    if "provider" in name or "llm" in name:
        return "provider_error"
    return "internal_error"


def _safe_error_message(exc: Exception) -> str:
    code = _error_code(exc)
    if code == "github_error":
        return "GitHub operation failed. Check repository access and token configuration."
    if code == "workspace_error":
        return "Workspace operation failed. Check workspace state and permissions."
    if code == "provider_error":
        return "Model provider operation failed. Check provider configuration."
    return "Run failed unexpectedly. Check server logs with the request or run ID."
