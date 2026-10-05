from __future__ import annotations

from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.runs import RunStore
from app.api.schemas import (
    ErrorResponse,
    HealthResponse,
    RunArtifacts,
    RunError,
    RunRequest,
    RunResponse,
    RunStatusResponse,
)
from app.core.config import Settings, get_settings
from app.graph.workflow import build_workflow


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
            error_type="http_error",
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
            raise HTTPException(status_code=404, detail="Run not found.")
        return run

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
    payload = ErrorResponse(error=RunError(type=error_type, message=message))
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(),
    )


def _error_message(detail: object) -> str:
    if isinstance(detail, str):
        return detail
    return "Request failed."


def _validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Request validation failed."
    message = errors[0].get("msg")
    if isinstance(message, str) and message:
        return message
    return "Request validation failed."


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
