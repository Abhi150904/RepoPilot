from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
import json
import re
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.schemas.code_change import CodeChangeSet, FileChange, SourceFile
from app.schemas.execution import (
    LLMUsageEvent,
    RepairContext,
    ReviewFinding,
    ReviewResult,
    TestAnalysis,
)
from app.schemas.issue import IssueAnalysis
from app.schemas.plan import ImplementationPlan
from app.schemas.repository import RepositoryContext

T = TypeVar("T", bound=BaseModel)


class LLMProviderError(RuntimeError):
    """Raised when a model provider cannot produce valid structured output."""


class LLMProvider(ABC):
    """Small provider interface used by Version 0 agents."""

    @abstractmethod
    def analyze_issue(self, issue: str) -> IssueAnalysis:
        raise NotImplementedError

    @abstractmethod
    def create_plan(
        self,
        issue: str,
        analysis: IssueAnalysis,
        repository_context: RepositoryContext | None = None,
    ) -> ImplementationPlan:
        raise NotImplementedError

    @abstractmethod
    def propose_code_changes(
        self,
        issue: str,
        analysis: IssueAnalysis,
        plan: ImplementationPlan,
        target_files: list[SourceFile],
        repair_context: RepairContext | None = None,
    ) -> CodeChangeSet:
        raise NotImplementedError

    @abstractmethod
    def review_changes(
        self,
        issue: str,
        plan: ImplementationPlan,
        change_set: CodeChangeSet,
        diff: str,
        test_analysis: TestAnalysis,
        repair_attempts: int = 0,
    ) -> ReviewResult:
        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    """Deterministic provider that keeps the first milestone runnable locally."""

    def analyze_issue(self, issue: str) -> IssueAnalysis:
        issue_lower = issue.lower()
        subject = _short_subject(issue)
        suspected_area = _guess_suspected_area(issue_lower)
        return IssueAnalysis(
            summary=f"The issue appears related to {subject}.",
            suspected_area=suspected_area,
            likely_cause=_guess_likely_cause(issue_lower, suspected_area),
            risk_level=_guess_risk_level(issue_lower),
        )

    def create_plan(
        self,
        issue: str,
        analysis: IssueAnalysis,
        repository_context: RepositoryContext | None = None,
    ) -> ImplementationPlan:
        files_to_inspect = [
            "login route",
            "request validation schema",
            "login endpoint tests",
        ]
        if repository_context:
            files_to_inspect = (
                [file.path for file in repository_context.matched_files]
                if repository_context.matched_files
                else ["No repository files matched; broaden repository search before editing."]
            )

        return ImplementationPlan(
            summary=f"Investigate and fix the reported behavior in {analysis.suspected_area}.",
            steps=_build_plan_steps(analysis=analysis, has_context=bool(repository_context)),
            files_to_inspect=files_to_inspect,
            tests_required=_build_required_tests(issue),
        )

    def propose_code_changes(
        self,
        issue: str,
        analysis: IssueAnalysis,
        plan: ImplementationPlan,
        target_files: list[SourceFile],
        repair_context: RepairContext | None = None,
    ) -> CodeChangeSet:
        changes = [
            change
            for file in target_files
            if (change := _propose_file_change(issue, plan, file, repair_context)) is not None
        ]
        return CodeChangeSet(
            summary=f"Prepared concrete source changes for {len(changes)} file(s).",
            changes=changes,
        )

    def review_changes(
        self,
        issue: str,
        plan: ImplementationPlan,
        change_set: CodeChangeSet,
        diff: str,
        test_analysis: TestAnalysis,
        repair_attempts: int = 0,
    ) -> ReviewResult:
        findings: list[ReviewFinding] = []
        if test_analysis.status != "passed":
            findings.append(
                ReviewFinding(
                    severity="error",
                    category="correctness",
                    message="Patch cannot be approved because tests did not pass.",
                )
            )
        if not change_set.changes:
            findings.append(
                ReviewFinding(
                    severity="error",
                    category="correctness",
                    message="No source changes were proposed for the issue.",
                )
            )
        if not diff.strip():
            findings.append(
                ReviewFinding(
                    severity="error",
                    category="maintainability",
                    message="No deterministic diff is available for review.",
                )
            )
        approved = not any(finding.severity == "error" for finding in findings)
        return ReviewResult(
            approved=approved,
            summary=(
                "Automated review approved the tested patch."
                if approved
                else "Automated review found issues that should be addressed before human approval."
            ),
            findings=findings,
            next_action="await_human_approval" if approved else "repair",
        )


