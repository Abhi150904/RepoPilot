from __future__ import annotations

from app.agents.repo_explorer import _build_query_terms, _rank_file_paths
from app.schemas.issue import IssueAnalysis
from app.schemas.repository import RepositoryFile


def test_query_terms_drop_generic_words() -> None:
    analysis = IssueAnalysis(
        summary="The issue appears related to App crashes when destination field is empty.",
        suspected_area="application logic",
        likely_cause="Unhandled edge case or missing validation in the application logic.",
        risk_level="high",
    )

    terms = _build_query_terms(
        issue="App crashes when destination field is empty",
        analysis=analysis,
    )

    assert "destination" in terms
    assert "field" in terms
    assert "validation" in terms
    assert "app" not in terms
    assert "empty" not in terms


def test_rank_file_paths_prioritizes_specific_matches_over_generic_app_files() -> None:
    files = [
        RepositoryFile(path="src/api/app.ts"),
        RepositoryFile(path="web/app/layout.tsx"),
        RepositoryFile(path="src/agents/planner.agent.ts"),
        RepositoryFile(path="web/components/destination-input.tsx"),
        RepositoryFile(path="web/components/theme-toggle.tsx"),
        RepositoryFile(path="src/validation/destination.schema.ts"),
    ]
    terms = ["destination", "validation", "input"]

    ranked_paths = _rank_file_paths(files=files, terms=terms)

    assert ranked_paths[:2] == [
        "src/validation/destination.schema.ts",
        "web/components/destination-input.tsx",
    ]
    assert "src/api/app.ts" not in ranked_paths
    assert "web/app/layout.tsx" not in ranked_paths


def test_rank_file_paths_uses_semantic_hints_for_sparse_issue_terms() -> None:
    files = [
        RepositoryFile(path="src/agents/planner.agent.ts"),
        RepositoryFile(path="src/api/schemas.ts"),
        RepositoryFile(path="src/api/app.ts"),
        RepositoryFile(path="web/app/page.tsx"),
        RepositoryFile(path="web/app/layout.tsx"),
    ]
    terms = ["destination", "field", "validation"]

    ranked_paths = _rank_file_paths(files=files, terms=terms)

    assert ranked_paths[:3] == [
        "src/api/schemas.ts",
        "web/app/page.tsx",
        "src/agents/planner.agent.ts",
    ]
    assert "src/api/app.ts" not in ranked_paths
