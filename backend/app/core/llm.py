from __future__ import annotations

from abc import ABC, abstractmethod
import re

from app.core.config import Settings, get_settings
from app.schemas.issue import IssueAnalysis
from app.schemas.plan import ImplementationPlan
from app.schemas.repository import RepositoryContext


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


def get_llm(role: str, settings: Settings | None = None) -> LLMProvider:
    config = settings or get_settings()

    if config.llm_provider == "mock":
        return MockLLMProvider()

    raise ValueError(
        f"Unsupported LLM provider '{config.llm_provider}' for role '{role}'. "
        "This project currently supports only REPOPILOT_LLM_PROVIDER=mock."
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