class GeminiLLMProvider(LLMProvider):
    """Gemini-backed provider for structured code generation."""

    def __init__(
        self,
        api_key: str,
        model: str,
        role: str = "coder",
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        max_output_tokens: int = 8192,
        max_prompt_chars: int = 120_000,
        sleep: object = time.sleep,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._role = role
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._max_output_tokens = max_output_tokens
        self._max_prompt_chars = max_prompt_chars
        self._sleep = sleep
        self._usage_events: list[LLMUsageEvent] = []

    @property
    def usage_events(self) -> list[LLMUsageEvent]:
        return list(self._usage_events)

    def analyze_issue(self, issue: str) -> IssueAnalysis:
        payload = _build_analysis_payload(issue=issue)
        return self._generate_structured(payload=payload, schema=IssueAnalysis)

    def create_plan(
        self,
        issue: str,
        analysis: IssueAnalysis,
        repository_context: RepositoryContext | None = None,
    ) -> ImplementationPlan:
        payload = _build_plan_payload(
            issue=issue,
            analysis=analysis,
            repository_context=repository_context,
        )
        return self._generate_structured(payload=payload, schema=ImplementationPlan)

    def propose_code_changes(
        self,
        issue: str,
        analysis: IssueAnalysis,
        plan: ImplementationPlan,
        target_files: list[SourceFile],
        repair_context: RepairContext | None = None,
    ) -> CodeChangeSet:
        payload = _build_gemini_payload(
            issue=issue,
            analysis=analysis,
            plan=plan,
            target_files=target_files,
            repair_context=repair_context,
        )
        return self._generate_structured(payload=payload, schema=CodeChangeSet)

    def review_changes(
        self,
        issue: str,
        plan: ImplementationPlan,
        change_set: CodeChangeSet,
        diff: str,
        test_analysis: TestAnalysis,
        repair_attempts: int = 0,
    ) -> ReviewResult:
        payload = _build_review_payload(
            issue=issue,
            plan=plan,
            change_set=change_set,
            diff=diff,
            test_analysis=test_analysis,
            repair_attempts=repair_attempts,
        )
        return self._generate_structured(payload=payload, schema=ReviewResult)

    def _generate_structured(self, *, payload: dict[str, object], schema: type[T]) -> T:
        started = time.perf_counter()
        retry_count = 0
        usage_totals = _empty_usage_totals()
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent"
        )
        request_payload = _with_generation_config(
            payload=payload,
            max_output_tokens=self._max_output_tokens,
            max_prompt_chars=self._max_prompt_chars,
        )
        last_parse_error: LLMProviderError | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response, http_retries = self._post_with_retries(
                    url=url,
                    payload=request_payload,
                )
            except LLMProviderError as exc:
                duration_ms = _duration_ms(started)
                self._record_usage_event(
                    usage_totals=usage_totals,
                    duration_ms=duration_ms,
                    success=False,
                    retry_count=retry_count,
                    error=exc,
                )
                raise

            retry_count += http_retries
            usage_totals = _merge_usage_totals(
                usage_totals,
                _extract_gemini_usage_totals(response.json()),
            )
            try:
                parsed = _parse_gemini_structured_output(
                    payload=response.json(),
                    schema=schema,
                    schema_name=schema.__name__,
                )
                self._record_usage_event(
                    usage_totals=usage_totals,
                    duration_ms=_duration_ms(started),
                    success=True,
                    retry_count=retry_count,
                    error=None,
                )
                return parsed
            except LLMProviderError as exc:
                last_parse_error = exc
                if attempt >= self._max_retries:
                    break
                retry_count += 1
                request_payload = _build_schema_repair_payload(
                    original_payload=request_payload,
                    schema_name=schema.__name__,
                    error_message=str(exc),
                )

        assert last_parse_error is not None
        self._record_usage_event(
            usage_totals=usage_totals,
            duration_ms=_duration_ms(started),
            success=False,
            retry_count=retry_count,
            error=last_parse_error,
        )
        raise last_parse_error

    def _post_with_retries(
        self,
        *,
        url: str,
        payload: dict[str, object],
    ) -> tuple[httpx.Response, int]:
        last_error: httpx.HTTPError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = httpx.post(
                    url,
                    params={"key": self._api_key},
                    json=payload,
                    timeout=self._timeout_seconds,
                )
                response.raise_for_status()
                return response, attempt
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self._max_retries or not _is_retryable_http_error(exc):
                    raise LLMProviderError(
                        _format_gemini_http_error(exc, self._model)
                    ) from exc
                self._sleep(_retry_delay_seconds(attempt))

        assert last_error is not None
        raise LLMProviderError(_format_gemini_http_error(last_error, self._model)) from last_error

    def _record_usage_event(
        self,
        *,
        usage_totals: dict[str, int | None],
        duration_ms: float,
        success: bool,
        retry_count: int,
        error: Exception | None,
    ) -> None:
        self._usage_events.append(
            LLMUsageEvent(
                provider="gemini",
                model=self._model,
                role=self._role,
                prompt_tokens=usage_totals["prompt_tokens"],
                output_tokens=usage_totals["output_tokens"],
                total_tokens=usage_totals["total_tokens"],
                estimated_cost_usd=None,
                duration_ms=duration_ms,
                success=success,
                retry_count=retry_count,
                error_type=error.__class__.__name__ if error else None,
                error_message=str(error) if error else None,
            )
        )


