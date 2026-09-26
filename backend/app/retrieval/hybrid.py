from __future__ import annotations

from app.retrieval.bm25 import BM25Index
from app.retrieval.embeddings import EmbeddingProvider, HashEmbeddingProvider
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.keyword import retrieve_keyword_chunks
from app.retrieval.vector import InMemoryVectorIndex
from app.schemas.repository import CodeChunk, RetrievalResult


class HybridRetriever:
    """Combines keyword, BM25, and vector retrieval with rank fusion."""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        rrf_k: int = 60,
    ) -> None:
        if rrf_k <= 0:
            raise ValueError("RRF k must be positive.")
        self._embedding_provider = embedding_provider or HashEmbeddingProvider()
        self._rrf_k = rrf_k

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

        return reciprocal_rank_fusion(
            ranked_lists=[keyword_results, bm25_results, vector_results],
            k=self._rrf_k,
            limit=limit,
            source="hybrid_rrf",
        )
