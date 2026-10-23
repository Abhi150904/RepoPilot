from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import subprocess
from threading import Event, Lock, Thread
from typing import Any, Callable
from uuid import uuid4

from app.agents.approval import ApprovalGate
from app.agents.publication import PublicationPreparer
from app.agents.publisher import PublishExecutor
from app.agents.run_summarizer import RunSummarizer
from app.api.runs import FreeRunsExhausted, IdempotencyConflict, RunLimitExceeded, RunLimits, RunStore
from app.api.schemas import (
    ApprovalRequest,
    MetricsResponse,
    PublishRequest,
    RejectRequest,
    RunArtifacts,
    RunRequest,
    RunResponse,
    RunStatusResponse,
)
from app.auth.models import RunOwner
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
from app.core.llm_usage import LLMCallContext, LLMUsageRecorderProtocol, llm_call_context
from app.core.config import get_settings
from app.graph.workflow import build_workflow
from app.schemas.execution import ApprovalDecision, PublicationPackage, PublishResult, ReviewResult
from app.tools.git import inspect_git_safety
from app.tools.github import GitHubClient


logger = logging.getLogger(__name__)


class RunServiceError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class RepoPilotRunService:
    def __init__(
        self,
        run_store: RunStore | None = None,
        audit_logger: AuditLogger | None = None,
        installation_token_resolver: Callable[[RunOwner], str | None] | None = None,
        llm_usage_recorder: LLMUsageRecorderProtocol | None = None,
        lease_seconds: int = 1800,
        heartbeat_interval_seconds: float = 60.0,
    ) -> None:
        self.run_store = run_store or RunStore()
        self.audit_logger = audit_logger or AuditLogger()
        self._installation_token_resolver = installation_token_resolver
        self._llm_usage_recorder = llm_usage_recorder
        self._worker_id = uuid4().hex
        self._lease_seconds = lease_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._request_ids: dict[str, str] = {}
        self._owners: dict[str, RunOwner] = {}
        self._execution_pending: set[str] = set()
        self._transition_lock = Lock()

    def create_run(
        self,
        request: RunRequest,
        *,
        request_id: str | None = None,
        owner: RunOwner | None = None,
        idempotency_key: str | None = None,
        limits: RunLimits | None = None,
    ) -> RunStatusResponse:
        try:
            created = self.run_store.create_result(
                _workflow_input(request),
                request_id=request_id,
                owner=owner,
                idempotency_key=idempotency_key,
                limits=limits,
            )
            run = created.run
        except FreeRunsExhausted as exc:
            raise RunServiceError(status_code=402, code="free_runs_exhausted", message=str(exc)) from exc
        except RunLimitExceeded as exc:
            raise RunServiceError(status_code=429, code="run_limit_reached", message=str(exc)) from exc
        except IdempotencyConflict as exc:
            raise RunServiceError(
                status_code=409,
                code="idempotency_conflict",
                message="Idempotency-Key was reused with a different run payload.",
            ) from exc
        if created.created:
            self._execution_pending.add(run.run_id)
        if request_id:
            self._request_ids[run.run_id] = request_id
        if owner:
            self._owners[run.run_id] = owner
        self.audit_logger.record(
            RUN_CREATED,
            run_id=run.run_id,
            metadata={
                **_trace_metadata(run_id=run.run_id, request_id=request_id),
                **_owner_metadata(owner),
                "request": _audit_request_metadata(run.request),
            },
        )
        return run

    def consume_execution_pending(self, run_id: str) -> bool:
        if run_id not in self._execution_pending:
            return False
        self._execution_pending.remove(run_id)
        return True

    def execute_run(self, run_id: str) -> None:
        run = self.run_store.get(run_id)
        if run is None:
            return
        if run.lifecycle_status == "queued":
            self.run_store.mark_running(
                run_id,
                worker_id=self._worker_id,
                lease_seconds=self._lease_seconds,
            )
            run = self.run_store.get(run_id)
            if run is None:
                return
        if run.lifecycle_status != "running":
            return
        self._execute_claimed_run(run)

    def execute_next_queued(self) -> RunStatusResponse | None:
        run = self.run_store.claim_next_queued(
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if run is None:
            return None
        self._execute_claimed_run(run)
        return self.run_store.get(run.run_id)

    def recover_stale_runs(self) -> int:
        return self.run_store.recover_stale_running_runs()

    def _execute_claimed_run(self, run: RunStatusResponse) -> None:
        run_id = run.run_id
        request_id = self._request_ids.get(run_id) or self.run_store.get_request_id(run_id)
        self.audit_logger.record(
            RUN_STARTED,
            run_id=run_id,
            metadata=_trace_metadata(run_id=run_id, request_id=request_id),
        )
        stop_heartbeat = self._start_lease_heartbeat(run_id)
        try:
            workflow = build_workflow()
            runtime_input = _workflow_runtime_input(
                run.request, run_id=run_id, github_token=self._github_token_for_run(run_id))
            if not self.run_store.begin_execution(run_id, worker_id=self._worker_id):
                return
            with llm_call_context(
                LLMCallContext(
                    run_id=run_id,
                    request_id=request_id,
                    recorder=self._llm_usage_recorder,
                )
            ):
                result = workflow.invoke(runtime_input)
            response = _run_response(result)
            self.run_store.mark_completed(run_id, response)
            self.audit_logger.record(
                RUN_COMPLETED,
                run_id=run_id,
                metadata={
                    **_trace_metadata(run_id=run_id, request_id=request_id),
                    "status": response.status,
                    "next_action": response.next_action,
                    "changed_files": response.artifacts.changed_files,
                },
            )
        except Exception as exc:
            logger.exception(
                "RepoPilot run failed: run_id=%s request_id=%s error_type=%s",
                run_id,
                request_id,
                exc.__class__.__name__,
            )
            self.run_store.mark_failed(run_id, exc, request_id=request_id)
            self.audit_logger.record(
                RUN_FAILED,
                run_id=run_id,
                metadata={
                    **_trace_metadata(run_id=run_id, request_id=request_id),
                    "error_type": exc.__class__.__name__,
                    "error_code": _audit_error_code(exc),
                },
            )
        finally:
            stop_heartbeat()

    def _start_lease_heartbeat(self, run_id: str) -> Callable[[], None]:
        interval = self._heartbeat_interval_seconds
        if interval <= 0:
            return lambda: None
        stop = Event()

        def beat() -> None:
            while not stop.wait(interval):
                try:
                    renewed = self.run_store.renew_run_lease(
                        run_id,
                        worker_id=self._worker_id,
                        lease_seconds=self._lease_seconds,
                    )
                except Exception:
                    logger.exception("RepoPilot run lease heartbeat failed: run_id=%s", run_id)
                    continue
                if not renewed:
                    return

        thread = Thread(target=beat, name=f"repopilot-heartbeat-{run_id[:8]}", daemon=True)
        thread.start()

        def stop_thread() -> None:
            stop.set()
            thread.join(timeout=1)

        return stop_thread

    def get_run(self, run_id: str) -> RunStatusResponse:
        run = self.run_store.get(run_id)
        if run is None:
            raise RunServiceError(status_code=404, code="run_not_found", message="Run not found.")
        return run

    def list_runs(self, *, owner: RunOwner | None = None, limit: int = 50) -> list[RunStatusResponse]:
        return self.run_store.list(owner=owner, limit=limit)

    def get_result(self, run_id: str) -> RunResponse:
        return self._completed_response(run_id)

    def get_owner(self, run_id: str) -> RunOwner | None:
        self.get_run(run_id)
        return self._owners.get(run_id) or self.run_store.get_owner(run_id)

    def approve_run(
        self,
        run_id: str,
        request: ApprovalRequest | None = None,
        actor: str = "human",
        actor_context: dict[str, object] | None = None,
    ) -> RunStatusResponse:
        with self._transition_lock:
            self._ensure_review_mutable(run_id)
            response = self._completed_response(run_id)
            result = dict(response.result)
            review = _review_result(result)
            approval = ApprovalGate().decide(review=review, approved=True)
            result["approval_decision"] = approval.model_dump()
            result["approval_binding"] = _approval_binding(result)
            if request and request.note:
                result["approval_note"] = request.note
            result["run_summary"] = RunSummarizer().summarize(result).model_dump()
            updated = self.run_store.update_response(run_id, _run_response(result))
            self.audit_logger.record(
                RUN_APPROVED,
                run_id=run_id,
                actor=actor,
                actor_context=actor_context,
                metadata={
                    **_trace_metadata(run_id=run_id, request_id=self._request_id_for_run(run_id)),
                    "has_note": bool(request and request.note),
                },
            )
            return updated

    def reject_run(
        self,
        run_id: str,
        request: RejectRequest | None = None,
        actor: str = "human",
        actor_context: dict[str, object] | None = None,
    ) -> RunStatusResponse:
        with self._transition_lock:
            self._ensure_review_mutable(run_id)
            response = self._completed_response(run_id)
            result = dict(response.result)
            result["approval_decision"] = ApprovalDecision(
                approved=False,
                status="not_ready",
                summary="Human reviewer rejected this run.",
                next_action="inspect_failure",
            ).model_dump()
            result.pop("approval_binding", None)
            if request and request.reason:
                result["rejection_reason"] = request.reason
            summary = dict(response.run_summary)
            summary.update(
                {
                    "status": "needs_human",
                    "summary": "Human reviewer rejected this run.",
                    "next_action": "inspect_failure",
                }
            )
            result["run_summary"] = summary
            updated = self.run_store.update_response(run_id, _run_response(result))
            self.audit_logger.record(
                RUN_REJECTED,
                run_id=run_id,
                actor=actor,
                actor_context=actor_context,
                metadata={
                    **_trace_metadata(run_id=run_id, request_id=self._request_id_for_run(run_id)),
                    "has_reason": bool(request and request.reason),
                },
            )
            return updated

    def _ensure_review_mutable(self, run_id: str) -> None:
        if self.get_run(run_id).publication_status in {"publishing", "published"}:
            raise RunServiceError(
                status_code=409,
                code="review_locked",
                message="Review decisions cannot change during or after publication.",
            )

    def publish_run(
        self,
        run_id: str,
        request: PublishRequest,
        actor: str = "system",
        actor_context: dict[str, object] | None = None,
    ) -> RunStatusResponse:
        with self._transition_lock:
            response = self._completed_response(run_id)
            result = dict(response.result)
            approval = _approval_decision(result)
            if not approval.approved:
                raise RunServiceError(
                    status_code=409,
                    code="approval_required",
                    message="Run must be approved before publication.",
                )
            if request.mode != "dry_run":
                _validate_approval_binding(result)
            package = _publication_package(result, approval)
            self.run_store.mark_publication_status(
                run_id,
                "publishing",
                event_type="run.publication_started",
                event_metadata={"mode": request.mode},
            )
            try:
                publish_result = _publish(
                    package=package,
                    result=result,
                    mode=request.mode,
                    previous=_publish_result(result),
                    github_token=self._github_token_for_run(run_id),
                )
            except Exception:
                self.run_store.mark_publication_status(
                    run_id,
                    "failed",
                    event_type="run.publication_failed",
                    event_metadata={"mode": request.mode},
                )
                raise
            result["publication_package"] = package.model_dump()
            result["publish_result"] = publish_result.model_dump()
            result["run_summary"] = RunSummarizer().summarize(result).model_dump()
            updated = self.run_store.update_response(run_id, _run_response(result))
            updated = self.run_store.mark_publication_status(
                run_id,
                updated.publication_status,
                event_type=_publication_event_type(updated.publication_status),
                event_metadata={
                    "mode": request.mode,
                    "status": publish_result.status,
                    "branch_name": publish_result.branch_name,
                    "pr_url": publish_result.pr_url,
                },
            )
            self.audit_logger.record(
                RUN_PUBLISHED,
                run_id=run_id,
                actor=actor,
                actor_context=actor_context,
                metadata={
                    **_trace_metadata(run_id=run_id, request_id=self._request_id_for_run(run_id)),
                    "mode": request.mode,
                    "status": publish_result.status,
                    "branch_name": publish_result.branch_name,
                    "pr_url": publish_result.pr_url,
                },
            )
            return updated

    def get_metrics(self, run_id: str) -> MetricsResponse:
        response = self._completed_response(run_id)
        metrics = response.run_summary.get("metrics")
        if not isinstance(metrics, dict):
            metrics = response.result.get("run_metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        return MetricsResponse(metrics=metrics)

    def _completed_response(self, run_id: str) -> RunResponse:
        run = self.get_run(run_id)
        if run.lifecycle_status != "completed" or run.response is None:
            raise RunServiceError(
                status_code=409,
                code="run_not_ready",
                message="Run result is not available yet.",
            )
        return run.response

    def _github_token_for_run(self, run_id: str) -> str | None:
        owner = self._owners.get(run_id) or self.run_store.get_owner(run_id)
        if owner is None or self._installation_token_resolver is None:
            return None
        return self._installation_token_resolver(owner)

    def _request_id_for_run(self, run_id: str) -> str | None:
        return self._request_ids.get(run_id) or self.run_store.get_request_id(run_id)


def _workflow_input(request: RunRequest) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if request.repository is not None and request.issue_number is not None:
        data["repository"] = request.repository
        data["issue_number"] = request.issue_number
    elif request.issue is not None:
        data["issue"] = request.issue

    optional_fields = {
        "apply_changes": request.apply_changes,
        "workspace_path": request.workspace_path,
        "run_tests": request.run_tests,
        "test_runner": _test_runner_for_request(request) if request.run_tests else None,
        "test_command": request.test_command,
        "max_repair_attempts": request.max_repair_attempts,
        "approved": request.approved,
        "publish_dry_run": request.publish_dry_run,
        "publish_local": request.publish_local,
        "publish_push": request.publish_push,
        "publish_pr": request.publish_pr,
    }
    for key, value in optional_fields.items():
        if value not in (None, False):
            data[key] = value
    return data


def _test_runner_for_request(request: RunRequest) -> str:
    settings = get_settings()
    if settings.hosted_mode or settings.deployment_environment == "staging":
        return "docker"
    if request.test_runner == "docker" and settings.deployment_environment == "local":
        return "local"
    return request.test_runner


def _workflow_runtime_input(
    request: dict[str, Any],
    *,
    run_id: str,
    github_token: str | None,
) -> dict[str, Any]:
    data = dict(request)
    data["_run_id"] = run_id
    if github_token:
        data["_github_token"] = github_token
    return data


def _audit_request_metadata(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "github" if "repository" in request else "issue_text",
        "repository": _string_or_none(request.get("repository")),
        "issue_number": request.get("issue_number") if isinstance(request.get("issue_number"), int) else None,
        "apply_changes": request.get("apply_changes") is True,
        "run_tests": request.get("run_tests") is True,
        "publication_requested": any(
            request.get(key) is True
            for key in ("publish_dry_run", "publish_local", "publish_push", "publish_pr")
        ),
    }


def _trace_metadata(*, run_id: str, request_id: str | None = None) -> dict[str, str]:
    metadata = {"run_id": run_id}
    if request_id:
        metadata["request_id"] = request_id
    return metadata


def _owner_metadata(owner: RunOwner | None) -> dict[str, object]:
    if owner is None:
        return {}
    return {
        "owner": owner.actor_context(),
    }


def _run_response(result: dict[str, Any]) -> RunResponse:
    result = _public_result(result)
    summary = result.get("run_summary")
    if not isinstance(summary, dict):
        raise ValueError("Workflow completed without a run summary.")
    return RunResponse(
        status=str(summary.get("status", "unknown")),
        next_action=str(summary.get("next_action", "inspect_failure")),
        summary=str(summary.get("summary", "")),
        artifacts=_run_artifacts(result=result, summary=summary),
        run_summary=summary,
        result=dict(result),
    )


def _public_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if not key.startswith("_") and "token" not in key.lower() and "secret" not in key.lower()
    }


def _review_result(result: dict[str, Any]) -> ReviewResult:
    review = result.get("review_result")
    if not isinstance(review, dict):
        raise RunServiceError(
            status_code=409,
            code="review_unavailable",
            message="Run does not have a review result to approve.",
        )
    return ReviewResult.model_validate(review)


def _approval_decision(result: dict[str, Any]) -> ApprovalDecision:
    approval = result.get("approval_decision")
    if not isinstance(approval, dict):
        raise RunServiceError(
            status_code=409,
            code="approval_required",
            message="Run must be approved before publication.",
        )
    return ApprovalDecision.model_validate(approval)


def _publish_result(result: dict[str, Any]) -> PublishResult | None:
    publish_result = result.get("publish_result")
    if not isinstance(publish_result, dict):
        return None
    return PublishResult.model_validate(publish_result)


def _approval_binding(result: dict[str, Any]) -> dict[str, Any]:
    workspace_path = _string_or_none(result.get("workspace_path"))
    changed_files = _string_list(result.get("modified_files"))
    if not workspace_path or not changed_files:
        return {
            "status": "unavailable",
            "summary": "Approval could not be bound to workspace contents.",
            "workspace_path": workspace_path,
            "changed_files": changed_files,
        }

    safety = inspect_git_safety(
        workspace_path=workspace_path,
        expected_changed_files=changed_files,
    )
    return {
        "status": "bound" if safety.status == "safe" else "needs_attention",
        "summary": "Approval is bound to the current workspace contents.",
        "workspace_path": workspace_path,
        "changed_files": changed_files,
        "content_digest": _workspace_content_digest(
            workspace_path=workspace_path,
            changed_files=changed_files,
        ),
        "head_commit": _git_output(workspace_path, "rev-parse", "HEAD"),
        "git_safety": safety.model_dump(),
    }


def _validate_approval_binding(result: dict[str, Any]) -> None:
    binding = result.get("approval_binding")
    if not isinstance(binding, dict):
        raise RunServiceError(
            status_code=409,
            code="approval_binding_required",
            message="Run approval must be bound to workspace contents before publication.",
        )
    if binding.get("status") != "bound":
        raise RunServiceError(
            status_code=409,
            code="approval_binding_unavailable",
            message="Run approval could not be safely bound to workspace contents.",
        )

    workspace_path = _string_or_none(binding.get("workspace_path"))
    changed_files = _string_list(binding.get("changed_files"))
    if not workspace_path or not changed_files:
        raise RunServiceError(
            status_code=409,
            code="approval_binding_unavailable",
            message="Run approval is missing workspace binding details.",
        )

    safety = inspect_git_safety(
        workspace_path=workspace_path,
        expected_changed_files=changed_files,
    )
    if safety.status != "safe":
        raise RunServiceError(
            status_code=409,
            code="git_safety_failed",
            message="Workspace safety must be revalidated before publication.",
        )

    current_digest = _workspace_content_digest(
        workspace_path=workspace_path,
        changed_files=changed_files,
    )
    if binding.get("content_digest") != current_digest:
        raise RunServiceError(
            status_code=409,
            code="approval_binding_stale",
            message="Workspace contents changed after approval. Re-approve before publishing.",
        )


def _publication_package(
    result: dict[str, Any],
    approval: ApprovalDecision,
) -> PublicationPackage:
    changed_files = _string_list(result.get("modified_files"))
    workspace_path = _string_or_none(result.get("workspace_path"))
    git_safety = None
    if workspace_path:
        git_safety = inspect_git_safety(
            workspace_path=workspace_path,
            expected_changed_files=changed_files,
        )

    existing = result.get("publication_package")
    if isinstance(existing, dict):
        package = PublicationPackage.model_validate(existing)
        return package.model_copy(update={"git_safety": git_safety})

    run_workspace = _dict_or_none(result.get("run_workspace"))
    branch_name = None
    branch_exists = False
    if run_workspace:
        branch_name = _string_or_none(run_workspace.get("branch_name"))
        branch_exists = branch_name is not None

    return PublicationPreparer().prepare(
        issue=str(result.get("issue", "RepoPilot changes")),
        approval=approval,
        changed_files=changed_files,
        issue_number=result.get("issue_number") if isinstance(result.get("issue_number"), int) else None,
        repository=_string_or_none(result.get("repository")),
        git_safety=git_safety,
        branch_name=branch_name,
        branch_exists=branch_exists,
    )


def _publish(
    *,
    package: PublicationPackage,
    result: dict[str, Any],
    mode: str,
    previous: PublishResult | None = None,
    github_token: str | None = None,
) -> PublishResult:
    executor = PublishExecutor(
        workspace_path=_string_or_none(result.get("workspace_path")),
        github_token=github_token,
    )
    if mode == "dry_run":
        return executor.dry_run(package)

    if previous and previous.mode in ("local", "push", "pr") and previous.status == "published":
        local_result = previous
    else:
        local_result = executor.publish_local(package)
    if mode == "local" or local_result.status != "published":
        return local_result

    if previous and previous.mode in ("push", "pr") and previous.status == "published":
        push_result = previous
    else:
        push_result = executor.push_branch(package=package, local_result=local_result)
    if mode == "push" or push_result.status != "published":
        return push_result

    if previous and previous.mode == "pr" and previous.status == "published":
        return previous

    return executor.open_pull_request(
        package=package,
        push_result=push_result,
        repository=_string_or_none(result.get("repository")),
        github=GitHubClient(token=github_token),
    )


def _workspace_content_digest(*, workspace_path: str, changed_files: list[str]) -> str:
    root = Path(workspace_path)
    digest = hashlib.sha256()
    for path in sorted(changed_files):
        digest.update(path.encode("utf-8"))
        file_path = root / path
        if file_path.exists() and file_path.is_file():
            digest.update(file_path.read_bytes())
        else:
            digest.update(b"<missing>")
    return digest.hexdigest()


def _git_output(workspace_path: str, *args: str) -> str | None:
    completed = subprocess.run(
        ["git", *args],
        cwd=workspace_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _run_artifacts(
    *,
    result: dict[str, Any],
    summary: dict[str, Any],
) -> RunArtifacts:
    run_workspace = _dict_or_none(result.get("run_workspace"))
    publish_result = _dict_or_none(result.get("publish_result"))
    publication_package = _dict_or_none(result.get("publication_package"))
    branch_name = _first_string(
        run_workspace.get("branch_name") if run_workspace else None,
        publish_result.get("branch_name") if publish_result else None,
        publication_package.get("branch_name") if publication_package else None,
    )
    pr_url = _first_string(
        publish_result.get("pr_url") if publish_result else None,
        publication_package.get("pr_url") if publication_package else None,
    )

    return RunArtifacts(
        issue_url=_string_or_none(result.get("issue_url")),
        workspace_path=_string_or_none(result.get("workspace_path")),
        branch_name=branch_name,
        changed_files=_string_list(result.get("modified_files")),
        diff=_non_empty_string_or_none(result.get("diff")),
        tests_passed=_bool_or_none(summary.get("tests_passed")),
        test_result=_dict_or_none(result.get("test_result")),
        test_analysis=_dict_or_none(result.get("test_analysis")),
        review_result=_dict_or_none(result.get("review_result")),
        publication_package=publication_package,
        publish_result=publish_result,
        pr_url=pr_url,
    )


def _dict_or_none(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


def _non_empty_string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _first_string(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def _bool_or_none(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _audit_error_code(exc: Exception) -> str:
    name = exc.__class__.__name__.lower()
    if "github" in name:
        return "github_error"
    if "workspace" in name:
        return "workspace_error"
    if "provider" in name or "llm" in name:
        return "provider_error"
    return "internal_error"


def _publication_event_type(status: str) -> str:
    if status == "published":
        return "run.publication_published"
    if status == "failed":
        return "run.publication_failed"
    if status == "ready":
        return "run.publication_ready"
    return "run.publication_updated"
