from __future__ import annotations

from pydantic import BaseModel, Field


class ImplementationPlan(BaseModel):
    summary: str = Field(description="Brief implementation strategy.")
    steps: list[str] = Field(description="Ordered implementation steps.")
    files_to_inspect: list[str] = Field(
        description="Likely files or areas to inspect once repository access exists."
    )
    tests_required: list[str] = Field(description="Regression tests to add or update.")

