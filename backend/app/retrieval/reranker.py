from __future__ import annotations

from typing import Protocol

from app.retrieval.embeddings import tokenize_for_embedding
from app.schemas.repository import RetrievalResult


class Reranker(Protocol):
    def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        limit: int = 8,
    ) -> list[RetrievalResult]:
        """Return reranked retrieval results."""


class NoOpReranker:
    """Preserves the existing retrieval order."""

    def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        limit: int = 8,
    ) -> list[RetrievalResult]:
        if limit <= 0:
            return []
        return results[:limit]


class HeuristicReranker:
    """Small deterministic reranker used before model-backed reranking exists."""

    def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        limit: int = 8,
    ) -> list[RetrievalResult]:
        if limit <= 0 or not results:
            return []

        query_terms = tokenize_for_embedding(query)
        query_mentions_test = any(term in {"test", "tests", "testing"} for term in query_terms)
        reranked = [
            _copy_with_rerank_score(
                result=result,
                query_terms=query_terms,
                query_mentions_test=query_mentions_test,
            )
            for result in results
        ]
        reranked.sort(key=lambda result: (-result.score, result.chunk.path, result.chunk.start_line))
        return reranked[:limit]


def _copy_with_rerank_score(
    result: RetrievalResult,
    query_terms: list[str],
    query_mentions_test: bool,
) -> RetrievalResult:
    chunk = result.chunk
    path_terms = set(tokenize_for_embedding(chunk.path))
    symbol_terms = set(tokenize_for_embedding(chunk.symbol or ""))
    content_terms = tokenize_for_embedding(chunk.content)
    early_content_terms = set(tokenize_for_embedding("\n".join(chunk.content.splitlines()[:12])))

    boost = 0.0
    for term in query_terms:
        if term in path_terms:
            boost += 0.15
        if term in symbol_terms:
            boost += 0.25
        if term in early_content_terms:
            boost += 0.12
        elif term in content_terms:
            boost += 0.05

    if _is_test_path(chunk.path) and not query_mentions_test:
        boost -= 0.05

    return RetrievalResult(
        chunk=chunk,
        score=max(result.score + boost, 0.0),
        matched_terms=result.matched_terms,
        source="reranked",
    )


def _is_test_path(path: str) -> bool:
    path_lower = path.lower()
    return (
        path_lower.startswith(("test/", "tests/"))
        or ".test." in path_lower
        or ".spec." in path_lower
    )