def get_llm(role: str, settings: Settings | None = None) -> LLMProvider:
    config = settings or get_settings()
    provider_name = config.llm_provider.strip().lower()

    if provider_name == "mock":
        return MockLLMProvider()
    if provider_name == "gemini":
        if not config.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is required when REPO_PILOT_LLM_PROVIDER=gemini."
            )
        if not config.llm_model.strip():
            raise ValueError(
                "REPO_PILOT_LLM_MODEL is required when REPO_PILOT_LLM_PROVIDER=gemini."
            )
        return GeminiLLMProvider(
            api_key=config.gemini_api_key,
            model=_model_for_role(config, role),
            role=role,
            max_retries=max(0, config.llm_max_retries),
            max_output_tokens=max(1, config.llm_max_output_tokens),
            max_prompt_chars=max(1000, config.llm_max_prompt_chars),
        )

    raise ValueError(
        f"Unsupported LLM provider '{config.llm_provider}' for role '{role}'. "
        "This project currently supports REPO_PILOT_LLM_PROVIDER=mock or gemini."
    )


def _short_subject(issue: str) -> str:
    first_line = issue.strip().splitlines()[0] if issue.strip() else "the reported behavior"
    cleaned = re.sub(r"\s+", " ", first_line).strip(" .")
    return cleaned[:100] or "the reported behavior"


def _guess_suspected_area(issue_lower: str) -> str:
    if any(word in issue_lower for word in ("login", "auth", "token", "jwt")):
        return "authentication flow"
    if any(word in issue_lower for word in ("cli", "command", "argument")):
        return "command-line interface"
    if any(word in issue_lower for word in ("graph", "langgraph", "workflow", "agent")):
        return "agent workflow"
    if any(word in issue_lower for word in ("test", "vitest", "pytest")):
        return "test coverage"
    if any(word in issue_lower for word in ("env", "config", "api key", "model")):
        return "configuration"
    return "application logic"


def _guess_likely_cause(issue_lower: str, suspected_area: str) -> str:
    if any(word in issue_lower for word in ("crash", "error", "exception", "500")):
        return f"Unhandled edge case or missing validation in the {suspected_area}."
    if any(word in issue_lower for word in ("missing", "not available", "not yet")):
        return f"Feature or integration work is incomplete in the {suspected_area}."
    if any(word in issue_lower for word in ("wrong", "incorrect", "invalid")):
        return f"Incorrect branching or data handling in the {suspected_area}."
    return f"The {suspected_area} likely needs inspection against the issue requirements."


def _guess_risk_level(issue_lower: str) -> str:
    if any(word in issue_lower for word in ("security", "data loss", "production", "crash")):
        return "high"
    if any(word in issue_lower for word in ("500", "error", "refactor", "workflow", "agent", "api")):
        return "medium"
    return "low"


