from __future__ import annotations

import re

from app.schemas.repository import CodeChunk


BOUNDARY_PATTERN = re.compile(
    r"^\s*(?:"
    r"def\s+|class\s+|async\s+def\s+|"
    r"export\s+(?:const|function|class)\s+|"
    r"(?:const|let|var)\s+[A-Za-z0-9_]+\s*=\s*(?:async\s*)?\(|"
    r"function\s+|"
    r"describe\s*\(|it\s*\("
    r")"
)

SYMBOL_PATTERNS = [
    re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*export\s+(?:const|function|class)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*="),
    re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)"),
]


def chunk_code_file(path: str, content: str, max_lines: int = 80) -> list[CodeChunk]:
    """Split code on common symbol/test boundaries with a line-count fallback."""

    lines = content.splitlines()
    if not lines:
        return []

    boundary_indexes = _find_boundary_indexes(lines)
    if len(boundary_indexes) <= 1:
        return _chunk_by_line_count(path=path, lines=lines, max_lines=max_lines)

    chunks: list[CodeChunk] = []
    for index, start in enumerate(boundary_indexes):
        end = boundary_indexes[index + 1] - 1 if index + 1 < len(boundary_indexes) else len(lines)
        for chunk_start, chunk_end in _split_large_range(start=start, end=end, max_lines=max_lines):
            chunk_lines = lines[chunk_start - 1 : chunk_end]
            chunks.append(
                CodeChunk(
                    path=path,
                    start_line=chunk_start,
                    end_line=chunk_end,
                    content="\n".join(chunk_lines),
                    symbol=_extract_symbol(chunk_lines[0]) if chunk_lines else None,
                )
            )

    return [chunk for chunk in chunks if chunk.content.strip()]


def _find_boundary_indexes(lines: list[str]) -> list[int]:
    boundaries = [
        line_number
        for line_number, line in enumerate(lines, start=1)
        if BOUNDARY_PATTERN.match(line)
    ]
    if 1 not in boundaries:
        boundaries.insert(0, 1)
    return boundaries


def _chunk_by_line_count(path: str, lines: list[str], max_lines: int) -> list[CodeChunk]:
    chunks: list[CodeChunk] = []
    for start in range(1, len(lines) + 1, max_lines):
        end = min(start + max_lines - 1, len(lines))
        content = "\n".join(lines[start - 1 : end])
        if content.strip():
            chunks.append(
                CodeChunk(
                    path=path,
                    start_line=start,
                    end_line=end,
                    content=content,
                )
            )
    return chunks


def _split_large_range(start: int, end: int, max_lines: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    current = start
    while current <= end:
        chunk_end = min(current + max_lines - 1, end)
        ranges.append((current, chunk_end))
        current = chunk_end + 1
    return ranges


def _extract_symbol(line: str) -> str | None:
    for pattern in SYMBOL_PATTERNS:
        match = pattern.match(line)
        if match:
            return match.group(1)
    return None
