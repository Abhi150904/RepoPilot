from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IssueAnalysis(BaseModel):
    summary: str = Field(description="Short explanation of the reported issue.")
    suspected_area: str = Field(description="Likely part of the codebase involved.")
    likely_cause: str = Field(description="Why the issue is probably happening.")
    risk_level: Literal["low", "medium", "high"] = Field(
        description="Expected implementation risk."
    )


class GitHubIssue(BaseModel):
    number: int
    title: str
    body: str
    url: str
    is_pull_request: bool = False
