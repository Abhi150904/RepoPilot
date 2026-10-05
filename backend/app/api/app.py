from __future__ import annotations

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.schemas import (
    ApprovalRequest,
    ErrorResponse,
    HealthResponse,
    MetricsResponse,
    PublishRequest,
    RejectRequest,
    RunError,
    RunRequest,
    RunResponse,
    RunStatusResponse,
)
from app.core.config import Settings, get_settings
from app.services.run_service import RepoPilotRunService, RunServiceError


def create_app(
    settings: Settings | None = None,
    service: RepoPilotRunService | None = None,
) -> FastAPI:
    config = settings or get_settings()
    api = FastAPI(title="RepoPilot API", version="0.1.0")
    api.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(config.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    run_service = service or RepoPilotRunService()

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

    @api.exception_handler(RunServiceError)
    def run_service_exception_handler(
        request: Request,
        exc: RunServiceError,
    ) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            error_type=exc.code,
            message=exc.message,
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
        run = run_service.create_run(request)
        background_tasks.add_task(run_service.execute_run, run.run_id)
        return run

    @api.get(
        "/runs/{run_id}",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}},
    )
    def get_run(run_id: str) -> RunStatusResponse:
        return run_service.get_run(run_id)

    @api.get(
        "/runs/{run_id}/result",
        response_model=RunResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def get_run_result(run_id: str) -> RunResponse:
        return run_service.get_result(run_id)

    @api.post(
        "/runs/{run_id}/approve",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def approve_run(run_id: str, request: ApprovalRequest | None = None) -> RunStatusResponse:
        return run_service.approve_run(run_id, request)

    @api.post(
        "/runs/{run_id}/reject",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def reject_run(run_id: str, request: RejectRequest | None = None) -> RunStatusResponse:
        return run_service.reject_run(run_id, request)

    @api.post(
        "/runs/{run_id}/publish",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def publish_run(run_id: str, request: PublishRequest) -> RunStatusResponse:
        return run_service.publish_run(run_id, request)

    @api.get(
        "/runs/{run_id}/metrics",
        response_model=MetricsResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def get_run_metrics(run_id: str) -> MetricsResponse:
        return run_service.get_metrics(run_id)

    return api


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


def _cors_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


app = create_app()