def _build_plan_steps(analysis: IssueAnalysis, has_context: bool) -> list[str]:
    steps = [
        f"Review the relevant {analysis.suspected_area} files.",
        "Reproduce or reason through the reported behavior.",
        "Identify the smallest code change that addresses the issue.",
        "Add or update regression tests for the reported behavior.",
        "Run the focused test suite and inspect failures before widening changes.",
    ]
    if not has_context:
        steps.insert(0, "Use repository exploration to identify likely files before editing.")
    return steps


def _build_required_tests(issue: str) -> list[str]:
    subject = _short_subject(issue).lower()
    return [
        f"regression test for: {subject}",
        "existing behavior around the touched code path remains unchanged",
    ]


PROMPT_VERSION = "2026-10-04"


def _build_analysis_payload(issue: str) -> dict[str, object]:
    return _build_gemini_json_payload(
        role="analyzer",
        task="Analyze a software issue for RepoPilot.",
        rules=[
            "Return JSON only.",
            "Keep the analysis concise and implementation-oriented.",
            "Set risk_level to low, medium, or high only.",
            "Do not propose code changes in this step.",
        ],
        output_schema={
            "summary": "short explanation of the reported issue",
            "suspected_area": "likely codebase area involved",
            "likely_cause": "probable cause of the behavior",
            "risk_level": "low | medium | high",
        },
        context={
            "issue": issue,
        },
    )


def _build_plan_payload(
    issue: str,
    analysis: IssueAnalysis,
    repository_context: RepositoryContext | None,
) -> dict[str, object]:
    return _build_gemini_json_payload(
        role="planner",
        task="Create a focused implementation plan for RepoPilot.",
        rules=[
            "Return JSON only.",
            "Keep steps concrete and ordered.",
            "Prefer repository paths from repository_context when provided.",
            "Do not invent exact files when no repository context is available.",
            "Include regression tests that would prove the issue is fixed.",
        ],
        output_schema={
            "summary": "brief implementation strategy",
            "steps": ["ordered implementation step"],
            "files_to_inspect": ["repo path or specific code area"],
            "tests_required": ["regression test to add or update"],
        },
        context={
            "issue": issue,
            "analysis": analysis.model_dump(),
            "repository_context": (
                repository_context.model_dump() if repository_context else None
            ),
        },
    )


def _build_gemini_payload(
    issue: str,
    analysis: IssueAnalysis,
    plan: ImplementationPlan,
    target_files: list[SourceFile],
    repair_context: RepairContext | None,
) -> dict[str, object]:
    return _build_gemini_json_payload(
        role="coder",
        task="Return structured source-code changes for RepoPilot.",
        rules=[
            "Return JSON only.",
            "Do not return markdown fences.",
            "Do not return unified diffs.",
            "Only modify paths included in target_files unless creating a clearly justified new file.",
            "For modify actions, proposed_content must be the complete new file content.",
            "Do not omit unchanged parts of modified files.",
            "Use repair_context.test_summary, repair_context.failure_reason, and repair_context.previous_diff when present.",
        ],
        output_schema={
            "summary": "string",
            "changes": [
                {
                    "path": "string",
                    "action": "modify or create",
                    "explanation": "string",
                    "proposed_content": "complete source file content",
                }
            ],
        },
        context={
            "issue": issue,
            "analysis": analysis.model_dump(),
            "plan": plan.model_dump(),
            "target_files": [file.model_dump() for file in target_files],
            "repair_context": _repair_context_for_prompt(repair_context),
        },
    )


def _build_review_payload(
    issue: str,
    plan: ImplementationPlan,
    change_set: CodeChangeSet,
    diff: str,
    test_analysis: TestAnalysis,
    repair_attempts: int,
) -> dict[str, object]:
    return _build_gemini_json_payload(
        role="reviewer",
        task="Review a tested RepoPilot patch before human approval.",
        rules=[
            "Return JSON only.",
            "Approve only when tests passed and the diff appears relevant to the issue.",
            "Call out correctness, edge case, security, maintainability, and test coverage concerns.",
            "Use severity error for blockers, warning for non-blocking risks, info for context.",
            "Set next_action to await_human_approval when approved, repair when fixable, or needs_human when uncertain.",
        ],
        output_schema={
            "approved": "boolean",
            "summary": "review verdict",
            "findings": [
                {
                    "severity": "info | warning | error",
                    "category": "correctness | edge_cases | error_handling | security | maintainability | test_coverage",
                    "message": "finding text",
                    "path": "optional repo path",
                }
            ],
            "next_action": "await_human_approval | repair | needs_human",
        },
        context={
            "issue": issue,
            "plan": plan.model_dump(),
            "change_set": _change_set_for_prompt(change_set),
            "diff": _truncate_text(diff, 40_000),
            "test_analysis": _test_analysis_for_prompt(test_analysis),
            "repair_attempts": repair_attempts,
        },
    )


