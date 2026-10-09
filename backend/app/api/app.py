from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from app.auth.authorization import AuthorizationError, RepositoryAuthorizationService
from app.auth.github_app import GitHubAppError, GitHubAppService
from app.auth.github_oauth import GitHubOAuthClient, OAuthError
from app.auth.models import AuthSession, RunOwner
from app.auth.sessions import InMemorySessionStore

from app.api.schemas import (
    ApprovalRequest,
    AuthMeResponse,
    AuthUser,
    ErrorResponse,
    EvaluationComparisonResponse,
    EvaluationCaseResultResponse,
    EvaluationMetricResponse,
    EvaluationRunRequest,
    EvaluationRunResponse,
    EvaluationSuiteResponse,
    GitHubInstallationResponse,
    GitHubRepositoriesResponse,
    GitHubRepositoryResponse,
    HealthResponse,
    MetricsResponse,
    PublishRequest,
    ReadinessResponse,
    RejectRequest,
    RunError,
    RunRequest,
    RunResponse,
    RunStatusResponse,
)
from app.core.config import Settings, get_settings, inline_run_execution_enabled, readiness_report
from app.core.audit import AuditLogger
from app.core.llm_usage import LLMUsageRecorder
from app.api.runs import RunStore
from app.evals.service import EvaluationService, EvaluationServiceError
from app.evals.store import EvaluationStore
from app.services.run_service import RepoPilotRunService, RunServiceError


