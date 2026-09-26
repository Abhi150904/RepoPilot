from __future__ import annotations

from dataclasses import dataclass

from app.retrieval.bm25 import BM25Index
from app.retrieval.embeddings import EmbeddingProvider, HashEmbeddingProvider
from app.retrieval.keyword import retrieve_keyword_chunks
from app.retrieval.vector import InMemoryVectorIndex
from app.schemas.repository import CodeChunk, RetrievalResult


@dataclass(frozen=True)
class HybridRetrievalWeights:
    keyword: float = 0.4
    bm25: float = 0.4
    vector: float = 0.2

    def validate(self) -> None:
        if self.keyword < 0 or self.bm25 < 0 or self.vector < 0:
            raise ValueError("Hybrid retrieval weights cannot be negative.")
        if self.keyword + self.bm25 + self.vector <= 0:
            raise ValueError("At least one hybrid retrieval weight must be positive.")


class HybridRetriever:
    """Combines keyword, BM25, and vector retrieval into one ranked result list."""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        weights: HybridRetrievalWeights | None = None,
    ) -> None:
        self._embedding_provider = embedding_provider or HashEmbeddingProvider()
        self._weights = weights or HybridRetrievalWeights()
        self._weights.validate()

    def search(
        self,
        chunks: list[CodeChunk],
        query_terms: list[str],
        limit: int = 8,
    ) -> list[RetrievalResult]:
        if limit <= 0 or not chunks or not query_terms:
            return []

        query = " ".join(query_terms)
        keyword_results = retrieve_keyword_chunks(
            chunks=chunks,
            query_terms=query_terms,
            limit=len(chunks),
        )

        bm25_index = BM25Index()
        bm25_index.add_chunks(chunks)
        bm25_results = bm25_index.search(query=query, limit=len(chunks))

        vector_index = InMemoryVectorIndex(embedding_provider=self._embedding_provider)
        vector_index.add_chunks(chunks)
        vector_results = vector_index.search(query=query, limit=len(chunks))

        merged = _merge_results(
            weighted_results=[
                (keyword_results, self._weights.keyword),
                (bm25_results, self._weights.bm25),
                (vector_results, self._weights.vector),
            ]
        )
        merged.sort(key=lambda result: (-result.score, result.chunk.path, result.chunk.start_line))
        return merged[:limit]


def _merge_results(
    weighted_results: list[tuple[list[RetrievalResult], float]],
) -> list[RetrievalResult]:
    merged: dict[tuple[str, int, int], RetrievalResult] = {}

    for results, weight in weighted_results:
        if weight <= 0:
            continue

        max_score = max((result.score for result in results), default=0.0)
        if max_score <= 0:
            continue

        for result in results:
            key = (result.chunk.path, result.chunk.start_line, result.chunk.end_line)
            normalized_score = result.score / max_score
            weighted_score = normalized_score * weight

            if key not in merged:
                merged[key] = RetrievalResult(
                    chunk=result.chunk,
                    score=weighted_score,
                    matched_terms=result.matched_terms,
                    source="hybrid",
                )
                continue

            existing = merged[key]
            existing.score += weighted_score
            existing.matched_terms = _dedupe([*existing.matched_terms, *result.matched_terms])

    return list(merged.values())


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_items: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique_items.append(item)
    return unique_items