def _build_gemini_json_payload(
    *,
    role: str,
    task: str,
    rules: list[str],
    output_schema: dict[str, object],
    context: dict[str, object],
) -> dict[str, object]:
    prompt = {
        "prompt_version": PROMPT_VERSION,
        "role": role,
        "task": task,
        "rules": rules,
        "output_schema": output_schema,
        "context": context,
    }
    return {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": json.dumps(prompt, indent=2),
                    }
                ],
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        },
    }


def _parse_gemini_structured_output(
    *,
    payload: dict[str, object],
    schema: type[T],
    schema_name: str,
) -> T:
    text = _extract_gemini_text(payload)
    try:
        data = json.loads(_strip_json_fences(text))
    except json.JSONDecodeError as exc:
        raise LLMProviderError("Gemini returned malformed JSON.") from exc

    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise LLMProviderError(
            f"Gemini returned JSON that does not match {schema_name}."
        ) from exc


def _format_gemini_http_error(exc: httpx.HTTPError, model: str) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        response_text = exc.response.text.strip()
        detail = f" Response body: {response_text[:500]}" if response_text else ""
        return (
            f"Gemini request failed for model '{model}' with "
            f"{exc.response.status_code} {exc.response.reason_phrase}.{detail}"
        )
    return f"Gemini request failed for model '{model}': {exc}"


def _is_retryable_http_error(exc: httpx.HTTPError) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 429, 500, 502, 503, 504}
    return False


def _retry_delay_seconds(attempt: int) -> float:
    return min(0.25 * (2 ** attempt), 2.0)


def _model_for_role(config: Settings, role: str) -> str:
    role_models = {
        "analyzer": config.analyzer_model,
        "planner": config.planner_model,
        "coder": config.coder_model,
        "reviewer": config.reviewer_model,
    }
    selected = role_models.get(role) or config.llm_model
    return selected.strip()


def _with_generation_config(
    *,
    payload: dict[str, object],
    max_output_tokens: int,
    max_prompt_chars: int,
) -> dict[str, object]:
    capped = deepcopy(payload)
    _cap_payload_text(capped, max_prompt_chars)
    generation_config = capped.setdefault("generationConfig", {})
    if isinstance(generation_config, dict):
        generation_config["maxOutputTokens"] = max_output_tokens
    return capped


def _cap_payload_text(payload: dict[str, object], max_prompt_chars: int) -> None:
    contents = payload.get("contents")
    if not isinstance(contents, list):
        return
    for content in contents:
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                part["text"] = _truncate_text(part["text"], max_prompt_chars)


def _build_schema_repair_payload(
    *,
    original_payload: dict[str, object],
    schema_name: str,
    error_message: str,
) -> dict[str, object]:
    repaired = deepcopy(original_payload)
    contents = repaired.setdefault("contents", [])
    if isinstance(contents, list):
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Your previous response could not be parsed. "
                            f"Return corrected JSON only for schema {schema_name}. "
                            f"Parser error: {error_message}"
                        )
                    }
                ],
            }
        )
    return repaired


def _extract_gemini_usage_totals(payload: dict[str, object]) -> dict[str, int | None]:
    usage = payload.get("usageMetadata")
    if not isinstance(usage, dict):
        return _empty_usage_totals()
    return {
        "prompt_tokens": _optional_int(usage.get("promptTokenCount")),
        "output_tokens": _optional_int(usage.get("candidatesTokenCount")),
        "total_tokens": _optional_int(usage.get("totalTokenCount")),
    }


