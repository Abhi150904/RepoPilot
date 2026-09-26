from __future__ import annotations

from app.retrieval.embeddings import EmbeddingProvider, tokenize_for_embedding
from app.schemas.repository import CodeChunk, RetrievalResult


class InMemoryVectorIndex:
    """Simple vector index used before introducing an external vector database."""

    def __init__(self, embedding_provider: EmbeddingProvider) -> None:
        self._embedding_provider = embedding_provider
        self._items: list[tuple[CodeChunk, list[float]]] = []

    def add_chunks(self, chunks: list[CodeChunk]) -> None:
        texts = [_chunk_embedding_text(chunk) for chunk in chunks]
        vectors = self._embedding_provider.embed_texts(texts)
        self._items.extend(zip(chunks, vectors))

    def search(self, query: str, limit: int = 8) -> list[RetrievalResult]:
        if limit <= 0 or not self._items:
            return []

        query_vector = self._embedding_provider.embed_texts([query])[0]
        query_terms = tokenize_for_embedding(query)
        results: list[RetrievalResult] = []

        for chunk, vector in self._items:
            score = _dot_product(query_vector, vector)
            if score <= 0:
                continue
            results.append(
                RetrievalResult(
                    chunk=chunk,
                    score=score,
                    matched_terms=_matched_terms(query_terms=query_terms, chunk=chunk),
                    source="vector",
                )
            )

        results.sort(key=lambda result: (-result.score, result.chunk.path, result.chunk.start_line))
        return results[:limit]


def _chunk_embedding_text(chunk: CodeChunk) -> str:
    parts = [chunk.path, chunk.symbol or "", chunk.content]
    return "\n".join(part for part in parts if part)


def _matched_terms(query_terms: list[str], chunk: CodeChunk) -> list[str]:
    chunk_terms = set(tokenize_for_embedding(_chunk_embedding_text(chunk)))
    return [term for term in query_terms if term in chunk_terms]


def _dot_product(left: list[float], right: list[float]) -> float:
    return sum(left_value * right_value for left_value, right_value in zip(left, right))
