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
    score: float | None = None
    source: str = "keyword"


class RepositoryContext(BaseModel):
    repository: str
    query: str
    matched_files: list[RetrievedFile]


class CodeChunk(BaseModel):
    path: str
    start_line: int
    end_line: int
    content: str
    symbol: str | None = None


class RetrievalResult(BaseModel):
    chunk: CodeChunk
    score: float
    matched_terms: list[str]
    source: str = "keyword"
