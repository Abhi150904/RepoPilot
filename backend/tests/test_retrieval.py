from __future__ import annotations

from app.retrieval.chunker import chunk_code_file
from app.retrieval.keyword import retrieve_keyword_chunks
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
