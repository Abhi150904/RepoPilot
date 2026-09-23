from __future__ import annotations

from pydantic import BaseModel, Field


class RepositoryFile(BaseModel):
    path: str
    size: int | None = None


class RetrievedFile(BaseModel):
    path: str
    reason: str
    content_preview: str = Field(
        description="Small preview of the file content for planning."
    )


class RepositoryContext(BaseModel):
    repository: str
    query: str
    matched_files: list[RetrievedFile]
