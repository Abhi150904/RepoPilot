from __future__ import annotations

from collections import Counter
import math

from app.retrieval.embeddings import tokenize_for_embedding
from app.schemas.repository import CodeChunk, RetrievalResult


class BM25Index:
    """In-memory BM25 retriever for sparse code search."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        if k1 <= 0:
            raise ValueError("k1 must be positive.")
        if not 0 <= b <= 1:
            raise ValueError("b must be between 0 and 1.")

        self._k1 = k1
        self._b = b
        self._chunks: list[CodeChunk] = []
        self._term_frequencies: list[Counter[str]] = []
        self._document_frequencies: Counter[str] = Counter()
        self._document_lengths: list[int] = []
        self._average_document_length = 0.0

    def add_chunks(self, chunks: list[CodeChunk]) -> None:
        for chunk in chunks:
            tokens = tokenize_for_embedding(_chunk_search_text(chunk))
            term_frequency = Counter(tokens)

            self._chunks.append(chunk)
            self._term_frequencies.append(term_frequency)
            self._document_lengths.append(len(tokens))
            self._document_frequencies.update(term_frequency.keys())

        if self._document_lengths:
            self._average_document_length = sum(self._document_lengths) / len(
                self._document_lengths
            )

    def search(self, query: str, limit: int = 8) -> list[RetrievalResult]:
        if limit <= 0 or not self._chunks:
            return []

        query_terms = tokenize_for_embedding(query)
        scored_results: list[RetrievalResult] = []

        for index, chunk in enumerate(self._chunks):
            score, matched_terms = self._score_document(
                document_index=index,
                query_terms=query_terms,
            )
            if score <= 0:
                continue

            scored_results.append(
                RetrievalResult(
                    chunk=chunk,
                    score=score,
                    matched_terms=matched_terms,
                    source="bm25",
                )
            )

        scored_results.sort(
            key=lambda result: (-result.score, result.chunk.path, result.chunk.start_line)
        )
        return scored_results[:limit]

    def _score_document(
        self,
        document_index: int,
        query_terms: list[str],
    ) -> tuple[float, list[str]]:
        term_frequency = self._term_frequencies[document_index]
        document_length = self._document_lengths[document_index]
        score = 0.0
        matched_terms: list[str] = []

        for term in query_terms:
            frequency = term_frequency.get(term, 0)
            if frequency == 0:
                continue

            idf = self._inverse_document_frequency(term)
            numerator = frequency * (self._k1 + 1)
            denominator = frequency + self._k1 * (
                1
                - self._b
                + self._b
                * (document_length / max(self._average_document_length, 1.0))
            )
            score += idf * (numerator / denominator)
            matched_terms.append(term)

        return score, matched_terms

    def _inverse_document_frequency(self, term: str) -> float:
        document_count = len(self._chunks)
        documents_with_term = self._document_frequencies.get(term, 0)
        return math.log(1 + (document_count - documents_with_term + 0.5) / (documents_with_term + 0.5))


def _chunk_search_text(chunk: CodeChunk) -> str:
    parts = [chunk.path, chunk.symbol or "", chunk.content]
    return "\n".join(part for part in parts if part)
