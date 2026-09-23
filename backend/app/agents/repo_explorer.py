from __future__ import annotations

import re

from app.schemas.issue import IssueAnalysis
from app.schemas.repository import RepositoryContext, RepositoryFile, RetrievedFile
from app.tools.github import GitHubClient, GitHubError


class RepoExplorer:
    """Finds likely relevant repository files using simple deterministic search."""

    def __init__(self, github: GitHubClient) -> None:
        self._github = github

    def explore(
        self,
        repository: str,
        issue: str,
        analysis: IssueAnalysis,
        max_files: int = 5,
    ) -> RepositoryContext:
        query_terms = _build_query_terms(issue=issue, analysis=analysis)
        query = " ".join(query_terms[:5])
        files = self._github.list_repository_files(repository)

        candidate_paths = _rank_file_paths(files=files, terms=query_terms)
        candidate_paths.extend(self._search_code_paths(repository, query))

        selected_paths = _dedupe(candidate_paths)[:max_files]
        matched_files = [
            self._read_preview(repository=repository, path=path, terms=query_terms)
            for path in selected_paths
        ]

        return RepositoryContext(
            repository=repository,
            query=query,
            matched_files=[file for file in matched_files if file is not None],
        )

    def _search_code_paths(self, repository: str, query: str) -> list[str]:
        if not query:
            return []
        try:
            return self._github.search_code(repository, query)
        except GitHubError:
            return []

    def _read_preview(
        self,
        repository: str,
        path: str,
        terms: list[str],
    ) -> RetrievedFile | None:
        try:
            content = self._github.read_file(repository, path)
        except GitHubError:
            return None

        return RetrievedFile(
            path=path,
            reason=_reason_for_path(path=path, terms=terms),
            content_preview=content[:1200],
        )


def _build_query_terms(issue: str, analysis: IssueAnalysis) -> list[str]:
    text = f"{issue} {analysis.summary} {analysis.suspected_area} {analysis.likely_cause}"
    words = re.findall(r"[A-Za-z][A-Za-z0-9_]+", text.lower())
    stop_words = {
        "the",
        "and",
        "that",
        "with",
        "when",
        "from",
        "this",
        "likely",
        "missing",
        "returns",
        "return",
        "allows",
        "code",
        "value",
    }
    terms = [word for word in words if len(word) > 2 and word not in stop_words]
    return _dedupe(terms)


def _rank_file_paths(files: list[RepositoryFile], terms: list[str]) -> list[str]:
    scored_paths: list[tuple[int, str]] = []
    for file in files:
        path_lower = file.path.lower()
        score = sum(3 for term in terms if term in path_lower)

        if path_lower.startswith(("test", "tests")):
            score += 1
        if any(part in path_lower for part in ("route", "controller", "service")):
            score += 1
        if score > 0:
            scored_paths.append((score, file.path))

    scored_paths.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in scored_paths]


def _reason_for_path(path: str, terms: list[str]) -> str:
    matching_terms = [term for term in terms if term in path.lower()]
    if matching_terms:
        return f"Path matched issue terms: {', '.join(matching_terms[:4])}."
    return "Selected by repository code search."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_items: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            unique_items.append(item)
    return unique_items
