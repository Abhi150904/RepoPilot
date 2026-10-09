from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from sqlalchemy.types import JSON

from app.api.schemas import (
    EvaluationCaseResultResponse,
    EvaluationMetricResponse,
    EvaluationRunResponse,
    EvaluationSuiteResponse,
)


EvalStatus = Literal["queued", "running", "completed", "failed", "interrupted"]
EvalType = Literal["retrieval", "workflow"]


class EvaluationConflict(Exception):
    pass


class EvaluationBase(DeclarativeBase):
    pass


class EvalSuiteRow(EvaluationBase):
    __tablename__ = "eval_suites"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_eval_suites_name_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    eval_type: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    cases: Mapped[list["EvalCaseRow"]] = relationship(back_populates="suite")


class EvalCaseRow(EvaluationBase):
    __tablename__ = "eval_cases"
    __table_args__ = (UniqueConstraint("suite_id", "case_key", name="uq_eval_cases_suite_case_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    suite_id: Mapped[int] = mapped_column(ForeignKey("eval_suites.id"), nullable=False, index=True)
    case_key: Mapped[str] = mapped_column(String(255), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    expected_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    suite: Mapped[EvalSuiteRow] = relationship(back_populates="cases")


class EvalRunRow(EvaluationBase):
    __tablename__ = "eval_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_owner_key", "idempotency_key", name="uq_eval_runs_idempotency_owner_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    suite_id: Mapped[int] = mapped_column(ForeignKey("eval_suites.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_key: Mapped[str] = mapped_column(String(255), nullable=False, default="anonymous")
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_owner_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    benchmark_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class EvalCaseResultRow(EvaluationBase):
    __tablename__ = "eval_case_results"
    __table_args__ = (UniqueConstraint("eval_run_id", "eval_case_id", name="uq_eval_case_results_run_case"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    eval_run_id: Mapped[str] = mapped_column(ForeignKey("eval_runs.id"), nullable=False, index=True)
    eval_case_id: Mapped[int] = mapped_column(ForeignKey("eval_cases.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    measurements_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvalMetricRow(EvaluationBase):
    __tablename__ = "eval_metrics"
    __table_args__ = (UniqueConstraint("eval_run_id", "metric_name", name="uq_eval_metrics_run_metric"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    eval_run_id: Mapped[str] = mapped_column(ForeignKey("eval_runs.id"), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


@dataclass(frozen=True)
class EvalRunCreateResult:
    run: EvaluationRunResponse
    created: bool


class EvaluationStore:
    def __init__(self, database_url: str | None = None, engine: Engine | None = None) -> None:
        self._engine = engine or (create_engine(database_url, future=True) if database_url else create_engine("sqlite+pysqlite:///:memory:", future=True))
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)
        if engine is not None or database_url is None or database_url.startswith("sqlite"):
            EvaluationBase.metadata.create_all(self._engine)

    def upsert_suite(
        self,
        *,
        name: str,
        eval_type: EvalType,
        version: str,
        description: str | None,
        cases: list[dict[str, Any]],
    ) -> EvaluationSuiteResponse:
        now = _now()
        with self._session_factory() as session:
            suite = session.scalars(
                select(EvalSuiteRow).where(EvalSuiteRow.name == name, EvalSuiteRow.version == version)
            ).first()
            if suite is None:
                suite = EvalSuiteRow(
                    name=name,
                    eval_type=eval_type,
                    version=version,
                    description=description,
                    created_at=now,
                )
                session.add(suite)
                session.flush()
            else:
                existing_cases = list(session.scalars(select(EvalCaseRow).where(EvalCaseRow.suite_id == suite.id).order_by(EvalCaseRow.case_key)))
                if suite.eval_type != eval_type or _cases_hash(existing_cases) != _case_payloads_hash(cases):
                    raise EvaluationConflict("Evaluation suite versions are immutable. Bump the suite version when benchmark cases change.")
                suite.description = description
                session.commit()
                return _suite_response(suite)
            for case in cases:
                existing = session.scalars(
                    select(EvalCaseRow).where(EvalCaseRow.suite_id == suite.id, EvalCaseRow.case_key == case["case_key"])
                ).first()
                values = {
                    "input_json": dict(case.get("input_json") or {}),
                    "expected_json": dict(case.get("expected_json") or {}),
                    "metadata_json": dict(case.get("metadata_json") or {}),
                }
                if existing is None:
                    session.add(
                        EvalCaseRow(
                            suite_id=suite.id,
                            case_key=case["case_key"],
                            created_at=now,
                            **values,
                        )
                    )
                else:
                    existing.input_json = values["input_json"]
                    existing.expected_json = values["expected_json"]
                    existing.metadata_json = values["metadata_json"]
            session.commit()
            return _suite_response(suite)

    def list_suites(self) -> list[EvaluationSuiteResponse]:
        with self._session_factory() as session:
            rows = session.scalars(select(EvalSuiteRow).order_by(EvalSuiteRow.name, EvalSuiteRow.version))
            return [_suite_response(row) for row in rows]

    def suite_by_name(self, name: str) -> EvalSuiteRow | None:
        with self._session_factory() as session:
            row = session.scalars(select(EvalSuiteRow).where(EvalSuiteRow.name == name)).first()
            return _detach(row)

    def suite_cases(self, suite_id: int) -> list[EvalCaseRow]:
        with self._session_factory() as session:
            rows = session.scalars(select(EvalCaseRow).where(EvalCaseRow.suite_id == suite_id).order_by(EvalCaseRow.case_key))
            return [_detach(row) for row in rows]

    def run_case_snapshots(self, eval_run_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            row = session.get(EvalRunRow, eval_run_id)
            if row is None:
                raise KeyError(eval_run_id)
            cases = dict(row.benchmark_snapshot_json or {}).get("cases")
            return list(cases) if isinstance(cases, list) else []

    def create_run(
        self,
        *,
        suite_id: int,
        configuration: dict[str, Any],
        created_by: str | None,
        owner_key: str,
        idempotency_key: str | None,
        idempotency_owner_key: str,
    ) -> EvalRunCreateResult:
        now = _now()
        payload_hash = _payload_hash({"suite_id": suite_id, "configuration": configuration})
        with self._session_factory() as session:
            existing = self._existing_idempotent_run(
                session=session,
                idempotency_key=idempotency_key,
                idempotency_owner_key=idempotency_owner_key,
                payload_hash=payload_hash,
            )
            if existing is not None:
                return EvalRunCreateResult(self.get_run(existing.id), created=False)  # type: ignore[arg-type]
            row = EvalRunRow(
                id=uuid4().hex,
                suite_id=suite_id,
                status="queued",
                configuration_json=dict(configuration),
                created_at=now,
                created_by=created_by,
                owner_key=owner_key,
                idempotency_key=idempotency_key,
                idempotency_owner_key=idempotency_owner_key if idempotency_key else None,
                payload_hash=payload_hash if idempotency_key else None,
                benchmark_snapshot_json=_benchmark_snapshot(session, suite_id),
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                if not idempotency_key:
                    raise
                existing = self._existing_idempotent_run(
                    session=session,
                    idempotency_key=idempotency_key,
                    idempotency_owner_key=idempotency_owner_key,
                    payload_hash=payload_hash,
                )
                if existing is not None:
                    return EvalRunCreateResult(self.get_run(existing.id), created=False)  # type: ignore[arg-type]
                raise EvaluationConflict("Idempotency-Key was reused with a different evaluation payload.") from exc
            return EvalRunCreateResult(self.get_run(row.id), created=True)  # type: ignore[arg-type]

    def mark_running(self, eval_run_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(EvalRunRow, eval_run_id)
            if row is None:
                raise KeyError(eval_run_id)
            row.status = "running"
            row.started_at = _now()
            session.commit()

    def interrupt_running_runs(self) -> int:
        now = _now()
        count = 0
        with self._session_factory() as session:
            rows = session.scalars(select(EvalRunRow).where(EvalRunRow.status == "running"))
            for row in rows:
                row.status = "interrupted"
                row.completed_at = now
                row.error_type = "Interrupted"
                row.safe_error_message = "Evaluation was interrupted before completion. Start a new evaluation run to retry."
                count += 1
            session.commit()
        return count

    def complete_run(self, eval_run_id: str, metrics: dict[str, float | None]) -> None:
        now = _now()
        with self._session_factory() as session:
            row = session.get(EvalRunRow, eval_run_id)
            if row is None:
                raise KeyError(eval_run_id)
            row.status = "completed"
            row.completed_at = now
            for name, value in metrics.items():
                session.add(EvalMetricRow(eval_run_id=eval_run_id, metric_name=name, metric_value=value, metadata_json={}))
            session.commit()

    def fail_run(self, eval_run_id: str, exc: Exception) -> None:
        with self._session_factory() as session:
            row = session.get(EvalRunRow, eval_run_id)
            if row is None:
                raise KeyError(eval_run_id)
            row.status = "failed"
            row.completed_at = _now()
            row.error_type = exc.__class__.__name__
            row.safe_error_message = _safe_error_message(exc)
            session.commit()

    def add_case_result(
        self,
        *,
        eval_run_id: str,
        eval_case_id: int,
        status: Literal["passed", "failed", "error"],
        output: dict[str, Any],
        measurements: dict[str, Any],
        duration_ms: float | None,
        error_type: str | None = None,
        safe_error_message: str | None = None,
    ) -> None:
        with self._session_factory() as session:
            session.add(
                EvalCaseResultRow(
                    eval_run_id=eval_run_id,
                    eval_case_id=eval_case_id,
                    status=status,
                    output_json=output,
                    measurements_json=measurements,
                    duration_ms=duration_ms,
                    error_type=error_type,
                    safe_error_message=safe_error_message,
                    created_at=_now(),
                )
            )
            session.commit()

    def get_run(self, eval_run_id: str, *, owner_key: str | None = None) -> EvaluationRunResponse | None:
        with self._session_factory() as session:
            row = session.get(EvalRunRow, eval_run_id)
            if row is None:
                return None
            if owner_key is not None and row.owner_key != owner_key:
                return None
            suite = session.get(EvalSuiteRow, row.suite_id)
            return _run_response(
                row=row,
                suite=suite,
                metrics=_metrics_for_run(session, row.id),
                case_results=_case_results_for_run(session, row.id),
            )

    def list_runs(self, *, owner_key: str | None = None, limit: int = 50) -> list[EvaluationRunResponse]:
        with self._session_factory() as session:
            statement = select(EvalRunRow).order_by(EvalRunRow.created_at.desc()).limit(limit)
            if owner_key is not None:
                statement = statement.where(EvalRunRow.owner_key == owner_key)
            rows = list(session.scalars(statement))
            return [
                _run_response(
                    row=row,
                    suite=session.get(EvalSuiteRow, row.suite_id),
                    metrics=_metrics_for_run(session, row.id),
                    case_results=_case_results_for_run(session, row.id),
                )
                for row in rows
            ]

    def _existing_idempotent_run(
        self,
        *,
        session: Session,
        idempotency_key: str | None,
        idempotency_owner_key: str,
        payload_hash: str,
    ) -> EvalRunRow | None:
        if not idempotency_key:
            return None
        row = session.scalars(
            select(EvalRunRow).where(
                EvalRunRow.idempotency_key == idempotency_key,
                EvalRunRow.idempotency_owner_key == idempotency_owner_key,
            )
        ).first()
        if row is None:
            return None
        if row.payload_hash != payload_hash:
            raise EvaluationConflict("Idempotency-Key was reused with a different evaluation payload.")
        return row


def _suite_response(row: EvalSuiteRow) -> EvaluationSuiteResponse:
    return EvaluationSuiteResponse(
        id=row.id,
        name=row.name,
        description=row.description,
        eval_type=row.eval_type,  # type: ignore[arg-type]
        version=row.version,
        created_at=row.created_at,
    )


def _run_response(
    *,
    row: EvalRunRow,
    suite: EvalSuiteRow | None,
    metrics: list[EvaluationMetricResponse],
    case_results: list[EvaluationCaseResultResponse],
) -> EvaluationRunResponse:
    return EvaluationRunResponse(
        id=row.id,
        suite_id=row.suite_id,
        suite_name=suite.name if suite else "unknown",
        eval_type=(suite.eval_type if suite else "retrieval"),  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        configuration=dict(row.configuration_json or {}),
        metrics=metrics,
        case_results=case_results,
        started_at=row.started_at,
        completed_at=row.completed_at,
        created_at=row.created_at,
        created_by=row.created_by,
        error_type=row.error_type,
        safe_error_message=row.safe_error_message,
    )


def _benchmark_snapshot(session: Session, suite_id: int) -> dict[str, Any]:
    suite = session.get(EvalSuiteRow, suite_id)
    cases = list(session.scalars(select(EvalCaseRow).where(EvalCaseRow.suite_id == suite_id).order_by(EvalCaseRow.case_key)))
    snapshot_cases = [
        {
            "id": case.id,
            "case_key": case.case_key,
            "input_json": dict(case.input_json or {}),
            "expected_json": dict(case.expected_json or {}),
            "metadata_json": dict(case.metadata_json or {}),
        }
        for case in cases
    ]
    return {
        "suite": {
            "id": suite.id if suite else suite_id,
            "name": suite.name if suite else "unknown",
            "version": suite.version if suite else "unknown",
            "eval_type": suite.eval_type if suite else "unknown",
            "description": suite.description if suite else None,
        },
        "cases": snapshot_cases,
        "snapshot_hash": _payload_hash({"suite_id": suite_id, "cases": snapshot_cases}),
    }


def _metrics_for_run(session: Session, eval_run_id: str) -> list[EvaluationMetricResponse]:
    rows = session.scalars(select(EvalMetricRow).where(EvalMetricRow.eval_run_id == eval_run_id).order_by(EvalMetricRow.metric_name))
    return [
        EvaluationMetricResponse(
            metric_name=row.metric_name,
            metric_value=row.metric_value,
            metadata=dict(row.metadata_json or {}),
        )
        for row in rows
    ]


def _case_results_for_run(session: Session, eval_run_id: str) -> list[EvaluationCaseResultResponse]:
    rows = session.scalars(
        select(EvalCaseResultRow)
        .where(EvalCaseResultRow.eval_run_id == eval_run_id)
        .order_by(EvalCaseResultRow.id)
    )
    case_map = {
        case.id: case.case_key
        for case in session.scalars(select(EvalCaseRow))
    }
    return [
        EvaluationCaseResultResponse(
            id=row.id,
            eval_run_id=row.eval_run_id,
            eval_case_id=row.eval_case_id,
            case_key=case_map.get(row.eval_case_id, "unknown"),
            status=row.status,  # type: ignore[arg-type]
            output=dict(row.output_json or {}),
            measurements=dict(row.measurements_json or {}),
            error_type=row.error_type,
            safe_error_message=row.safe_error_message,
            duration_ms=row.duration_ms,
            created_at=row.created_at,
        )
        for row in rows
    ]


def _detach(row):
    return row


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _cases_hash(cases: list[EvalCaseRow]) -> str:
    return _payload_hash(
        {
            "cases": [
                {
                    "case_key": case.case_key,
                    "input_json": case.input_json,
                    "expected_json": case.expected_json,
                    "metadata_json": case.metadata_json,
                }
                for case in sorted(cases, key=lambda item: item.case_key)
            ]
        }
    )


def _case_payloads_hash(cases: list[dict[str, Any]]) -> str:
    return _payload_hash(
        {
            "cases": [
                {
                    "case_key": case["case_key"],
                    "input_json": dict(case.get("input_json") or {}),
                    "expected_json": dict(case.get("expected_json") or {}),
                    "metadata_json": dict(case.get("metadata_json") or {}),
                }
                for case in sorted(cases, key=lambda item: str(item["case_key"]))
            ]
        }
    )


def _safe_error_message(exc: Exception) -> str:
    if exc.__class__.__name__ == "ValueError":
        return str(exc)
    return "Evaluation failed. Check server logs for the evaluation run ID."
