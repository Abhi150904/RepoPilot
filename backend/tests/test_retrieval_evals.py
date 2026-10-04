from __future__ import annotations

from pathlib import Path

import pytest

from app.evals.retrieval import (
    DEFAULT_BENCHMARK_PATH,
    RetrievalBenchmark,
    RetrievalBenchmarkCase,
    dedupe_ranked_paths,
    load_retrieval_benchmark,
    run_retrieval_benchmark,
    score_ranked_paths,
)
from app.schemas.repository import CodeChunk, RetrievalResult


def test_score_ranked_paths_calculates_recall_precision_hits_and_mrr() -> None:
    metrics = score_ranked_paths(
        ranked_paths=["src/noise.py", "src/login.py", "tests/test_login.py"],
        relevant_paths=["src/login.py", "tests/test_login.py"],
        k_values=[1, 2, 3],
    )

    assert metrics.recall_at_k == {1: 0.0, 2: 0.5, 3: 1.0}
    assert metrics.precision_at_k == {1: 0.0, 2: 0.5, 3: 0.6667}
    assert metrics.hit_at_k == {1: False, 2: True, 3: True}
    assert metrics.mrr == 0.5


def test_score_ranked_paths_requires_relevant_paths_and_positive_k() -> None:
    with pytest.raises(ValueError, match="at least one relevant path"):
        score_ranked_paths(ranked_paths=[], relevant_paths=[], k_values=[1])

    with pytest.raises(ValueError, match="positive"):
        score_ranked_paths(ranked_paths=[], relevant_paths=["a.py"], k_values=[0])


def test_dedupe_ranked_paths_keeps_first_chunk_for_each_file() -> None:
    first = RetrievalResult(
        chunk=CodeChunk(path="src/login.py", start_line=1, end_line=8, content="email"),
        score=1.0,
        matched_terms=["email"],
    )
    duplicate = RetrievalResult(
        chunk=CodeChunk(path="src/login.py", start_line=9, end_line=20, content="password"),
        score=0.8,
        matched_terms=["password"],
    )
    second = RetrievalResult(
        chunk=CodeChunk(path="tests/test_login.py", start_line=1, end_line=8, content="missing email"),
        score=0.7,
        matched_terms=["email"],
    )

    assert dedupe_ranked_paths([first, duplicate, second]) == [
        "src/login.py",
        "tests/test_login.py",
    ]


def test_load_retrieval_benchmark_fixture() -> None:
    benchmark = load_retrieval_benchmark(DEFAULT_BENCHMARK_PATH)

    assert len(benchmark.cases) == 3
    assert benchmark.k_values == [1, 3, 5]
    assert benchmark.cases[0].id == "destination-empty-crash"
    assert benchmark.cases[0].chunks[0].path == "src/agents/planner.agent.ts"


def test_run_retrieval_benchmark_compares_retrievers_on_fixture() -> None:
    benchmark = load_retrieval_benchmark(DEFAULT_BENCHMARK_PATH)

    result = run_retrieval_benchmark(benchmark)

    assert result.total_cases == 3
    assert {summary.retriever for summary in result.summaries} == {
        "keyword",
        "bm25",
        "vector",
        "hybrid",
        "hybrid_reranked",
    }
    assert len(result.cases) == 15
    assert all(0 <= summary.avg_mrr <= 1 for summary in result.summaries)
    assert all(summary.avg_recall_at_k[5] > 0 for summary in result.summaries)


def test_run_retrieval_benchmark_accepts_custom_retriever() -> None:
    case = RetrievalBenchmarkCase(
        id="simple",
        query="login email validation",
        relevant_paths=["src/login.py"],
        chunks=[
            CodeChunk(
                path="src/login.py",
                start_line=1,
                end_line=3,
                content="validate email before login",
            )
        ],
    )

    result = run_retrieval_benchmark(
        benchmark=RetrievalBenchmark(cases=[case], k_values=[1]),
        retrievers={
            "custom": lambda benchmark_case, limit: [
                RetrievalResult(
                    chunk=benchmark_case.chunks[0],
                    score=1.0,
                    matched_terms=["email"],
                    source="custom",
                )
            ]
        },
    )

    assert result.summaries[0].retriever == "custom"
    assert result.summaries[0].avg_mrr == 1.0
    assert result.cases[0].ranked_paths == ["src/login.py"]