def create_app(
    settings: Settings | None = None,
    service: RepoPilotRunService | None = None,
    session_store: InMemorySessionStore | None = None,
    oauth_client: GitHubOAuthClient | None = None,
    github_app_service: GitHubAppService | None = None,
    evaluation_service: EvaluationService | None = None,
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
    sessions = session_store or InMemorySessionStore()
    oauth = oauth_client or GitHubOAuthClient(config)
    github_app = github_app_service or GitHubAppService(config)
    llm_usage_recorder = LLMUsageRecorder(database_url=config.database_url)
    run_service = service or RepoPilotRunService(
        run_store=RunStore(database_url=config.database_url),
        audit_logger=AuditLogger(database_url=config.database_url),
        llm_usage_recorder=llm_usage_recorder,
        installation_token_resolver=lambda owner: (
            github_app.installation_access_token(installation_id=owner.installation_id)
            if owner.installation_id is not None
            else None
        )
    )
    repository_authorizer = RepositoryAuthorizationService(github_app)
    eval_service = evaluation_service or EvaluationService(
        store=EvaluationStore(database_url=config.database_url),
        settings=config,
        llm_usage_recorder=llm_usage_recorder,
    )

    @api.on_event("startup")
    def recover_interrupted_evaluations() -> None:
        eval_service.recover_interrupted_runs()
    api_logger = logging.getLogger("repopilot.api")

    @api.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid4().hex
        request.state.request_id = request_id
        started_at = perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        _apply_security_headers(response.headers)
        api_logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        return response

    @api.exception_handler(HTTPException)
    def http_exception_handler(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            error_type=_error_code(exc.detail, "http_error"),
            message=_error_message(exc.detail),
            request_id=_request_id(request),
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
            request_id=_request_id(request),
        )

    @api.exception_handler(EvaluationServiceError)
    def evaluation_service_exception_handler(
        request: Request,
        exc: EvaluationServiceError,
    ) -> JSONResponse:
        return _error_response(
            status_code=exc.status_code,
            error_type=exc.code,
            message=exc.message,
            request_id=_request_id(request),
        )

    @api.exception_handler(AuthorizationError)
    def authorization_exception_handler(
        request: Request,
        exc: AuthorizationError,
    ) -> JSONResponse:
        return _error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            error_type="repository_forbidden",
            message="Repository is not authorized for RepoPilot.",
            request_id=_request_id(request),
        )

    @api.exception_handler(OAuthError)
    def oauth_exception_handler(
        request: Request,
        exc: OAuthError,
    ) -> JSONResponse:
        return _auth_error_response(request)

    @api.exception_handler(GitHubAppError)
    def github_app_exception_handler(
        request: Request,
        exc: GitHubAppError,
    ) -> JSONResponse:
        return _auth_error_response(request)

    def _auth_error_response(request: Request) -> JSONResponse:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            error_type="auth_error",
            message="Authentication or GitHub App authorization failed.",
            request_id=_request_id(request),
        )

    @api.exception_handler(PermissionError)
    def permission_exception_handler(
        request: Request,
        exc: PermissionError,
    ) -> JSONResponse:
        return _error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            error_type="forbidden",
            message="Request is not authorized.",
            request_id=_request_id(request),
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
            request_id=_request_id(request),
        )

    @api.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="repopilot")

    @api.get("/ready", response_model=ReadinessResponse)
    def ready() -> JSONResponse:
        report = ReadinessResponse.model_validate(readiness_report(config))
        return JSONResponse(
            status_code=status.HTTP_200_OK if report.status == "ready" else status.HTTP_503_SERVICE_UNAVAILABLE,
            content=report.model_dump(),
        )

    @api.get("/auth/github/login")
    def github_login() -> RedirectResponse:
        state = sessions.create_oauth_state()
        response = RedirectResponse(oauth.login_url(state=state), status_code=status.HTTP_307_TEMPORARY_REDIRECT)
        response.set_cookie(
            "repopilot_oauth_state",
            state,
            httponly=True,
            secure=config.hosted_mode,
            samesite="lax",
            max_age=600,
        )
        return response

    @api.get("/auth/github/callback")
    def github_callback(request: Request, code: str | None = None, state: str | None = None) -> RedirectResponse:
        cookie_state = request.cookies.get("repopilot_oauth_state")
        if not code or not state or state != cookie_state or not sessions.consume_oauth_state(state):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_oauth_state", "message": "Invalid GitHub OAuth state."},
            )
        access_token = oauth.exchange_code(code=code)
        user = oauth.get_user(access_token=access_token)
        session = sessions.create_session(user=user, oauth_access_token=access_token)
        redirect_url = f"{config.public_base_url}/app" if config.public_base_url else "/app"
        response = RedirectResponse(redirect_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
        _set_session_cookie(response, session.session_id, secure=config.hosted_mode)
        response.delete_cookie("repopilot_oauth_state")
        return response

    @api.post("/auth/logout")
    def logout(request: Request) -> AuthMeResponse:
        session_id = request.cookies.get("repopilot_session")
        sessions.delete_session(session_id)
        response = JSONResponse(content=AuthMeResponse(authenticated=False).model_dump())
        response.delete_cookie("repopilot_session")
        return response

    @api.get("/auth/me", response_model=AuthMeResponse)
    def auth_me(request: Request) -> AuthMeResponse:
        session = _optional_session(request, sessions)
        if session is None:
            return AuthMeResponse(authenticated=False)
        return _auth_me_response(session)

    @api.get("/github/installations", response_model=list[GitHubInstallationResponse])
    def github_installations(request: Request) -> list[GitHubInstallationResponse]:
        if not config.hosted_mode:
            return []
        session = _require_session(request, sessions, config)
        installations = github_app.list_user_installations(oauth_access_token=session.oauth_access_token)
        return [
            GitHubInstallationResponse(
                id=installation["id"],
                account_login=_account_value(installation, "login"),
                account_type=_account_value(installation, "type"),
            )
            for installation in installations
            if isinstance(installation.get("id"), int)
        ]

    @api.get("/github/repositories", response_model=GitHubRepositoriesResponse)
    def github_repositories(request: Request) -> GitHubRepositoriesResponse:
        if not config.hosted_mode:
            return GitHubRepositoriesResponse(repositories=[], install_url=github_app.installation_url())
        session = _require_session(request, sessions, config)
        repositories = github_app.list_authorized_repositories(oauth_access_token=session.oauth_access_token)
        return GitHubRepositoriesResponse(
            repositories=[
                GitHubRepositoryResponse(
                    full_name=repo.full_name,
                    installation_id=repo.installation_id,
                    default_branch=repo.default_branch,
                    private=repo.private,
                )
                for repo in repositories
            ],
            install_url=github_app.installation_url(),
        )

    @api.post(
        "/runs",
        response_model=RunStatusResponse,
        status_code=status.HTTP_202_ACCEPTED,
        responses={422: {"model": ErrorResponse}},
    )
    def create_run(
        request: RunRequest,
        background_tasks: BackgroundTasks,
        http_request: Request,
    ) -> RunStatusResponse:
        session = _require_session(http_request, sessions, config, csrf=True)
        owner = _run_owner_for_request(
            config=config,
            session=session,
            request=request,
            repository_authorizer=repository_authorizer,
        )
        run = run_service.create_run(
            _hosted_initial_request(config=config, request=request),
            request_id=_request_id(http_request),
            owner=owner,
            idempotency_key=http_request.headers.get("Idempotency-Key"),
        )
        if inline_run_execution_enabled(config) and run_service.consume_execution_pending(run.run_id):
            background_tasks.add_task(run_service.execute_next_queued)
        return run

    @api.get("/runs", response_model=list[RunStatusResponse])
    def list_runs(request: Request) -> list[RunStatusResponse]:
        owner = _owner_filter_for_run_list(config=config, request=request, sessions=sessions)
        return run_service.list_runs(owner=owner)

    @api.get(
        "/runs/{run_id}",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}},
    )
    def get_run(run_id: str, request: Request) -> RunStatusResponse:
        _authorize_run_access(config=config, request=request, sessions=sessions, run_service=run_service, run_id=run_id)
        return run_service.get_run(run_id)

    @api.get(
        "/runs/{run_id}/result",
        response_model=RunResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def get_run_result(run_id: str, request: Request) -> RunResponse:
        _authorize_run_access(config=config, request=request, sessions=sessions, run_service=run_service, run_id=run_id)
        return run_service.get_result(run_id)

    @api.post(
        "/runs/{run_id}/approve",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def approve_run(run_id: str, http_request: Request, request: ApprovalRequest | None = None) -> RunStatusResponse:
        session = _require_session(http_request, sessions, config, csrf=True)
        owner = _authorize_run_access(config=config, request=http_request, sessions=sessions, run_service=run_service, run_id=run_id, session=session)
        return run_service.approve_run(run_id, request, actor=_actor_for_session(session), actor_context=_actor_context(owner, session))

    @api.post(
        "/runs/{run_id}/reject",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def reject_run(run_id: str, http_request: Request, request: RejectRequest | None = None) -> RunStatusResponse:
        session = _require_session(http_request, sessions, config, csrf=True)
        owner = _authorize_run_access(config=config, request=http_request, sessions=sessions, run_service=run_service, run_id=run_id, session=session)
        return run_service.reject_run(run_id, request, actor=_actor_for_session(session), actor_context=_actor_context(owner, session))

    @api.post(
        "/runs/{run_id}/publish",
        response_model=RunStatusResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def publish_run(run_id: str, request: PublishRequest, http_request: Request) -> RunStatusResponse:
        session = _require_session(http_request, sessions, config, csrf=True)
        owner = _authorize_run_access(config=config, request=http_request, sessions=sessions, run_service=run_service, run_id=run_id, session=session)
        return run_service.publish_run(run_id, request, actor=_actor_for_session(session), actor_context=_actor_context(owner, session))

    @api.get(
        "/runs/{run_id}/metrics",
        response_model=MetricsResponse,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def get_run_metrics(run_id: str, request: Request) -> MetricsResponse:
        _authorize_run_access(config=config, request=request, sessions=sessions, run_service=run_service, run_id=run_id)
        return run_service.get_metrics(run_id)

    @api.get("/evaluations/suites", response_model=list[EvaluationSuiteResponse])
    def list_evaluation_suites(request: Request) -> list[EvaluationSuiteResponse]:
        _require_session(request, sessions, config)
        return eval_service.list_suites()

    @api.post(
        "/evaluations/runs",
        response_model=EvaluationRunResponse,
        status_code=status.HTTP_202_ACCEPTED,
        responses={422: {"model": ErrorResponse}},
    )
    def create_evaluation_run(
        request: EvaluationRunRequest,
        http_request: Request,
        background_tasks: BackgroundTasks,
    ) -> EvaluationRunResponse:
        session = _require_session(http_request, sessions, config, csrf=True)
        run = eval_service.create_and_run(
            request,
            created_by=_actor_for_session(session),
            idempotency_key=http_request.headers.get("Idempotency-Key"),
            idempotency_owner_key=_eval_idempotency_owner_key(session),
            execute_inline=False,
        )
        if run.status == "queued" and inline_run_execution_enabled(config):
            background_tasks.add_task(eval_service.execute_next_queued)
        return run

    @api.get("/evaluations/runs", response_model=list[EvaluationRunResponse])
    def list_evaluation_runs(request: Request) -> list[EvaluationRunResponse]:
        session = _require_session(request, sessions, config)
        return eval_service.list_runs(owner_key=_eval_owner_key(session))

    @api.get(
        "/evaluations/runs/{eval_run_id}",
        response_model=EvaluationRunResponse,
        responses={404: {"model": ErrorResponse}},
    )
    def get_evaluation_run(eval_run_id: str, request: Request) -> EvaluationRunResponse:
        session = _require_session(request, sessions, config)
        return eval_service.get_run(eval_run_id, owner_key=_eval_owner_key(session))

    @api.get(
        "/evaluations/runs/{eval_run_id}/cases",
        response_model=list[EvaluationCaseResultResponse],
        responses={404: {"model": ErrorResponse}},
    )
    def get_evaluation_cases(eval_run_id: str, request: Request) -> list[EvaluationCaseResultResponse]:
        session = _require_session(request, sessions, config)
        return eval_service.get_run(eval_run_id, owner_key=_eval_owner_key(session)).case_results

    @api.get(
        "/evaluations/runs/{eval_run_id}/metrics",
        response_model=list[EvaluationMetricResponse],
        responses={404: {"model": ErrorResponse}},
    )
    def get_evaluation_metrics(eval_run_id: str, request: Request) -> list[EvaluationMetricResponse]:
        session = _require_session(request, sessions, config)
        return eval_service.get_run(eval_run_id, owner_key=_eval_owner_key(session)).metrics

    @api.get(
        "/evaluations/compare",
        response_model=EvaluationComparisonResponse,
        responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    )
    def compare_evaluation_runs(run_ids: str, request: Request) -> EvaluationComparisonResponse:
        session = _require_session(request, sessions, config)
        return eval_service.compare([item.strip() for item in run_ids.split(",") if item.strip()], owner_key=_eval_owner_key(session))

    return api


def _error_response(
    *,
    status_code: int,
    error_type: str,
    message: str,
    request_id: str | None = None,
) -> JSONResponse:
    details = {"request_id": request_id} if request_id else {}
    payload = ErrorResponse(
        error=RunError(code=error_type, message=message, type=error_type, details=details)
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(),
        headers={"cache-control": "no-store"},
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


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def _optional_session(request: Request, sessions: InMemorySessionStore) -> AuthSession | None:
    return sessions.get_session(request.cookies.get("repopilot_session"))


def _require_session(
    request: Request,
    sessions: InMemorySessionStore,
    config: Settings,
    *,
    csrf: bool = False,
) -> AuthSession | None:
    if not config.hosted_mode:
        return None
    session = _optional_session(request, sessions)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "authentication_required", "message": "Authentication is required."},
        )
    if csrf and request.headers.get("x-csrf-token") != session.csrf_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "csrf_failed", "message": "CSRF validation failed."},
        )
    return session


def _run_owner_for_request(
    *,
    config: Settings,
    session: AuthSession | None,
    request: RunRequest,
    repository_authorizer: RepositoryAuthorizationService,
) -> RunOwner | None:
    if not config.hosted_mode:
        return None
    if session is None:
        raise PermissionError("Authentication is required.")
    return repository_authorizer.owner_for_run(session=session, request=request)


def _hosted_initial_request(*, config: Settings, request: RunRequest) -> RunRequest:
    if not config.hosted_mode:
        return request
    return request.model_copy(
        update={
            "approved": False,
            "publish_dry_run": False,
            "publish_local": False,
            "publish_push": False,
            "publish_pr": False,
        }
    )


def _authorize_run_access(
    *,
    config: Settings,
    request: Request,
    sessions: InMemorySessionStore,
    run_service: RepoPilotRunService,
    run_id: str,
    session: AuthSession | None = None,
) -> RunOwner | None:
    if not config.hosted_mode:
        return None
    active_session = session or _require_session(request, sessions, config)
    if active_session is None:
        raise PermissionError("Authentication is required.")
    requester = RunOwner(
        github_user_id=active_session.user.github_user_id,
        github_login=active_session.user.login,
    )
    owner = run_service.get_owner(run_id)
    if not requester.can_access(owner):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "run_not_found", "message": "Run not found."},
        )
    return owner


