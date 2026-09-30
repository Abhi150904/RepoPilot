from __future__ import annotations

from pathlib import Path


class WorkspacePathError(ValueError):
    """Raised when a requested file path escapes the allowed workspace."""


class WorkspaceFileSystem:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()

    def resolve_path(self, relative_path: str) -> Path:
        path = (self._root / relative_path).resolve()
        if path != self._root and self._root not in path.parents:
            raise WorkspacePathError(f"Path escapes workspace: {relative_path}")
        return path

    def read_text(self, relative_path: str) -> str:
        return self.resolve_path(relative_path).read_text(encoding="utf-8")

    def write_text(self, relative_path: str, content: str) -> None:
        path = self.resolve_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def file_exists(self, relative_path: str) -> bool:
        return self.resolve_path(relative_path).exists()
