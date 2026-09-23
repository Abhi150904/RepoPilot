from __future__ import annotations

from app.core.llm import LLMProvider
from app.schemas.issue import IssueAnalysis
from app.schemas.plan import ImplementationPlan
from app.schemas.repository import RepositoryContext


class Planner:
    """Creates a structured implementation plan from an issue analysis."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def create_plan(
        self,
        issue: str,
        analysis: IssueAnalysis,
        repository_context: RepositoryContext | None = None,
    ) -> ImplementationPlan:
        return self._llm.create_plan(
            issue=issue,
            analysis=analysis,
            repository_context=repository_context,
        )
