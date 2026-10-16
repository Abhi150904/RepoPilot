from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from app.api.runs import RunStore
from app.api.schemas import PublishRequest, RunRequest
from app.core.audit import RUN_COMPLETED, RUN_STARTED
from app.core.config import Settings
from app.services.run_service import RepoPilotRunService, RunServiceError


@pytest.mark.parametrize("publication_status", ["publishing", "published"])
@pytest.mark.parametrize("action", ["approve_run", "reject_run"])
def test_publication_locks_review_decisions(monkeypatch, publication_status, action) -> None:
    store = RunStore(engine=create_engine("sqlite+pysqlite:///:memory:", future=True))

    class FakeWorkflow:
        def invoke(self, workflow_input):
            return _reviewed_result(workflow_input["_run_id"])

    import app.services.run_service as service_module

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    service = RepoPilotRunService(run_store=store)
    run = service.create_run(RunRequest(issue="Review lock test"))
    service.execute_next_queued()
    store.mark_publication_status(run.run_id, publication_status, event_type="run.publication_updated")
    before = service.get_run(run.run_id)

    with pytest.raises(RunServiceError) as caught:
        getattr(service, action)(run.run_id)

    assert caught.value.status_code == 409
    assert caught.value.code == "review_locked"
    assert service.get_run(run.run_id) == before


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
    assert "run.stage.analysis" in [event["event_type"] for event in completed.events]
    assert "run.stage.tests" in [event["event_type"] for event in completed.events]
    assert service.get_run(second.run_id).lifecycle_status == "queued"
    assert [event["event_type"] for event in audit.events] == [
        "run.created",
        "run.created",
        RUN_STARTED,
        RUN_COMPLETED,
    ]
    assert audit.events[-1]["metadata"]["request_id"] == "trace-1"


def test_local_queued_run_uses_local_test_runner(monkeypatch) -> None:
    store = RunStore(engine=create_engine("sqlite+pysqlite:///:memory:", future=True))
    captured: dict[str, object] = {}

    class FakeWorkflow:
        def invoke(self, workflow_input):
            captured.update(workflow_input)
            return _reviewed_result(workflow_input["_run_id"])

    import app.services.run_service as service_module

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    monkeypatch.setattr(
        service_module,
        "get_settings",
        lambda: Settings(deployment_environment="local", _env_file=None),
    )
    service = RepoPilotRunService(run_store=store)
    run = service.create_run(
        RunRequest(
            repository="example/demo",
            issue_number=1,
            run_tests=True,
        )
    )

    completed = service.execute_next_queued()

    assert completed is not None
    assert completed.run_id == run.run_id
    assert captured["test_runner"] == "local"


def test_publish_dry_run_reports_blockers_without_binding(monkeypatch) -> None:
    store = RunStore(engine=create_engine("sqlite+pysqlite:///:memory:", future=True))

    class FakeWorkflow:
        def invoke(self, workflow_input):
            result = _reviewed_result(workflow_input["_run_id"])
            result["workspace_path"] = None
            result["approval_decision"] = {
                "approved": True,
                "status": "approved",
                "summary": "Human approval was provided.",
                "next_action": "commit_changes",
            }
            result["approval_binding"] = {
                "status": "unavailable",
                "summary": "Approval could not be bound to workspace contents.",
                "workspace_path": None,
                "changed_files": ["app.py"],
            }
            result["run_summary"]["status"] = "approved"
            return result

    import app.services.run_service as service_module

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    service = RepoPilotRunService(run_store=store)
    run = service.create_run(RunRequest(issue="First issue"))
    completed = service.execute_next_queued()

    assert completed is not None
    updated = service.publish_run(run.run_id, PublishRequest(mode="dry_run"))

    publish_result = updated.response.result["publish_result"]
    assert publish_result["mode"] == "dry_run"
    assert publish_result["status"] == "blocked"
    assert "Git safety report is missing." in publish_result["blockers"]


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
        "analysis": {
            "summary": "Missing validation.",
            "suspected_area": "form handling",
            "likely_cause": "blank input is accepted",
            "risk_level": "low",
        },
        "plan": {
            "summary": "Validate blank input.",
            "steps": ["Trim input", "Block empty feedback"],
            "files_to_inspect": ["app.py"],
            "tests_required": ["blank input"],
        },
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
            "metrics": {
                "stage_timings": [
                    {"stage": "analyzer", "duration_ms": 12.5, "success": True},
                    {"stage": "planner", "duration_ms": 9.5, "success": True},
                ],
            },
            "next_action": "human_review",
        },
        "run_metrics": {
            "stage_timings": [
                {"stage": "analyzer", "duration_ms": 12.5, "success": True},
                {"stage": "planner", "duration_ms": 9.5, "success": True},
            ],
        },
    }
