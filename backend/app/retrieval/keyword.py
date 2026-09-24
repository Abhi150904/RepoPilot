from __future__ import annotations

import re
from pathlib import PurePosixPath

from app.schemas.repository import CodeChunk, RetrievalResult


def retrieve_keyword_chunks(
    chunks: list[CodeChunk],
    query_terms: list[str],
    limit: int = 8,
) -> list[RetrievalResult]:
    """Rank code chunks with a deterministic keyword baseline."""

    normalized_terms = _dedupe([term.lower() for term in query_terms if term.strip()])
    results: list[RetrievalResult] = []

    for chunk in chunks:
        score, matched_terms = _score_chunk(chunk=chunk, query_terms=normalized_terms)
        if score <= 0:
            continue
        results.append(
            RetrievalResult(
                chunk=chunk,
                score=score,
                matched_terms=matched_terms,
            )
        )

    results.sort(key=lambda result: (-result.score, result.chunk.path, result.chunk.start_line))
    return results[:limit]


def _score_chunk(chunk: CodeChunk, query_terms: list[str]) -> tuple[float, list[str]]:
    path_tokens = set(_tokens(chunk.path))
    filename_tokens = set(_tokens(PurePosixPath(chunk.path).name))
    symbol_tokens = set(_tokens(chunk.symbol or ""))
    content_tokens = _tokens(chunk.content)
    content_token_set = set(content_tokens)

    score = 0.0
    matched_terms: list[str] = []

    for term in query_terms:
        term_count = content_tokens.count(term)
        term_score = 0.0

        if term in path_tokens:
            term_score += 8
        if term in filename_tokens:
            term_score += 5
        if term in symbol_tokens:
            term_score += 4
        if term in content_token_set:
            term_score += min(term_count, 5)

        if term_score > 0:
            score += term_score
            matched_terms.append(term)

    if chunk.path.lower().startswith(("test", "tests")):
        score += 0.5

    return score, matched_terms


def _tokens(text: str) -> list[str]:
    return [_normalize_token(token) for token in re.findall(r"[a-z][a-z0-9]+", text.lower())]


def _normalize_token(token: str) -> str:
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_items: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique_items.append(item)
    return unique_items
