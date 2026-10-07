from __future__ import annotations

import json
import logging

from app.api.schemas import PublishRequest, RunRequest
from app.core.audit import (
    RUN_APPROVED,
    RUN_COMPLETED,
    RUN_CREATED,
    RUN_FAILED,
    RUN_PUBLISHED,
    RUN_REJECTED,
    RUN_STARTED,
    AuditLogger,
)
from app.schemas.execution import GitSafetyReport
from app.services.run_service import RepoPilotRunService


def test_audit_logger_redacts_sensitive_metadata(caplog) -> None:
    logger = logging.getLogger("test.repopilot.audit")
    audit = AuditLogger(logger=logger)

    with caplog.at_level(logging.INFO, logger="test.repopilot.audit"):
        event = audit.record(
            "run.created",
            run_id="run-1",
            metadata={
                "github_token": "secret-token",
                "nested": {"api_key": "secret-key", "safe": "visible"},
            },
        )

    assert event.safe_payload()["metadata"]["github_token"] == "[redacted]"
    payload = json.loads(caplog.records[0].message)
    assert payload["run_id"] == "run-1"
    assert payload["metadata"]["github_token"] == "[redacted]"
    assert payload["metadata"]["nested"]["api_key"] == "[redacted]"
    assert payload["metadata"]["nested"]["safe"] == "visible"
    assert "secret-token" not in caplog.records[0].message
    assert "secret-key" not in caplog.records[0].message


def test_audit_logger_caps_large_metadata(caplog) -> None:
    logger = logging.getLogger("test.repopilot.audit.large")
    audit = AuditLogger(logger=logger)

    with caplog.at_level(logging.INFO, logger="test.repopilot.audit.large"):
        audit.record(
            "run.completed",
            metadata={
                "diff": "x" * 800,
                "items": list(range(25)),
                "mapping": {f"k{i}": i for i in range(45)},
            },
        )

    payload = json.loads(caplog.records[0].message)
    assert payload["metadata"]["diff"].endswith("[truncated 300 chars]")
    assert payload["metadata"]["items"][-1] == {"_truncated": True, "remaining": 5}
    assert payload["metadata"]["mapping"]["_truncated"] is True


def test_run_service_audits_lifecycle_without_raw_issue(monkeypatch) -> None:
    audit = CapturingAuditLogger()

    class FakeWorkflow:
        def invoke(self, workflow_input):
            return _reviewed_result()

    import app.services.run_service as service_module

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    service = RepoPilotRunService(audit_logger=audit)

    run = service.create_run(
        RunRequest(issue="A" * 1000, apply_changes=False, run_tests=False)
    )
    service.execute_run(run.run_id)

    assert [event["event_type"] for event in audit.events] == [
        RUN_CREATED,
        RUN_STARTED,
        RUN_COMPLETED,
    ]
    created = audit.events[0]
    assert created["metadata"]["request"]["mode"] == "issue_text"
    assert "issue" not in created["metadata"]["request"]
    assert "A" * 1000 not in json.dumps(created)
    completed = audit.events[-1]
    assert completed["metadata"]["status"] == "awaiting_approval"
    assert completed["metadata"]["changed_files"] == ["app.py"]


def test_run_service_audits_approval_rejection_and_publication(monkeypatch) -> None:
    audit = CapturingAuditLogger()

    class FakeWorkflow:
        def invoke(self, workflow_input):
            return _reviewed_result(workspace_path=".", modified_files=["app.py"])

    import app.services.run_service as service_module

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    monkeypatch.setattr(
        service_module,
        "inspect_git_safety",
        lambda workspace_path, expected_changed_files: GitSafetyReport(
            status="safe",
            summary="safe",
        ),
    )
    service = RepoPilotRunService(audit_logger=audit)

    run = service.create_run(RunRequest(issue="Login fails"))
    service.execute_run(run.run_id)
    service.approve_run(run.run_id)
    service.publish_run(run.run_id, PublishRequest(mode="dry_run"))

    rejected_run = service.create_run(RunRequest(issue="Destination fails"))
    service.execute_run(rejected_run.run_id)
    service.reject_run(rejected_run.run_id)

    event_types = [event["event_type"] for event in audit.events]
    assert RUN_APPROVED in event_types
    assert RUN_PUBLISHED in event_types
    assert RUN_REJECTED in event_types
    published = next(event for event in audit.events if event["event_type"] == RUN_PUBLISHED)
    assert published["metadata"]["mode"] == "dry_run"
    assert published["metadata"]["status"] == "ready"


def test_run_service_audits_failures_without_exception_message(monkeypatch) -> None:
    audit = CapturingAuditLogger()

    class FakeWorkflow:
        def invoke(self, workflow_input):
            raise RuntimeError("secret failure detail")

    import app.services.run_service as service_module

    monkeypatch.setattr(service_module, "build_workflow", lambda: FakeWorkflow())
    service = RepoPilotRunService(audit_logger=audit)

    run = service.create_run(RunRequest(issue="Login fails"))
    service.execute_run(run.run_id)

    failed = audit.events[-1]
    assert failed["event_type"] == RUN_FAILED
    assert failed["metadata"] == {
        "error_type": "RuntimeError",
        "error_code": "internal_error",
    }
    assert "secret failure detail" not in json.dumps(failed)


class CapturingAuditLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(
        self,
        event_type: str,
        *,
        run_id: str | None = None,
        actor: str = "system",
        metadata: dict[str, object] | None = None,
    ):
        event = {
            "event_type": event_type,
            "run_id": run_id,
            "actor": actor,
            "metadata": metadata or {},
        }
        self.events.append(event)
        return event


def _reviewed_result(
    *,
    workspace_path: str | None = None,
    modified_files: list[str] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "issue": "Login endpoint returns 500 when email is missing.",
        "modified_files": modified_files or ["app.py"],
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
    if workspace_path:
        result["workspace_path"] = workspace_path
    return result
