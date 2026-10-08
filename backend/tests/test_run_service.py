from __future__ import annotations

from sqlalchemy import create_engine

from app.api.runs import RunStore
from app.api.schemas import RunRequest
from app.core.audit import RUN_COMPLETED, RUN_STARTED
from app.services.run_service import RepoPilotRunService


def test_execute_next_queued_claims_and_completes_one_run(monkeypatch) -> None:
    audit = CapturingAuditLogger()
    store = RunStore(engine=create_engine("sqlite+pysqlite:///:memory:", future=True))

    class FakeWorkflow:
        def invoke(self, workflow_input):
            return _reviewed_result(workflow_input["_run_id"])

    import app.services.run_service as service_module

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    service = RepoPilotRunService(run_store=store, audit_logger=audit)
    first = service.create_run(RunRequest(issue="First issue"), request_id="trace-1")
    second = service.create_run(RunRequest(issue="Second issue"), request_id="trace-2")

    completed = service.execute_next_queued()

    assert completed is not None
    assert completed.run_id == first.run_id
    assert completed.lifecycle_status == "completed"
    assert service.get_run(second.run_id).lifecycle_status == "queued"
    assert [event["event_type"] for event in audit.events] == [
        "run.created",
        "run.created",
        RUN_STARTED,
        RUN_COMPLETED,
    ]
    assert audit.events[-1]["metadata"]["request_id"] == "trace-1"


def test_execute_next_queued_returns_none_without_work() -> None:
    service = RepoPilotRunService(run_store=RunStore())

    assert service.execute_next_queued() is None


def test_list_runs_returns_recent_service_runs() -> None:
    service = RepoPilotRunService(run_store=RunStore())
    first = service.create_run(RunRequest(issue="First issue"))
    second = service.create_run(RunRequest(issue="Second issue"))

    runs = service.list_runs()

    assert [run.run_id for run in runs] == [second.run_id, first.run_id]


class CapturingAuditLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(
        self,
        event_type: str,
        *,
        run_id: str | None = None,
        actor: str = "system",
        actor_context: dict[str, object] | None = None,
        metadata: dict[str, object] | None = None,
    ):
        event = {
            "event_type": event_type,
            "run_id": run_id,
            "actor": actor,
            "actor_context": actor_context or {},
            "metadata": metadata or {},
        }
        self.events.append(event)
        return event


def _reviewed_result(run_id: str) -> dict[str, object]:
    return {
        "issue": "Login endpoint returns 500 when email is missing.",
        "_run_id": run_id,
        "modified_files": ["app.py"],
        "diff": "--- app.py\n+++ app.py\n",
        "test_analysis": {
            "status": "passed",
            "summary": "Tests passed.",
            "failure_reason": None,
            "next_action": "ready_for_review",
        },
        "review_result": {
            "approved": True,
            "summary": "Patch looks good.",
            "findings": [],
            "next_action": "await_human_approval",
        },
        "run_summary": {
            "status": "awaiting_approval",
            "summary": "Tests passed and automated review approved the patch.",
            "tests_passed": True,
            "repair_attempts": 0,
            "metrics": None,
            "next_action": "human_review",
        },
    }
