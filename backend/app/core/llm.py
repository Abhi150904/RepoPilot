from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.config import Settings, get_settings
from app.schemas.issue import IssueAnalysis
from app.schemas.plan import ImplementationPlan


class LLMProvider(ABC):
    """Small provider interface used by Version 0 agents."""

    @abstractmethod
    def analyze_issue(self, issue: str) -> IssueAnalysis:
        raise NotImplementedError

    @abstractmethod
    def create_plan(self, issue: str, analysis: IssueAnalysis) -> ImplementationPlan:
        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    """Deterministic provider that keeps the first milestone runnable locally."""

    def analyze_issue(self, issue: str) -> IssueAnalysis:
        return IssueAnalysis(
            summary="The login endpoint likely does not validate that email is present.",
            suspected_area="request validation",
            likely_cause="Missing input validation allows a malformed login request to reach code that expects an email value.",
            risk_level="medium",
        )

    def create_plan(self, issue: str, analysis: IssueAnalysis) -> ImplementationPlan:
        return ImplementationPlan(
            summary="Add explicit missing-email validation for the login endpoint.",
            steps=[
                "Locate the login route or controller.",
                "Inspect how request payloads are validated.",
                "Add validation that rejects requests without an email.",
                "Return a clear 400-level error instead of allowing a server error.",
                "Add a regression test for a login request with no email.",
            ],
            files_to_inspect=[
                "login route",
                "request validation schema",
                "login endpoint tests",
            ],
            tests_required=[
                "missing email returns a 400-level validation error",
                "valid login request behavior is unchanged",
            ],
        )


def get_llm(role: str, settings: Settings | None = None) -> LLMProvider:
    config = settings or get_settings()

    if config.llm_provider == "mock":
        return MockLLMProvider()

    raise ValueError(
        f"Unsupported LLM provider '{config.llm_provider}' for role '{role}'. "
        "Version 0 supports only REPOPILOT_LLM_PROVIDER=mock."
    )

