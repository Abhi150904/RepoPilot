from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from pydantic import BaseModel, Field

from app.retrieval.bm25 import BM25Index
from app.retrieval.embeddings import HashEmbeddingProvider, tokenize_for_embedding
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.keyword import retrieve_keyword_chunks
from app.retrieval.reranker import HeuristicReranker
from app.retrieval.vector import InMemoryVectorIndex
from app.schemas.repository import CodeChunk, RetrievalResult

DEFAULT_BENCHMARK_PATH = Path("backend/tests/fixtures/retrieval/benchmark.json")
DEFAULT_K_VALUES = [1, 3, 5]
DEFAULT_RETRIEVAL_LIMIT = 8


class RetrievalBenchmarkCase(BaseModel):
    id: str
    query: str
    relevant_paths: list[str]
    chunks: list[CodeChunk]
    query_terms: list[str] = Field(default_factory=list)


class RetrievalBenchmark(BaseModel):
    cases: list[RetrievalBenchmarkCase]
    k_values: list[int] = Field(default_factory=lambda: list(DEFAULT_K_VALUES))


class RetrievalMetrics(BaseModel):
    recall_at_k: dict[int, float]
    precision_at_k: dict[int, float]
    hit_at_k: dict[int, bool]
    mrr: float


class RetrievalCaseResult(BaseModel):
    case_id: str
    retriever: str
    ranked_paths: list[str]
    metrics: RetrievalMetrics
    duration_ms: float


class RetrieverSummary(BaseModel):
    retriever: str
    cases: int
    avg_recall_at_k: dict[int, float]
    avg_precision_at_k: dict[int, float]
    hit_rate_at_k: dict[int, float]
    avg_mrr: float
    avg_duration_ms: float


class RetrievalBenchmarkResult(BaseModel):
    total_cases: int
    summaries: list[RetrieverSummary]
    cases: list[RetrievalCaseResult]


RetrieverFn = Callable[[RetrievalBenchmarkCase, int], list[RetrievalResult]]


def load_retrieval_benchmark(path: Path) -> RetrievalBenchmark:
    data = json.loads(path.read_text(encoding="utf-8"))
    return RetrievalBenchmark.model_validate(data)


def run_retrieval_benchmark(
    benchmark: RetrievalBenchmark,
    *,
    retrievers: dict[str, RetrieverFn] | None = None,
    limit: int = DEFAULT_RETRIEVAL_LIMIT,
) -> RetrievalBenchmarkResult:
    selected_retrievers = retrievers or default_retrievers()
    case_results: list[RetrievalCaseResult] = []

    for case in benchmark.cases:
        for name, retriever in selected_retrievers.items():
            start = time.perf_counter()
            results = retriever(case, limit)
            duration_ms = (time.perf_counter() - start) * 1000
            ranked_paths = dedupe_ranked_paths(results)
            case_results.append(
                RetrievalCaseResult(
                    case_id=case.id,
                    retriever=name,
                    ranked_paths=ranked_paths,
                    metrics=score_ranked_paths(
                        ranked_paths=ranked_paths,
                        relevant_paths=case.relevant_paths,
                        k_values=benchmark.k_values,
                    ),
                    duration_ms=round(duration_ms, 4),
                )
            )

    return RetrievalBenchmarkResult(
        total_cases=len(benchmark.cases),
        summaries=_summarize(case_results, benchmark.k_values),
        cases=case_results,
    )


def default_retrievers() -> dict[str, RetrieverFn]:
    return {
        "keyword": _keyword_search,
        "bm25": _bm25_search,
        "vector": _vector_search,
        "hybrid": _hybrid_search,
        "hybrid_reranked": _hybrid_reranked_search,
    }


def score_ranked_paths(
    *,
    ranked_paths: list[str],
    relevant_paths: list[str],
    k_values: Iterable[int],
) -> RetrievalMetrics:
    relevant = set(relevant_paths)
    if not relevant:
        raise ValueError("Retrieval benchmark cases must include at least one relevant path.")

    recall_at_k: dict[int, float] = {}
    precision_at_k: dict[int, float] = {}
    hit_at_k: dict[int, bool] = {}

    for k in k_values:
        if k <= 0:
            raise ValueError("k values must be positive.")
        top_k = ranked_paths[:k]
        hits = len(relevant & set(top_k))
        recall_at_k[k] = _round_score(hits / len(relevant))
        precision_at_k[k] = _round_score(hits / k)
        hit_at_k[k] = hits > 0

    return RetrievalMetrics(
        recall_at_k=recall_at_k,
        precision_at_k=precision_at_k,
        hit_at_k=hit_at_k,
        mrr=_round_score(_mean_reciprocal_rank(ranked_paths, relevant)),
    )


