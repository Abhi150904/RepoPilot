from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.analyzer import IssueAnalyzer
from app.agents.coder import CodeWriter
from app.agents.planner import Planner
from app.agents.repo_explorer import RepoExplorer
from app.agents.test_analyzer import TestAnalyzer
from app.core.llm import get_llm
from app.graph.state import AgentState
from app.schemas.code_change import CodeChangeSet
from app.schemas.execution import TestResult
from app.schemas.issue import IssueAnalysis
from app.schemas.plan import ImplementationPlan
from app.schemas.repository import RepositoryContext
from app.tools.filesystem import WorkspaceFileSystem
from app.tools.github import GitHubClient
from app.tools.patch import apply_change_set
from app.tools.sandbox import run_tests_in_docker


def start_route(state: AgentState) -> str:
    if "repository" in state and "issue_number" in state:
        return "fetch_github_issue"
    return "issue_analyzer"


def after_analyzer_route(state: AgentState) -> str:
    if "repository" in state:
        return "repo_explorer"
    return "planner"


def after_code_writer_route(state: AgentState) -> str:
    if state.get("apply_changes"):
        return "apply_code_changes"
    if state.get("run_tests"):
        return "run_tests"
    return "end"


def after_apply_changes_route(state: AgentState) -> str:
    if state.get("run_tests"):
        return "run_tests"
    return "end"


def fetch_github_issue_node(state: AgentState) -> AgentState:
    repository = state["repository"]
    issue_number = state["issue_number"]
    issue = GitHubClient().get_issue(repository, issue_number)
    issue_text = f"{issue.title}\n\n{issue.body}".strip()
    return {
        "issue": issue_text,
        "issue_title": issue.title,
        "issue_body": issue.body,
        "issue_url": issue.url,
    }


def issue_analyzer_node(state: AgentState) -> AgentState:
    issue = state["issue"]
    analyzer = IssueAnalyzer(llm=get_llm("analyzer"))
    analysis = analyzer.analyze(issue)
    return {"analysis": analysis.model_dump()}


def planner_node(state: AgentState) -> AgentState:
    issue = state["issue"]
    analysis = IssueAnalysis.model_validate(state["analysis"])
    repository_context = None
    if "repository_context" in state:
        repository_context = RepositoryContext.model_validate(state["repository_context"])
    planner = Planner(llm=get_llm("planner"))
    plan = planner.create_plan(
        issue=issue,
        analysis=analysis,
        repository_context=repository_context,
    )
    return {"plan": plan.model_dump()}


def repo_explorer_node(state: AgentState) -> AgentState:
    repository = state["repository"]
    issue = state["issue"]
    analysis = IssueAnalysis.model_validate(state["analysis"])
    explorer = RepoExplorer(github=GitHubClient())
    context = explorer.explore(
        repository=repository,
        issue=issue,
        analysis=analysis,
    )
    return {"repository_context": context.model_dump()}


def code_writer_node(state: AgentState) -> AgentState:
    issue = state["issue"]
    plan = ImplementationPlan.model_validate(state["plan"])
    repository_context = None
    if "repository_context" in state:
        repository_context = RepositoryContext.model_validate(state["repository_context"])
    change_set = CodeWriter().propose_changes(
        issue=issue,
        plan=plan,
        repository_context=repository_context,
    )
    return {
        "code_changes": change_set.model_dump(),
        "diff": change_set.diff,
    }


def apply_code_changes_node(state: AgentState) -> AgentState:
    workspace_path = state.get("workspace_path")
    if not workspace_path:
        raise ValueError("workspace_path is required when apply_changes is true.")

    change_set = CodeChangeSet.model_validate(state["code_changes"])
    result = apply_change_set(
        change_set=change_set,
        filesystem=WorkspaceFileSystem(root=workspace_path),
    )
    return {
        "modified_files": result.modified_files,
        "diff": result.diff,
    }


def run_tests_node(state: AgentState) -> AgentState:
    workspace_path = state.get("workspace_path")
    if not workspace_path:
        raise ValueError("workspace_path is required when run_tests is true.")

    command = state.get("test_command", ["python", "-m", "pytest", "-p", "no:cacheprovider"])
    result: TestResult = run_tests_in_docker(
        workspace_path=workspace_path,
        command=command,
    )
    return {"test_result": result.model_dump()}


def analyze_tests_node(state: AgentState) -> AgentState:
    result = TestResult.model_validate(state["test_result"])
    analysis = TestAnalyzer().analyze(result)
    return {"test_analysis": analysis.model_dump()}


def build_workflow():
    graph = StateGraph(AgentState)
    graph.add_node("fetch_github_issue", fetch_github_issue_node)
    graph.add_node("issue_analyzer", issue_analyzer_node)
    graph.add_node("repo_explorer", repo_explorer_node)
    graph.add_node("planner", planner_node)
    graph.add_node("code_writer", code_writer_node)
    graph.add_node("apply_code_changes", apply_code_changes_node)
    graph.add_node("run_tests", run_tests_node)
    graph.add_node("analyze_tests", analyze_tests_node)

    graph.add_conditional_edges(
        START,
        start_route,
        {
            "fetch_github_issue": "fetch_github_issue",
            "issue_analyzer": "issue_analyzer",
        },
    )
    graph.add_edge("fetch_github_issue", "issue_analyzer")
    graph.add_conditional_edges(
        "issue_analyzer",
        after_analyzer_route,
        {
            "repo_explorer": "repo_explorer",
            "planner": "planner",
        },
    )
    graph.add_edge("repo_explorer", "planner")
    graph.add_edge("planner", "code_writer")
    graph.add_conditional_edges(
        "code_writer",
        after_code_writer_route,
        {
            "apply_code_changes": "apply_code_changes",
            "run_tests": "run_tests",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "apply_code_changes",
        after_apply_changes_route,
        {
            "run_tests": "run_tests",
            "end": END,
        },
    )
    graph.add_edge("run_tests", "analyze_tests")
    graph.add_edge("analyze_tests", END)

    return graph.compile()
