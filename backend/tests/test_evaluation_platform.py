from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api.schemas import EvaluationRunRequest
from app.core.config import Settings
from app.evals.models import EvalCaseResult, EvalCheck
from app.evals.service import EvaluationService, EvaluationServiceError
from app.evals.store import EvaluationConflict, EvaluationStore


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


def test_evaluation_runs_are_filtered_by_owner() -> None:
    service = _service()
    request = EvaluationRunRequest(suite="retrieval-core-v1", configuration={"strategy": "keyword", "top_k": 5})

    owner_a = service.create_and_run(request, idempotency_owner_key="owner-a")
    owner_b = service.create_and_run(request, idempotency_owner_key="owner-b")

    assert [run.id for run in service.list_runs(owner_key="owner-a")] == [owner_a.id]
    assert [run.id for run in service.list_runs(owner_key="owner-b")] == [owner_b.id]

    assert service.get_run(owner_a.id, owner_key="owner-a").id == owner_a.id
    with pytest.raises(EvaluationServiceError) as exc_info:
        service.get_run(owner_a.id, owner_key="owner-b")
    assert exc_info.value.status_code == 404


def test_evaluation_restart_recovery_interrupts_running_runs() -> None:
    service = _service()
    service.ensure_builtin_suites()
    suite = service.store.suite_by_name("retrieval-core-v1")
    assert suite is not None
    created = service.store.create_run(
        suite_id=suite.id,
        configuration={},
        created_by="test",
        owner_key="owner-a",
        idempotency_key=None,
        idempotency_owner_key="owner-a",
    )
    service.store.mark_running(created.run.id)

    assert service.recover_interrupted_runs() == 1
    recovered = service.get_run(created.run.id, owner_key="owner-a")
    assert recovered.status == "interrupted"


def test_suite_versions_are_immutable() -> None:
    service = _service()
    service.ensure_builtin_suites()

    with pytest.raises(EvaluationConflict):
        service.store.upsert_suite(
            name="retrieval-core-v1",
            version="1",
            eval_type="retrieval",
            description="Changed benchmark.",
            cases=[
                {
                    "case_key": "changed",
                    "input_json": {"query": "changed"},
                    "expected_json": {"relevant_paths": []},
                    "metadata_json": {},
                }
            ],
        )


def test_workflow_eval_records_repair_metrics(monkeypatch) -> None:
    service = _service()
    service.ensure_builtin_suites()
    suite = service.store.suite_by_name("workflow-core-v1")
    assert suite is not None
    created = service.store.create_run(
        suite_id=suite.id,
        configuration={},
        created_by="test",
        owner_key="owner-a",
        idempotency_key=None,
        idempotency_owner_key="owner-a",
    )

    def fake_run_eval_case(*args, **kwargs):
        return EvalCaseResult(
            id="case-1",
            status="passed",
            checks=[EvalCheck(name="tests_passed", category="tests", passed=True, message="ok")],
            points_earned=1,
            points_possible=1,
            score=1.0,
            repair_attempts=1,
            repair_succeeded=True,
        )

    import app.evals.runner as workflow_eval

    monkeypatch.setattr(workflow_eval, "run_eval_case", fake_run_eval_case)
    service._run_workflow_suite(created.run.id, suite.id, {})
    metrics = {metric.metric_name: metric.metric_value for metric in service.get_run(created.run.id).metrics}

    assert metrics["repair_attempts_total"] == 2.0
    assert metrics["repair_success_rate"] == 1.0


def test_evaluation_service_rejects_unknown_strategy() -> None:
    service = _service()

    with pytest.raises(EvaluationServiceError) as exc_info:
        service.create_and_run(
            EvaluationRunRequest(suite="retrieval-core-v1", configuration={"strategy": "does-not-exist"})
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "invalid_eval_config"
