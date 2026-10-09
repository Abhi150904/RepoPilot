from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.api.runs import RunStore
from app.api.schemas import EvaluationRunRequest, RunArtifacts, RunResponse
from app.core.config import Settings
from app.evals.service import EvaluationService
from app.evals.store import EvaluationStore


@pytest.mark.skipif(
    not os.getenv("REPOPILOT_TEST_DATABASE_URL"),
    reason="Set REPOPILOT_TEST_DATABASE_URL to run real Postgres persistence acceptance tests.",
)
def test_postgres_create_claim_complete_restart_retrieve() -> None:
    store = RunStore(database_url=os.environ["REPOPILOT_TEST_DATABASE_URL"])
    run = store.create({"issue": f"Postgres acceptance {uuid4().hex}"})

    claimed = store.claim_next_queued()
    assert claimed is not None
    assert claimed.run_id == run.run_id
    assert claimed.lifecycle_status == "running"

    store.mark_completed(
        run.run_id,
        RunResponse(
            status="awaiting_approval",
            next_action="human_review",
            summary="Acceptance run completed.",
            artifacts=RunArtifacts(changed_files=[]),
            run_summary={
                "status": "awaiting_approval",
                "summary": "Acceptance run completed.",
                "tests_passed": None,
                "repair_attempts": 0,
                "metrics": None,
                "next_action": "human_review",
            },
            result={
                "issue": "Postgres acceptance",
                "run_summary": {
                    "status": "awaiting_approval",
                    "summary": "Acceptance run completed.",
                    "tests_passed": None,
                    "repair_attempts": 0,
                    "metrics": None,
                    "next_action": "human_review",
                },
            },
        ),
    )

    reloaded = RunStore(database_url=os.environ["REPOPILOT_TEST_DATABASE_URL"])
    retrieved = reloaded.get(run.run_id)

    assert retrieved is not None
    assert retrieved.lifecycle_status == "completed"
    assert retrieved.response is not None
    assert [event["event_type"] for event in retrieved.events][-1] == "run.completed"


@pytest.mark.skipif(
    not os.getenv("REPOPILOT_TEST_DATABASE_URL"),
    reason="Set REPOPILOT_TEST_DATABASE_URL to run real Postgres persistence acceptance tests.",
)
def test_postgres_evaluation_create_complete_restart_retrieve() -> None:
    service = EvaluationService(
        store=EvaluationStore(database_url=os.environ["REPOPILOT_TEST_DATABASE_URL"]),
        settings=Settings(_env_file=None),
    )

    created = service.create_and_run(
        EvaluationRunRequest(suite="retrieval-core-v1", configuration={"strategy": "keyword", "top_k": 5}),
        created_by="postgres-acceptance",
        idempotency_key=f"eval-{uuid4().hex}",
        idempotency_owner_key="postgres-acceptance",
    )

    reloaded_service = EvaluationService(
        store=EvaluationStore(database_url=os.environ["REPOPILOT_TEST_DATABASE_URL"]),
        settings=Settings(_env_file=None),
    )
    retrieved = reloaded_service.get_run(created.id)

    assert retrieved.status == "completed"
    assert retrieved.case_results
    assert {metric.metric_name for metric in retrieved.metrics} >= {"recall_at_5", "precision_at_5", "mrr"}
