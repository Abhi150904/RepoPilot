from __future__ import annotations

from abc import ABC, abstractmethod
import json
import re

import httpx
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.schemas.code_change import CodeChangeSet, FileChange, SourceFile
from app.schemas.execution import RepairContext
from app.schemas.issue import IssueAnalysis
from app.schemas.plan import ImplementationPlan
from app.schemas.repository import RepositoryContext


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


class GeminiLLMProvider(LLMProvider):
    """Gemini-backed provider for structured code generation."""

    def __init__(
        self,
        api_key: str,
        model: str,
        fallback: LLMProvider | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._fallback = fallback or MockLLMProvider()
        self._timeout_seconds = timeout_seconds

    def analyze_issue(self, issue: str) -> IssueAnalysis:
        return self._fallback.analyze_issue(issue)

    def create_plan(
        self,
        issue: str,
        analysis: IssueAnalysis,
        repository_context: RepositoryContext | None = None,
    ) -> ImplementationPlan:
        return self._fallback.create_plan(
            issue=issue,
            analysis=analysis,
            repository_context=repository_context,
        )

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
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent"
        )
        try:
            response = httpx.post(
                url,
                params={"key": self._api_key},
                json=payload,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Gemini request failed: {exc}") from exc

        return _parse_gemini_change_set(response.json())


def get_llm(role: str, settings: Settings | None = None) -> LLMProvider:
    config = settings or get_settings()

    if config.llm_provider == "mock":
        return MockLLMProvider()
    if config.llm_provider == "gemini":
        if not config.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when REPOPILOT_LLM_PROVIDER=gemini.")
        return GeminiLLMProvider(
            api_key=config.gemini_api_key,
            model=config.llm_model,
        )

    raise ValueError(
        f"Unsupported LLM provider '{config.llm_provider}' for role '{role}'. "
        "This project currently supports REPOPILOT_LLM_PROVIDER=mock or gemini."
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


def _build_gemini_payload(
    issue: str,
    analysis: IssueAnalysis,
    plan: ImplementationPlan,
    target_files: list[SourceFile],
    repair_context: RepairContext | None,
) -> dict[str, object]:
    prompt = {
        "task": "Return structured source-code changes for RepoPilot.",
        "rules": [
            "Return JSON only.",
            "Do not return markdown fences.",
            "Do not return unified diffs.",
            "Only modify paths included in target_files unless creating a clearly justified new file.",
            "For modify actions, proposed_content must be the complete new file content.",
            "Do not omit unchanged parts of modified files.",
        ],
        "output_schema": {
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
        "issue": issue,
        "analysis": analysis.model_dump(),
        "plan": plan.model_dump(),
        "target_files": [file.model_dump() for file in target_files],
        "repair_context": repair_context.model_dump() if repair_context else None,
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


def _parse_gemini_change_set(payload: dict[str, object]) -> CodeChangeSet:
    text = _extract_gemini_text(payload)
    try:
        data = json.loads(_strip_json_fences(text))
    except json.JSONDecodeError as exc:
        raise LLMProviderError("Gemini returned malformed JSON.") from exc

    try:
        return CodeChangeSet.model_validate(data)
    except ValidationError as exc:
        raise LLMProviderError("Gemini returned JSON that does not match CodeChangeSet.") from exc


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
