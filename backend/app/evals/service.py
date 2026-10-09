from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from app.api.schemas import (
    EvaluationComparisonMetric,
    EvaluationComparisonResponse,
    EvaluationRunRequest,
    EvaluationRunResponse,
    EvaluationSuiteResponse,
)
from app.core.config import Settings
from app.core.llm_usage import LLMUsageRecorderProtocol
from app.evals.retrieval import (
    DEFAULT_BENCHMARK_PATH,
    RetrievalBenchmark,
    RetrievalBenchmarkCase,
    default_retrievers,
    load_retrieval_benchmark,
    run_retrieval_benchmark,
)
from app.evals.store import EvaluationConflict, EvaluationStore


class EvaluationServiceError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class EvaluationService:
    def __init__(
        self,
        *,
        store: EvaluationStore,
        settings: Settings,
        llm_usage_recorder: LLMUsageRecorderProtocol | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.llm_usage_recorder = llm_usage_recorder

    def ensure_builtin_suites(self) -> None:
        retrieval = load_retrieval_benchmark(DEFAULT_BENCHMARK_PATH)
        self.store.upsert_suite(
            name="retrieval-core-v1",
            version="1",
            eval_type="retrieval",
            description="Core retrieval benchmark from source-controlled fixtures.",
            cases=[
                {
                    "case_key": case.id,
                    "input_json": {
                        "query": case.query,
                        "query_terms": case.query_terms,
                        "chunks": [chunk.model_dump() for chunk in case.chunks],
                    },
                    "expected_json": {"relevant_paths": case.relevant_paths},
                    "metadata_json": {"k_values": retrieval.k_values},
                }
                for case in retrieval.cases
            ],
        )
        from app.evals import runner as workflow_eval

        workflow_paths = workflow_eval.discover_eval_cases([workflow_eval.DEFAULT_CASE_DIR])
        self.store.upsert_suite(
            name="workflow-core-v1",
            version="1",
            eval_type="workflow",
            description="Core workflow evaluation cases from source-controlled fixtures.",
            cases=[
                {
                    "case_key": workflow_eval.load_eval_case(path).id,
                    "input_json": {"case_path": str(path)},
                    "expected_json": workflow_eval.load_eval_case(path).expectations.model_dump(),
                    "metadata_json": {},
                }
                for path in workflow_paths
            ],
        )

    def list_suites(self) -> list[EvaluationSuiteResponse]:
        self.ensure_builtin_suites()
        return self.store.list_suites()

    def recover_interrupted_runs(self) -> int:
        return self.store.interrupt_running_runs()

    def create_and_run(
        self,
        request: EvaluationRunRequest,
        *,
        created_by: str | None = None,
        idempotency_key: str | None = None,
        idempotency_owner_key: str = "anonymous",
    ) -> EvaluationRunResponse:
        self.ensure_builtin_suites()
        suite = self.store.suite_by_name(request.suite)
        if suite is None:
            raise EvaluationServiceError(status_code=404, code="eval_suite_not_found", message="Evaluation suite not found.")
        configuration = self._validated_configuration(suite.eval_type, request.configuration)
        try:
            created = self.store.create_run(
                suite_id=suite.id,
                configuration=configuration,
                created_by=created_by,
                owner_key=idempotency_owner_key,
                idempotency_key=idempotency_key,
                idempotency_owner_key=idempotency_owner_key,
            )
        except EvaluationConflict as exc:
            raise EvaluationServiceError(
                status_code=409,
                code="idempotency_conflict",
                message="Idempotency-Key was reused with a different evaluation payload.",
            ) from exc
        if not created.created:
            return created.run
        eval_run_id = created.run.id
        self.store.mark_running(eval_run_id)
        try:
            if suite.eval_type == "retrieval":
                self._run_retrieval_suite(eval_run_id, suite.id, configuration)
            elif suite.eval_type == "workflow":
                self._run_workflow_suite(eval_run_id, suite.id, configuration)
            else:
                raise ValueError(f"Unsupported eval type: {suite.eval_type}")
        except Exception as exc:
            self.store.fail_run(eval_run_id, exc)
        run = self.store.get_run(eval_run_id)
        if run is None:
            raise EvaluationServiceError(status_code=404, code="eval_run_not_found", message="Evaluation run not found.")
        return run

    def list_runs(self, *, owner_key: str | None = None) -> list[EvaluationRunResponse]:
        self.ensure_builtin_suites()
        return self.store.list_runs(owner_key=owner_key)

    def get_run(self, eval_run_id: str, *, owner_key: str | None = None) -> EvaluationRunResponse:
        run = self.store.get_run(eval_run_id, owner_key=owner_key)
        if run is None:
            raise EvaluationServiceError(status_code=404, code="eval_run_not_found", message="Evaluation run not found.")
        return run

    def compare(self, run_ids: list[str], *, owner_key: str | None = None) -> EvaluationComparisonResponse:
        if len(run_ids) != 2:
            raise EvaluationServiceError(status_code=422, code="invalid_eval_comparison", message="Exactly two eval run IDs are required.")
        baseline = self.get_run(run_ids[0], owner_key=owner_key)
        current = self.get_run(run_ids[1], owner_key=owner_key)
        compatible = baseline.suite_name == current.suite_name and baseline.suite_id == current.suite_id
        baseline_metrics = {metric.metric_name: metric.metric_value for metric in baseline.metrics}
        current_metrics = {metric.metric_name: metric.metric_value for metric in current.metrics}
        metric_names = sorted(set(baseline_metrics) | set(current_metrics))
        return EvaluationComparisonResponse(
            baseline_run_id=baseline.id,
            current_run_id=current.id,
            compatible=compatible,
            warning=None if compatible else "Evaluation runs use different suites and should not be compared directly.",
            metrics=[
                EvaluationComparisonMetric(
                    metric_name=name,
                    baseline=baseline_metrics.get(name),
                    current=current_metrics.get(name),
                    delta=_delta(baseline_metrics.get(name), current_metrics.get(name)),
                    direction=_metric_direction(name),
                )
                for name in metric_names
            ],
        )

    def _validated_configuration(self, eval_type: str, configuration: dict[str, Any]) -> dict[str, Any]:
        if eval_type == "retrieval":
            strategies = default_retrievers()
            strategy = configuration.get("strategy", "hybrid")
            if not isinstance(strategy, str) or strategy not in strategies:
                raise EvaluationServiceError(status_code=422, code="invalid_eval_config", message="Unknown retrieval strategy.")
            top_k = configuration.get("top_k", 5)
            if not isinstance(top_k, int) or top_k < 1 or top_k > 20:
                raise EvaluationServiceError(status_code=422, code="invalid_eval_config", message="top_k must be an integer from 1 to 20.")
            limit = configuration.get("limit", max(top_k, 5))
            if not isinstance(limit, int) or limit < top_k or limit > 50:
                raise EvaluationServiceError(status_code=422, code="invalid_eval_config", message="limit must be an integer greater than or equal to top_k and at most 50.")
            return {
                "strategy": strategy,
                "top_k": top_k,
                "limit": limit,
                "llm_provider": self.settings.llm_provider,
                "llm_model": self.settings.llm_model,
            }
        if eval_type == "workflow":
            max_cases = configuration.get("max_cases")
            if max_cases is not None and (not isinstance(max_cases, int) or max_cases < 1 or max_cases > 20):
                raise EvaluationServiceError(status_code=422, code="invalid_eval_config", message="max_cases must be an integer from 1 to 20.")
            return {
                "max_cases": max_cases,
                "llm_provider": self.settings.llm_provider,
                "llm_model": self.settings.llm_model,
            }
        raise EvaluationServiceError(status_code=422, code="invalid_eval_config", message="Unsupported evaluation type.")

    def _run_retrieval_suite(self, eval_run_id: str, suite_id: int, configuration: dict[str, Any]) -> None:
        cases = self.store.run_case_snapshots(eval_run_id)
        benchmark = RetrievalBenchmark(
            cases=[
                RetrievalBenchmarkCase(
                    id=str(case["case_key"]),
                    query=case["input_json"]["query"],
                    query_terms=list(case["input_json"].get("query_terms") or []),
                    relevant_paths=list(case["expected_json"]["relevant_paths"]),
                    chunks=case["input_json"]["chunks"],
                )
                for case in cases
            ],
            k_values=[3, 5],
        )
        retrievers = default_retrievers()
        strategy = configuration["strategy"]
        result = run_retrieval_benchmark(
            benchmark,
            retrievers={strategy: retrievers[strategy]},
            limit=configuration["limit"],
        )
        case_lookup = {case["case_key"]: case for case in cases}
        for case_result in result.cases:
            case = case_lookup[case_result.case_id]
            measurements = {
                "recall_at_k": case_result.metrics.recall_at_k,
                "precision_at_k": case_result.metrics.precision_at_k,
                "hit_at_k": case_result.metrics.hit_at_k,
                "mrr": case_result.metrics.mrr,
            }
            self.store.add_case_result(
                eval_run_id=eval_run_id,
                eval_case_id=int(case["id"]),
                status="passed",
                output={"ranked_paths": case_result.ranked_paths},
                measurements=measurements,
                duration_ms=case_result.duration_ms,
            )
        summary = result.summaries[0]
        self.store.complete_run(
            eval_run_id,
            {
                "recall_at_3": summary.avg_recall_at_k.get(3),
                "recall_at_5": summary.avg_recall_at_k.get(5),
                "precision_at_3": summary.avg_precision_at_k.get(3),
                "precision_at_5": summary.avg_precision_at_k.get(5),
                "hit_rate_at_3": summary.hit_rate_at_k.get(3),
                "hit_rate_at_5": summary.hit_rate_at_k.get(5),
                "mrr": summary.avg_mrr,
                "average_case_duration_ms": summary.avg_duration_ms,
                **_empty_usage_metrics(),
            },
        )

    def _run_workflow_suite(self, eval_run_id: str, suite_id: int, configuration: dict[str, Any]) -> None:
        from app.evals import runner as workflow_eval

        cases = self.store.run_case_snapshots(eval_run_id)
        if configuration.get("max_cases") is not None:
            cases = cases[: configuration["max_cases"]]
        passed = 0
        test_applicable = 0
        test_passed = 0
        repair_attempts_total = 0
        repair_applicable = 0
        repair_successes = 0
        durations: list[float] = []
        for case in cases:
            path = Path(case["input_json"]["case_path"])
            started = perf_counter()
            try:
                result = workflow_eval.run_eval_case(
                    path,
                    eval_run_id=eval_run_id,
                    eval_case_id=int(case["id"]),
                    usage_recorder=self.llm_usage_recorder,
                )
                duration_ms = round((perf_counter() - started) * 1000, 4)
                durations.append(duration_ms)
                passed += 1 if result.status == "passed" else 0
                tests_check = next((check for check in result.checks if check.name == "tests_passed" and check.points > 0), None)
                if tests_check is not None:
                    test_applicable += 1
                    test_passed += 1 if tests_check.passed else 0
                self.store.add_case_result(
                    eval_run_id=eval_run_id,
                    eval_case_id=int(case["id"]),
                    status=result.status,
                    output=result.model_dump(),
                    measurements={
                        "score": result.score,
                        "points_earned": result.points_earned,
                        "points_possible": result.points_possible,
                        "repair_attempts": result.repair_attempts,
                        "repair_succeeded": result.repair_succeeded,
                    },
                    duration_ms=duration_ms,
                )
                repair_attempts_total += result.repair_attempts
                if result.repair_attempts > 0:
                    repair_applicable += 1
                    repair_successes += 1 if result.repair_succeeded else 0
            except Exception as exc:
                duration_ms = round((perf_counter() - started) * 1000, 4)
                durations.append(duration_ms)
                self.store.add_case_result(
                    eval_run_id=eval_run_id,
                    eval_case_id=int(case["id"]),
                    status="error",
                    output={},
                    measurements={},
                    duration_ms=duration_ms,
                    error_type=exc.__class__.__name__,
                    safe_error_message="Workflow evaluation case failed. Check server logs for the eval run ID.",
                )
        total = len(cases)
        usage = _usage_metrics(self.llm_usage_recorder, eval_run_id=eval_run_id)
        self.store.complete_run(
            eval_run_id,
            {
                "task_success_rate": _rate(passed, total),
                "test_pass_rate": _rate(test_passed, test_applicable) if test_applicable else None,
                "repair_attempts_total": float(repair_attempts_total),
                "repair_success_rate": _rate(repair_successes, repair_applicable) if repair_applicable else None,
                "average_case_duration_ms": round(sum(durations) / len(durations), 4) if durations else None,
                **usage,
            },
        )


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _delta(baseline: float | None, current: float | None) -> float | None:
    if baseline is None or current is None:
        return None
    return round(current - baseline, 4)


def _usage_metrics(
    recorder: LLMUsageRecorderProtocol | None,
    *,
    eval_run_id: str,
) -> dict[str, float | None]:
    if recorder is None:
        return _empty_usage_metrics()
    aggregate = recorder.aggregate(eval_run_id=eval_run_id)
    return {
        "llm_call_count": _float_or_none(aggregate.get("llm_call_count")),
        "prompt_tokens": _float_or_none(aggregate.get("prompt_tokens")),
        "completion_tokens": _float_or_none(aggregate.get("completion_tokens")),
        "total_tokens": _float_or_none(aggregate.get("total_tokens")),
        "estimated_cost_usd": _float_or_none(aggregate.get("estimated_cost_usd")),
    }


def _empty_usage_metrics() -> dict[str, float | None]:
    return {
        "llm_call_count": 0.0,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "estimated_cost_usd": None,
    }


def _float_or_none(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _metric_direction(name: str) -> Literal["higher_is_better", "lower_is_better", "neutral"]:
    if name in {"recall_at_3", "recall_at_5", "precision_at_3", "precision_at_5", "mrr", "task_success_rate", "test_pass_rate", "repair_success_rate"}:
        return "higher_is_better"
    if name.endswith("duration_ms") or name in {"estimated_cost", "estimated_cost_usd", "total_tokens", "prompt_tokens", "completion_tokens"}:
        return "lower_is_better"
    return "neutral"
