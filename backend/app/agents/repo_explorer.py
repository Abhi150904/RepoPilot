from __future__ import annotations

import re
from pathlib import PurePosixPath

from app.schemas.issue import IssueAnalysis
from app.schemas.repository import RepositoryContext, RepositoryFile, RetrievedFile
from app.tools.github import GitHubClient, GitHubError


WEAK_TERMS = {
    "app",
    "application",
    "empty",
    "crash",
    "crashes",
    "issue",
    "behavior",
    "logic",
    "reported",
    "related",
    "appears",
    "case",
    "edge",
    "unhandled",
}

TERM_PATH_HINTS = {
    "destination": {"agent", "planner", "page"},
    "field": {"form", "input", "page", "schema", "schemas"},
    "form": {"page", "schema", "schemas"},
    "input": {"guardrail", "guardrails", "page", "schema", "schemas"},
    "validation": {"guardrail", "guardrails", "schema", "schemas"},
}

IMPORTANT_CODE_PARTS = {
    "agent",
    "agents",
    "api",
    "component",
    "components",
    "controller",
    "form",
    "forms",
    "graph",
    "input",
    "inputs",
    "page",
    "pages",
    "route",
    "routes",
    "schema",
    "schemas",
    "service",
    "services",
    "validation",
    "validator",
}

IGNORED_PATH_PARTS = {
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".next",
    ".git",
}


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
        candidate_paths.extend(self._search_code_paths(repository, query_terms))

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

    def _search_code_paths(self, repository: str, query_terms: list[str]) -> list[str]:
        if not query_terms:
            return []

        paths: list[str] = []
        search_queries = [" ".join(query_terms[:3]), *query_terms[:5]]
        for query in _dedupe([item for item in search_queries if item]):
            try:
                paths.extend(self._github.search_code(repository, query))
            except GitHubError:
                continue
        return _dedupe(paths)

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
    terms = [
        word
        for word in words
        if len(word) > 2 and word not in stop_words and word not in WEAK_TERMS
    ]
    return _dedupe(terms)


def _rank_file_paths(files: list[RepositoryFile], terms: list[str]) -> list[str]:
    scored_paths: list[tuple[int, str]] = []
    for file in files:
        if _should_ignore_path(file.path):
            continue

        path_lower = file.path.lower()
        path_parts = set(_path_tokens(file.path))
        filename = PurePosixPath(file.path).name.lower()
        score = 0

        for term in terms:
            if term in path_parts:
                score += 8
            elif term in filename:
                score += 5
            elif term in path_lower:
                score += 2
            elif path_parts.intersection(TERM_PATH_HINTS.get(term, set())):
                score += 4

        if score > 0:
            if path_lower.startswith(("test", "tests")):
                score += 1
            if any(part in path_parts for part in IMPORTANT_CODE_PARTS):
                score += 3
            scored_paths.append((score, file.path))

    scored_paths.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in scored_paths]


def _reason_for_path(path: str, terms: list[str]) -> str:
    path_parts = set(_path_tokens(path))
    matching_terms = [term for term in terms if term in path_parts or term in path.lower()]
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


def _path_tokens(path: str) -> list[str]:
    return re.findall(r"[a-z][a-z0-9]+", path.lower())


def _should_ignore_path(path: str) -> bool:
    path_lower = path.lower()
    return any(part in path_lower.split("/") for part in IGNORED_PATH_PARTS)
