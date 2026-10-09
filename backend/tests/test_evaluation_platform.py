from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api.schemas import EvaluationRunRequest
from app.core.config import Settings
from app.evals.service import EvaluationService, EvaluationServiceError
from app.evals.store import EvaluationStore


def _service() -> EvaluationService:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    return EvaluationService(store=EvaluationStore(engine=engine), settings=Settings(_env_file=None))


def test_retrieval_evaluation_persists_cases_metrics_and_comparison() -> None:
    service = _service()

    first = service.create_and_run(
        EvaluationRunRequest(suite="retrieval-core-v1", configuration={"strategy": "keyword", "top_k": 5}),
        created_by="test",
    )
    second = service.create_and_run(
        EvaluationRunRequest(suite="retrieval-core-v1", configuration={"strategy": "hybrid", "top_k": 5}),
        created_by="test",
    )

    reloaded = service.get_run(first.id)
    assert reloaded.status == "completed"
    assert reloaded.case_results
    assert {metric.metric_name for metric in reloaded.metrics} >= {
        "recall_at_3",
        "recall_at_5",
        "precision_at_3",
        "precision_at_5",
        "hit_rate_at_3",
        "hit_rate_at_5",
        "mrr",
        "average_case_duration_ms",
        "llm_call_count",
        "total_tokens",
        "estimated_cost_usd",
    }
    assert all(metric.metric_value is None or metric.metric_value >= 0 for metric in reloaded.metrics)

    comparison = service.compare([first.id, second.id])
    assert comparison.compatible is True
    assert {metric.metric_name for metric in comparison.metrics} >= {"recall_at_5", "mrr"}


def test_evaluation_idempotency_is_scoped_per_owner() -> None:
    service = _service()
    request = EvaluationRunRequest(suite="retrieval-core-v1", configuration={"strategy": "keyword", "top_k": 5})

    first = service.create_and_run(request, idempotency_key="repeat-me", idempotency_owner_key="owner-a")
    repeated = service.create_and_run(request, idempotency_key="repeat-me", idempotency_owner_key="owner-a")
    other_owner = service.create_and_run(request, idempotency_key="repeat-me", idempotency_owner_key="owner-b")

    assert repeated.id == first.id
    assert other_owner.id != first.id

    with pytest.raises(EvaluationServiceError) as exc_info:
        service.create_and_run(
            EvaluationRunRequest(suite="retrieval-core-v1", configuration={"strategy": "hybrid", "top_k": 5}),
            idempotency_key="repeat-me",
            idempotency_owner_key="owner-a",
        )
    assert exc_info.value.status_code == 409


def test_evaluation_service_rejects_unknown_strategy() -> None:
    service = _service()

    with pytest.raises(EvaluationServiceError) as exc_info:
        service.create_and_run(
            EvaluationRunRequest(suite="retrieval-core-v1", configuration={"strategy": "does-not-exist"})
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "invalid_eval_config"
