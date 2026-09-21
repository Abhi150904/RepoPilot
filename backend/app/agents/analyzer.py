from __future__ import annotations

from app.core.llm import LLMProvider
from app.schemas.issue import IssueAnalysis


class IssueAnalyzer:
    """Produces a structured analysis for a software issue."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def analyze(self, issue: str) -> IssueAnalysis:
        return self._llm.analyze_issue(issue)

