from __future__ import annotations

import pytest

from app.retrieval.bm25 import BM25Index
from app.retrieval.chunker import chunk_code_file
from app.retrieval.embeddings import HashEmbeddingProvider, tokenize_for_embedding
from app.retrieval.hybrid import HybridRetriever, HybridRetrievalWeights
from app.retrieval.keyword import retrieve_keyword_chunks
from app.retrieval.vector import InMemoryVectorIndex
from app.schemas.repository import CodeChunk


def test_chunk_code_file_splits_on_common_symbols() -> None:
    content = "\n".join(
        [
            "import { z } from \"zod\";",
            "",
            "export const startRunRequestSchema = z.object({",
            "  message: z.string().trim().min(1)",
            "});",
            "",
            "export const resumeRunRequestSchema = z.object({",
            "  approved: z.boolean()",
            "});",
        ]
    )

    chunks = chunk_code_file(path="src/api/schemas.ts", content=content)

    assert [chunk.symbol for chunk in chunks] == [
        None,
        "startRunRequestSchema",
        "resumeRunRequestSchema",
    ]
    assert chunks[1].start_line == 3
    assert chunks[1].end_line == 6


def test_keyword_retrieval_scores_path_symbol_and_content_matches() -> None:
    chunks = [
        CodeChunk(
            path="src/api/app.ts",
            start_line=1,
            end_line=10,
            content="export const createApp = () => app;",
            symbol="createApp",
        ),
        CodeChunk(
            path="src/api/schemas.ts",
            start_line=1,
            end_line=10,
            content="message: z.string().trim().min(1, 'message is required')",
            symbol="startRunRequestSchema",
        ),
        CodeChunk(
            path="web/app/page.tsx",
            start_line=20,
            end_line=40,
            content="const [message, setMessage] = useState('');",
            symbol=None,
        ),
    ]

    results = retrieve_keyword_chunks(
        chunks=chunks,
        query_terms=["schema", "message", "validation"],
        limit=3,
    )

    assert results[0].chunk.path == "src/api/schemas.ts"
    assert "schema" in results[0].matched_terms
    assert "message" in results[0].matched_terms
    assert all(result.score > 0 for result in results)


def test_hash_embedding_provider_is_deterministic_and_normalizes_tokens() -> None:
    provider = HashEmbeddingProvider(dimensions=32)

    first = provider.embed_texts(["extractDestination validates destinations"])[0]
    second = provider.embed_texts(["extractDestination validates destinations"])[0]

    assert first == second
    assert tokenize_for_embedding("extractDestination validates destinations") == [
        "extract",
        "destination",
        "validate",
    ]


def test_vector_retrieval_ranks_related_chunks_above_unrelated_chunks() -> None:
    chunks = [
        CodeChunk(
            path="src/agents/planner.agent.ts",
            start_line=8,
            end_line=27,
            content="const extractDestination = (userQuery: string) => destination;",
            symbol="extractDestination",
        ),
        CodeChunk(
            path="src/api/schemas.ts",
            start_line=1,
            end_line=6,
            content="message: z.string().trim().min(1, 'message is required')",
            symbol="startRunRequestSchema",
        ),
        CodeChunk(
            path="web/app/globals.css",
            start_line=1,
            end_line=10,
            content=":root { --bg: #090a0c; --panel: #101216; }",
            symbol=None,
        ),
    ]
    index = InMemoryVectorIndex(embedding_provider=HashEmbeddingProvider(dimensions=64))
    index.add_chunks(chunks)

    results = index.search("destination validation", limit=3)

    assert results[0].chunk.path == "src/agents/planner.agent.ts"
    assert results[0].source == "vector"
    assert "destination" in results[0].matched_terms
    assert all(result.chunk.path != "web/app/globals.css" for result in results)


def test_bm25_retrieval_ranks_rare_relevant_terms_above_common_noise() -> None:
    chunks = [
        CodeChunk(
            path="src/agents/planner.agent.ts",
            start_line=8,
            end_line=27,
            content=(
                "const extractDestination = (userQuery: string) => {\n"
                "  const destination = userQuery.trim();\n"
                "  return destination || 'your destination';\n"
                "};"
            ),
            symbol="extractDestination",
        ),
        CodeChunk(
            path="src/api/schemas.ts",
            start_line=1,
            end_line=6,
            content="message: z.string().trim().min(1, 'message is required')",
            symbol="startRunRequestSchema",
        ),
        CodeChunk(
            path="web/app/globals.css",
            start_line=1,
            end_line=10,
            content="app app app app theme panel background color layout",
            symbol=None,
        ),
    ]
    index = BM25Index()
    index.add_chunks(chunks)

    results = index.search("destination validation", limit=3)

    assert results[0].chunk.path == "src/agents/planner.agent.ts"
    assert results[0].source == "bm25"
    assert "destination" in results[0].matched_terms
    assert all(result.chunk.path != "web/app/globals.css" for result in results)


def test_bm25_empty_index_and_invalid_parameters() -> None:
    assert BM25Index().search("destination validation") == []

    with pytest.raises(ValueError, match="k1"):
        BM25Index(k1=0)

    with pytest.raises(ValueError, match="b"):
        BM25Index(b=1.5)


def test_hybrid_retrieval_merges_duplicate_chunks_from_multiple_retrievers() -> None:
    chunks = [
        CodeChunk(
            path="src/agents/planner.agent.ts",
            start_line=8,
            end_line=27,
            content="const extractDestination = (userQuery: string) => destination;",
            symbol="extractDestination",
        ),
        CodeChunk(
            path="src/api/schemas.ts",
            start_line=1,
            end_line=6,
            content="message: z.string().trim().min(1, 'message is required')",
            symbol="startRunRequestSchema",
        ),
        CodeChunk(
            path="web/app/globals.css",
            start_line=1,
            end_line=10,
            content="theme panel background color layout",
            symbol=None,
        ),
    ]
    retriever = HybridRetriever(
        embedding_provider=HashEmbeddingProvider(dimensions=64),
        weights=HybridRetrievalWeights(keyword=0.4, bm25=0.4, vector=0.2),
    )

    results = retriever.search(
        chunks=chunks,
        query_terms=["destination", "validation"],
        limit=3,
    )

    assert results[0].chunk.path == "src/agents/planner.agent.ts"
    assert results[0].source == "hybrid"
    assert "destination" in results[0].matched_terms
    assert len([result for result in results if result.chunk.path == "src/agents/planner.agent.ts"]) == 1
    assert all(result.chunk.path != "web/app/globals.css" for result in results)


def test_hybrid_retrieval_handles_empty_inputs_and_invalid_weights() -> None:
    retriever = HybridRetriever()

    assert retriever.search(chunks=[], query_terms=["destination"]) == []
    assert retriever.search(
        chunks=[
            CodeChunk(
                path="src/example.ts",
                start_line=1,
                end_line=1,
                content="destination",
            )
        ],
        query_terms=[],
    ) == []

    with pytest.raises(ValueError, match="negative"):
        HybridRetriever(weights=HybridRetrievalWeights(keyword=-1))

    with pytest.raises(ValueError, match="positive"):
        HybridRetriever(weights=HybridRetrievalWeights(keyword=0, bm25=0, vector=0))