def dedupe_ranked_paths(results: list[RetrievalResult]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for result in results:
        path = result.chunk.path
        if path not in seen:
            seen.add(path)
            paths.append(path)
    return paths


def _keyword_search(case: RetrievalBenchmarkCase, limit: int) -> list[RetrievalResult]:
    return retrieve_keyword_chunks(
        chunks=case.chunks,
        query_terms=_query_terms(case),
        limit=limit,
    )


def _bm25_search(case: RetrievalBenchmarkCase, limit: int) -> list[RetrievalResult]:
    index = BM25Index()
    index.add_chunks(case.chunks)
    return index.search(case.query, limit=limit)


def _vector_search(case: RetrievalBenchmarkCase, limit: int) -> list[RetrievalResult]:
    index = InMemoryVectorIndex(embedding_provider=HashEmbeddingProvider(dimensions=128))
    index.add_chunks(case.chunks)
    return index.search(case.query, limit=limit)


def _hybrid_search(case: RetrievalBenchmarkCase, limit: int) -> list[RetrievalResult]:
    retriever = HybridRetriever(embedding_provider=HashEmbeddingProvider(dimensions=128))
    return retriever.search(
        chunks=case.chunks,
        query_terms=_query_terms(case),
        limit=limit,
    )


def _hybrid_reranked_search(case: RetrievalBenchmarkCase, limit: int) -> list[RetrievalResult]:
    results = _hybrid_search(case, limit=limit)
    return HeuristicReranker().rerank(query=case.query, results=results, limit=limit)


def _query_terms(case: RetrievalBenchmarkCase) -> list[str]:
    return case.query_terms or tokenize_for_embedding(case.query)


def _summarize(
    case_results: list[RetrievalCaseResult],
    k_values: list[int],
) -> list[RetrieverSummary]:
    summaries: list[RetrieverSummary] = []
    retriever_names = sorted({result.retriever for result in case_results})

    for retriever in retriever_names:
        results = [result for result in case_results if result.retriever == retriever]
        summaries.append(
            RetrieverSummary(
                retriever=retriever,
                cases=len(results),
                avg_recall_at_k={
                    k: _avg(result.metrics.recall_at_k[k] for result in results)
                    for k in k_values
                },
                avg_precision_at_k={
                    k: _avg(result.metrics.precision_at_k[k] for result in results)
                    for k in k_values
                },
                hit_rate_at_k={
                    k: _avg(1.0 if result.metrics.hit_at_k[k] else 0.0 for result in results)
                    for k in k_values
                },
                avg_mrr=_avg(result.metrics.mrr for result in results),
                avg_duration_ms=_avg(result.duration_ms for result in results),
            )
        )

    summaries.sort(key=lambda summary: (-summary.avg_mrr, summary.retriever))
    return summaries


def _mean_reciprocal_rank(ranked_paths: list[str], relevant_paths: set[str]) -> float:
    for index, path in enumerate(ranked_paths, start=1):
        if path in relevant_paths:
            return 1 / index
    return 0.0


def _avg(values: Iterable[float]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return _round_score(sum(items) / len(items))


def _round_score(value: float) -> float:
    return round(value, 4)


def _print_report(result: RetrievalBenchmarkResult) -> None:
    print(f"Retrieval benchmark cases: {result.total_cases}")
    for summary in result.summaries:
        recall = ", ".join(
            f"R@{k}={score:.2f}"
            for k, score in sorted(summary.avg_recall_at_k.items())
        )
        precision = ", ".join(
            f"P@{k}={score:.2f}"
            for k, score in sorted(summary.avg_precision_at_k.items())
        )
        print(
            f"- {summary.retriever}: MRR={summary.avg_mrr:.2f}, "
            f"{recall}, {precision}, avg={summary.avg_duration_ms:.2f}ms"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare RepoPilot retrieval strategies.")
    parser.add_argument(
        "benchmark",
        nargs="?",
        default=str(DEFAULT_BENCHMARK_PATH),
        help="Retrieval benchmark JSON file.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the retrieval benchmark result as JSON.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_RETRIEVAL_LIMIT,
        help="Maximum chunk results to request from each retriever.",
    )
    args = parser.parse_args()

    benchmark = load_retrieval_benchmark(Path(args.benchmark))
    result = run_retrieval_benchmark(benchmark, limit=args.limit)

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        _print_report(result)


if __name__ == "__main__":
    main()
