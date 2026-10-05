from __future__ import annotations

from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.runs import RunStore
from app.api.schemas import (
    ApprovalRequest,
    ErrorResponse,
    HealthResponse,
    MetricsResponse,
    PublishRequest,
    RejectRequest,
    RunArtifacts,
    RunError,
    RunRequest,
    RunResponse,
    RunStatusResponse,
)
from app.agents.approval import ApprovalGate
from app.agents.publication import PublicationPreparer
from app.agents.publisher import PublishExecutor
from app.agents.run_summarizer import RunSummarizer
from app.core.config import Settings, get_settings
from app.graph.workflow import build_workflow
from app.schemas.execution import ApprovalDecision, PublicationPackage, PublishResult, ReviewResult
from app.tools.git import inspect_git_safety
from app.tools.github import GitHubClient


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    api = FastAPI(title="RepoPilot API", version="0.1.0")
    api.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(config.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    run_store = RunStore()

    @api.exception_handler(HTTPException)
    def http_exception_handler(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            error_type=_error_code(exc.detail, "http_error"),
            message=_error_message(exc.detail),
        )

    @api.exception_handler(RequestValidationError)
    def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            status_code=422,
            error_type="validation_error",
            message=_validation_message(exc),
        )

    @api.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="repopilot")

    @api.post(
        "/runs",
        response_model=RunStatusResponse,
        status_code=status.HTTP_202_ACCEPTED,
        responses={422: {"model": ErrorResponse}},
    )
    def create_run(
        request: RunRequest,
        background_tasks: BackgroundTasks,
    ) -> RunStatusResponse:
        workflow_input = _workflow_input(request)
        run = run_store.create(workflow_input)
        background_tasks.add_task(_run_workflow_task, run_store, run.run_id, workflow_input)
        return run

    @api.get(
        "/runs/{run_id}",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}},
    )
    def get_run(run_id: str) -> RunStatusResponse:
        run = run_store.get(run_id)
        if run is None:
            raise _api_error(status_code=404, code="run_not_found", message="Run not found.")
        return run

    @api.get(
        "/runs/{run_id}/result",
        response_model=RunResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def get_run_result(run_id: str) -> RunResponse:
        return _completed_response(run_store, run_id)

    @api.post(
        "/runs/{run_id}/approve",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def approve_run(run_id: str, request: ApprovalRequest | None = None) -> RunStatusResponse:
        response = _completed_response(run_store, run_id)
        result = dict(response.result)
        review = _review_result(result)
        approval = ApprovalGate().decide(review=review, approved=True)
        result["approval_decision"] = approval.model_dump()
        if request and request.note:
            result["approval_note"] = request.note
        result["run_summary"] = RunSummarizer().summarize(result).model_dump()
        return run_store.update_response(run_id, _run_response(result))

    @api.post(
        "/runs/{run_id}/reject",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def reject_run(run_id: str, request: RejectRequest | None = None) -> RunStatusResponse:
        response = _completed_response(run_store, run_id)
        result = dict(response.result)
        result["approval_decision"] = ApprovalDecision(
            approved=False,
            status="not_ready",
            summary="Human reviewer rejected this run.",
            next_action="inspect_failure",
        ).model_dump()
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
        return run_store.update_response(run_id, _run_response(result))

    @api.post(
        "/runs/{run_id}/publish",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def publish_run(run_id: str, request: PublishRequest) -> RunStatusResponse:
        response = _completed_response(run_store, run_id)
        result = dict(response.result)
        approval = _approval_decision(result)
        if not approval.approved:
            raise _api_error(
                status_code=409,
                code="approval_required",
                message="Run must be approved before publication.",
            )
        package = _publication_package(result, approval)
        publish_result = _publish(package=package, result=result, mode=request.mode)
        result["publication_package"] = package.model_dump()
        result["publish_result"] = publish_result.model_dump()
        result["run_summary"] = RunSummarizer().summarize(result).model_dump()
        return run_store.update_response(run_id, _run_response(result))

    @api.get(
        "/runs/{run_id}/metrics",
        response_model=MetricsResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def get_run_metrics(run_id: str) -> MetricsResponse:
        response = _completed_response(run_store, run_id)
        metrics = response.run_summary.get("metrics")
        if not isinstance(metrics, dict):
            metrics = response.result.get("run_metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        return MetricsResponse(metrics=metrics)

    return api


def _run_workflow_task(
    run_store: RunStore,
    run_id: str,
    workflow_input: dict[str, Any],
) -> None:
    run_store.mark_running(run_id)
    try:
        result = build_workflow().invoke(workflow_input)
        run_store.mark_completed(run_id, _run_response(result))
    except Exception as exc:
        run_store.mark_failed(run_id, exc)


def _run_response(result: dict[str, Any]) -> RunResponse:
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
        "test_runner": request.test_runner if request.run_tests else None,
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


def _error_response(
    *,
    status_code: int,
    error_type: str,
    message: str,
) -> JSONResponse:
    payload = ErrorResponse(error=RunError(code=error_type, message=message, type=error_type))
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(),
    )


def _error_message(detail: object) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message:
            return message
    return "Request failed."


def _error_code(detail: object, fallback: str) -> str:
    if isinstance(detail, dict):
        code = detail.get("code")
        if isinstance(code, str) and code:
            return code
    return fallback


def _validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Request validation failed."
    message = errors[0].get("msg")
    if isinstance(message, str) and message:
        return message
    return "Request validation failed."


def _api_error(*, status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _completed_response(run_store: RunStore, run_id: str) -> RunResponse:
    run = run_store.get(run_id)
    if run is None:
        raise _api_error(status_code=404, code="run_not_found", message="Run not found.")
    if run.lifecycle_status != "completed" or run.response is None:
        raise _api_error(
            status_code=409,
            code="run_not_ready",
            message="Run result is not available yet.",
        )
    return run.response


def _review_result(result: dict[str, Any]) -> ReviewResult:
    review = result.get("review_result")
    if not isinstance(review, dict):
        raise _api_error(
            status_code=409,
            code="review_unavailable",
            message="Run does not have a review result to approve.",
        )
    return ReviewResult.model_validate(review)


def _approval_decision(result: dict[str, Any]) -> ApprovalDecision:
    approval = result.get("approval_decision")
    if not isinstance(approval, dict):
        raise _api_error(
            status_code=409,
            code="approval_required",
            message="Run must be approved before publication.",
        )
    return ApprovalDecision.model_validate(approval)


def _publication_package(
    result: dict[str, Any],
    approval: ApprovalDecision,
) -> PublicationPackage:
    existing = result.get("publication_package")
    if isinstance(existing, dict):
        return PublicationPackage.model_validate(existing)

    changed_files = _string_list(result.get("modified_files"))
    workspace_path = _string_or_none(result.get("workspace_path"))
    git_safety = None
    if workspace_path:
        git_safety = inspect_git_safety(
            workspace_path=workspace_path,
            expected_changed_files=changed_files,
        )
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
) -> PublishResult:
    executor = PublishExecutor(workspace_path=_string_or_none(result.get("workspace_path")))
    if mode == "dry_run":
        return executor.dry_run(package)

    local_result = executor.publish_local(package)
    if mode == "local" or local_result.status != "published":
        return local_result

    push_result = executor.push_branch(package=package, local_result=local_result)
    if mode == "push" or push_result.status != "published":
        return push_result

    return executor.open_pull_request(
        package=package,
        push_result=push_result,
        repository=_string_or_none(result.get("repository")),
        github=GitHubClient(),
    )


def _cors_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


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


app = create_app()
