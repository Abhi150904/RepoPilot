from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Iterator, Protocol

from sqlalchemy import Boolean, DateTime, Float, Integer, String, create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.schemas.execution import LLMUsageEvent


logger = logging.getLogger(__name__)


class LLMUsageBase(DeclarativeBase):
    pass


class LLMUsageEventRow(LLMUsageBase):
    __tablename__ = "llm_usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    eval_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    eval_case_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    usage_source: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repair_attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class LLMCallContext:
    run_id: str | None = None
    eval_run_id: str | None = None
    eval_case_id: int | None = None
    request_id: str | None = None
    recorder: LLMUsageRecorderProtocol | None = None


class LLMUsageRecorderProtocol(Protocol):
    def record(self, context: LLMCallContext, event: LLMUsageEvent) -> None:
        ...

    def aggregate(self, *, run_id: str | None = None, eval_run_id: str | None = None) -> dict[str, object]:
        ...


_current_context: ContextVar[LLMCallContext | None] = ContextVar("repopilot_llm_call_context", default=None)


def current_llm_run_id() -> str | None:
    context = _current_context.get()
    if context is None:
        return None
    return context.run_id or (
        f"eval:{context.eval_run_id}:{context.eval_case_id}" if context.eval_run_id else None
    )


@contextmanager
def llm_call_context(context: LLMCallContext) -> Iterator[None]:
    token = _current_context.set(context)
    try:
        yield
    finally:
        _current_context.reset(token)


def record_llm_usage(event: LLMUsageEvent) -> None:
    context = _current_context.get()
    if context is None or context.recorder is None:
        return
    try:
        context.recorder.record(context, event)
    except Exception:
        logger.exception("Failed to persist LLM usage event.")


class LLMUsageRecorder:
    def __init__(self, database_url: str | None = None, engine: Engine | None = None) -> None:
        self._engine = engine or (create_engine(database_url, future=True, pool_pre_ping=True, pool_recycle=300) if database_url else None)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False) if self._engine else None
        if self._engine and (engine is not None or (database_url and database_url.startswith("sqlite"))):
            LLMUsageBase.metadata.create_all(self._engine)

    def record(self, context: LLMCallContext, event: LLMUsageEvent) -> None:
        if self._session_factory is None:
            return
        with self._session_factory() as session:
            session.add(
                LLMUsageEventRow(
                    run_id=context.run_id,
                    eval_run_id=context.eval_run_id,
                    eval_case_id=context.eval_case_id,
                    request_id=context.request_id,
                    provider=event.provider,
                    model=event.model,
                    role=event.role,
                    usage_source=event.usage_source,
                    prompt_tokens=event.prompt_tokens,
                    completion_tokens=event.output_tokens,
                    total_tokens=event.total_tokens,
                    estimated_cost_usd=event.estimated_cost_usd,
                    duration_ms=event.duration_ms,
                    success=event.success,
                    retry_count=event.retry_count,
                    repair_attempt=event.repair_attempt,
                    error_type=event.error_type,
                    created_at=_now(),
                )
            )
            session.commit()

    def aggregate(self, *, run_id: str | None = None, eval_run_id: str | None = None) -> dict[str, object]:
        if self._session_factory is None:
            return _empty_aggregate()
        if run_id is None and eval_run_id is None:
            return _empty_aggregate()
        with self._session_factory() as session:
            filters = []
            if run_id is not None:
                filters.append(LLMUsageEventRow.run_id == run_id)
            if eval_run_id is not None:
                filters.append(LLMUsageEventRow.eval_run_id == eval_run_id)
            totals = session.execute(
                select(
                    func.count(LLMUsageEventRow.id),
                    func.sum(LLMUsageEventRow.prompt_tokens),
                    func.sum(LLMUsageEventRow.completion_tokens),
                    func.sum(LLMUsageEventRow.total_tokens),
                    func.sum(LLMUsageEventRow.estimated_cost_usd),
                    func.count(LLMUsageEventRow.prompt_tokens),
                    func.count(LLMUsageEventRow.completion_tokens),
                    func.count(LLMUsageEventRow.total_tokens),
                    func.count(LLMUsageEventRow.estimated_cost_usd),
                ).where(*filters)
            ).one()
            by_role_rows = session.execute(
                select(
                    LLMUsageEventRow.role,
                    func.count(LLMUsageEventRow.id),
                    func.sum(LLMUsageEventRow.total_tokens),
                    func.count(LLMUsageEventRow.total_tokens),
                )
                .where(*filters)
                .group_by(LLMUsageEventRow.role)
            ).all()
        return {
            "llm_call_count": int(totals[0] or 0),
            "prompt_tokens": _optional_int(totals[1]) if totals[5] == totals[0] else None,
            "completion_tokens": _optional_int(totals[2]) if totals[6] == totals[0] else None,
            "total_tokens": _optional_int(totals[3]) if totals[7] == totals[0] else None,
            "estimated_cost_usd": _optional_float(totals[4]) if totals[8] == totals[0] else None,
            "by_role": {
                str(role): {
                    "calls": int(calls or 0),
                    "total_tokens": _optional_int(total_tokens) if known == calls else None,
                }
                for role, calls, total_tokens, known in by_role_rows
            },
        }


def _empty_aggregate() -> dict[str, object]:
    return {
        "llm_call_count": 0,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "estimated_cost_usd": None,
        "by_role": {},
    }


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


def _optional_float(value: object) -> float | None:
    return round(float(value), 8) if value is not None else None


def _now() -> datetime:
    return datetime.now(timezone.utc)