def _owner_filter_for_run_list(
    *,
    config: Settings,
    request: Request,
    sessions: InMemorySessionStore,
) -> RunOwner | None:
    if not config.hosted_mode:
        return None
    session = _require_session(request, sessions, config)
    if session is None:
        raise PermissionError("Authentication is required.")
    return RunOwner(
        github_user_id=session.user.github_user_id,
        github_login=session.user.login,
    )


def _auth_me_response(session: AuthSession) -> AuthMeResponse:
    return AuthMeResponse(
        authenticated=True,
        user=AuthUser(
            github_user_id=session.user.github_user_id,
            login=session.user.login,
            avatar_url=session.user.avatar_url,
            name=session.user.name,
        ),
        csrf_token=session.csrf_token,
    )


def _set_session_cookie(response: RedirectResponse, session_id: str, *, secure: bool) -> None:
    response.set_cookie(
        "repopilot_session",
        session_id,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=60 * 60 * 8,
    )


def _account_value(installation: dict[str, object], key: str) -> str | None:
    account = installation.get("account")
    if not isinstance(account, dict):
        return None
    value = account.get(key)
    return value if isinstance(value, str) else None


def _actor_for_session(session: AuthSession | None) -> str:
    return "github_user" if session else "human"


def _actor_context(owner: RunOwner | None, session: AuthSession | None) -> dict[str, object] | None:
    if owner is not None:
        return owner.actor_context()
    if session is None:
        return None
    return {
        "github_user_id": session.user.github_user_id,
        "github_login": session.user.login,
    }


def _eval_idempotency_owner_key(session: AuthSession | None) -> str:
    return _eval_owner_key(session) or "anonymous"


def _eval_owner_key(session: AuthSession | None) -> str | None:
    if session is None:
        return None
    return f"github:{session.user.github_user_id}"


def _apply_security_headers(headers) -> None:
    headers.setdefault("x-content-type-options", "nosniff")
    headers.setdefault("x-frame-options", "DENY")
    headers.setdefault("referrer-policy", "no-referrer")
    headers.setdefault("cache-control", "no-store")


app = create_app()
