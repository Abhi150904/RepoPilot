from __future__ import annotations

from app.schemas.repository import RetrievalResult


def reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievalResult]],
    k: int = 60,
    limit: int = 8,
    source: str = "rrf",
) -> list[RetrievalResult]:
    """Fuse ranked retrieval lists using reciprocal rank fusion."""

    if k <= 0:
        raise ValueError("RRF k must be positive.")
    if limit <= 0:
        return []

    fused: dict[tuple[str, int, int], RetrievalResult] = {}

    for ranked_results in ranked_lists:
        for rank, result in enumerate(ranked_results, start=1):
            key = (result.chunk.path, result.chunk.start_line, result.chunk.end_line)
            contribution = 1 / (k + rank)

            if key not in fused:
                fused[key] = RetrievalResult(
                    chunk=result.chunk,
                    score=contribution,
                    matched_terms=result.matched_terms,
                    source=source,
                )
                continue

            existing = fused[key]
            existing.score += contribution
            existing.matched_terms = _dedupe([*existing.matched_terms, *result.matched_terms])

    results = list(fused.values())
    results.sort(key=lambda result: (-result.score, result.chunk.path, result.chunk.start_line))
    return results[:limit]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_items: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique_items.append(item)
    return unique_items
