from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceFile(BaseModel):
    path: str
    content: str
    exists: bool = True


class FileChange(BaseModel):
    path: str
    action: Literal["modify", "create"]
    explanation: str
    proposed_content: str | None = None


class CodeChangeSet(BaseModel):
    summary: str
    changes: list[FileChange] = Field(default_factory=list)
    diff: str = ""


class ChangeApplicationResult(BaseModel):
    modified_files: list[str] = Field(default_factory=list)
    diff: str = ""