def _empty_usage_totals() -> dict[str, int | None]:
    return {
        "prompt_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def _merge_usage_totals(
    left: dict[str, int | None],
    right: dict[str, int | None],
) -> dict[str, int | None]:
    return {
        key: _sum_optional_ints(left.get(key), right.get(key))
        for key in ("prompt_tokens", "output_tokens", "total_tokens")
    }


def _sum_optional_ints(left: int | None, right: int | None) -> int | None:
    if left is None:
        return right
    if right is None:
        return left
    return left + right


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _duration_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 4)


def _repair_context_for_prompt(repair_context: RepairContext | None) -> dict[str, object] | None:
    if repair_context is None:
        return None
    data = repair_context.model_dump()
    data["test_summary"] = _truncate_text(str(data.get("test_summary") or ""), 12_000)
    data["failure_reason"] = _truncate_text(str(data.get("failure_reason") or ""), 20_000)
    data["previous_diff"] = _truncate_text(str(data.get("previous_diff") or ""), 40_000)
    return data


def _test_analysis_for_prompt(test_analysis: TestAnalysis) -> dict[str, object]:
    data = test_analysis.model_dump()
    data["summary"] = _truncate_text(str(data.get("summary") or ""), 12_000)
    data["failure_reason"] = _truncate_text(str(data.get("failure_reason") or ""), 20_000)
    return data


def _change_set_for_prompt(change_set: CodeChangeSet) -> dict[str, object]:
    data = change_set.model_dump()
    data["diff"] = _truncate_text(str(data.get("diff") or ""), 40_000)
    for change in data.get("changes", []):
        if isinstance(change, dict) and isinstance(change.get("proposed_content"), str):
            change["proposed_content"] = _truncate_text(change["proposed_content"], 50_000)
    return data


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[truncated {omitted} characters]"


def _extract_gemini_text(payload: dict[str, object]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise LLMProviderError("Gemini response did not include candidates.")

    first = candidates[0]
    if not isinstance(first, dict):
        raise LLMProviderError("Gemini response candidate is malformed.")

    content = first.get("content")
    if not isinstance(content, dict):
        raise LLMProviderError("Gemini response did not include content.")

    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise LLMProviderError("Gemini response did not include text parts.")

    text_parts = [
        part.get("text")
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    if not text_parts:
        raise LLMProviderError("Gemini response text was empty.")
    return "\n".join(text_parts)


def _strip_json_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _propose_file_change(
    issue: str,
    plan: ImplementationPlan,
    file: SourceFile,
    repair_context: RepairContext | None,
) -> FileChange | None:
    issue_lower = issue.lower()
    content = file.content
    proposed = content

    if file.path.endswith(".py"):
        proposed = _repair_python_input_lookup(
            content=proposed,
            issue_lower=issue_lower,
            field="email",
            error_message="email is required",
        )
        proposed = _repair_python_input_lookup(
            content=proposed,
            issue_lower=issue_lower,
            field="destination",
            error_message="destination is required",
        )

    if repair_context and repair_context.failure_reason:
        proposed = _apply_repair_context_hint(
            content=proposed,
            failure_reason=repair_context.failure_reason,
        )

    if proposed == content:
        return None

    return FileChange(
        path=file.path,
        action="modify",
        explanation=f"Apply the implementation plan: {plan.summary}",
        proposed_content=proposed,
    )


def _repair_python_input_lookup(
    content: str,
    issue_lower: str,
    field: str,
    error_message: str,
) -> str:
    if field not in issue_lower:
        return content

    bracket_pattern = re.compile(
        rf"^(?P<indent>\s*)(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<payload>[A-Za-z_][A-Za-z0-9_]*)\[['\"]{field}['\"]\]\s*$",
        re.MULTILINE,
    )

    def replace_bracket_lookup(match: re.Match[str]) -> str:
        indent = match.group("indent")
        name = match.group("name")
        payload = match.group("payload")
        return (
            f"{indent}{name} = {payload}.get(\"{field}\")\n"
            f"{indent}if not {name}:\n"
            f"{indent}    return {{\"error\": \"{error_message}\"}}, 400"
        )

    return bracket_pattern.sub(replace_bracket_lookup, content)


def _apply_repair_context_hint(content: str, failure_reason: str) -> str:
    if "AssertionError" not in failure_reason and "FAILED" not in failure_reason:
        return content
    if "email is required" in content or "destination is required" in content:
        return content
    return content
