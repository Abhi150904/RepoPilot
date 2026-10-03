from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.approval import ApprovalGate
from app.agents.analyzer import IssueAnalyzer
from app.agents.coder import CodeWriter
from app.agents.planner import Planner
from app.agents.publication import PublicationPreparer
from app.agents.publisher import PublishExecutor
from app.agents.repair_decider import RepairDecider
from app.agents.repo_explorer import RepoExplorer
from app.agents.reviewer import Reviewer
from app.agents.run_summarizer import RunSummarizer
from app.agents.test_analyzer import TestAnalyzer
from app.core.llm import get_llm
from app.graph.state import AgentState
from app.schemas.code_change import CodeChangeSet, SourceFile
from app.schemas.execution import (
    ApprovalDecision,
    PublicationPackage,
    RepairContext,
    RepairDecision,
    ReviewResult,
    TestAnalysis,
    TestResult,
)
from app.schemas.issue import IssueAnalysis
from app.schemas.plan import ImplementationPlan
from app.schemas.repository import RepositoryContext
from app.tools.filesystem import WorkspaceFileSystem
from app.tools.git import inspect_git_safety
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


def after_repair_decision_route(state: AgentState) -> str:
    decision = RepairDecision.model_validate(state["repair_decision"])
    analysis = TestAnalysis.model_validate(state["test_analysis"])
    repair_attempts = state.get("repair_attempts", 0)
    max_repair_attempts = state.get("max_repair_attempts", 1)

    if (
        decision.next_action == "repair"
        and state.get("apply_changes")
        and repair_attempts < max_repair_attempts
    ):
        return "prepare_repair"
    if analysis.status == "passed":
        return "review_changes"
    return "end"


def after_approval_gate_route(state: AgentState) -> str:
    decision = ApprovalDecision.model_validate(state["approval_decision"])
    if decision.approved:
        return "prepare_publication"
    return "end"


def after_prepare_publication_route(state: AgentState) -> str:
    if state.get("publish_dry_run"):
        return "publish_dry_run"
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


def load_target_files_node(state: AgentState) -> AgentState:
    plan = ImplementationPlan.model_validate(state["plan"])
    repository_context = None
    if "repository_context" in state:
        repository_context = RepositoryContext.model_validate(state["repository_context"])

    target_paths = _select_target_paths(plan=plan, repository_context=repository_context)
    source_files: list[SourceFile] = []
    workspace_path = state.get("workspace_path")
    if workspace_path:
        filesystem = WorkspaceFileSystem(root=workspace_path)
        for path in target_paths:
            if filesystem.file_exists(path):
                source_files.append(
                    SourceFile(path=path, content=filesystem.read_text(path), exists=True)
                )
    elif "repository" in state:
        github = GitHubClient()
        for path in target_paths:
            try:
                content = github.read_file(state["repository"], path)
            except Exception:
                continue
            source_files.append(SourceFile(path=path, content=content, exists=True))

    return {"target_files": [file.model_dump() for file in source_files]}


def code_writer_node(state: AgentState) -> AgentState:
    issue = state["issue"]
    analysis = IssueAnalysis.model_validate(state["analysis"])
    plan = ImplementationPlan.model_validate(state["plan"])
    repository_context = None
    if "repository_context" in state:
        repository_context = RepositoryContext.model_validate(state["repository_context"])
    target_files = [
        SourceFile.model_validate(file)
        for file in state.get("target_files", [])
    ]
    repair_context = None
    if "repair_context" in state:
        repair_context = RepairContext.model_validate(state["repair_context"])
    change_set = CodeWriter(llm=get_llm("coder")).propose_changes(
        issue=issue,
        analysis=analysis,
        plan=plan,
        target_files=target_files,
        repository_context=repository_context,
        repair_context=repair_context,
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


def decide_repair_node(state: AgentState) -> AgentState:
    analysis = TestAnalysis.model_validate(state["test_analysis"])
    decision = RepairDecider().decide(analysis)
    return {"repair_decision": decision.model_dump()}


def prepare_repair_node(state: AgentState) -> AgentState:
    attempt = state.get("repair_attempts", 0) + 1
    analysis = TestAnalysis.model_validate(state["test_analysis"])
    context = RepairContext(
        attempt=attempt,
        test_status=analysis.status,
        test_summary=analysis.summary,
        failure_reason=analysis.failure_reason,
        previous_diff=state.get("diff", ""),
    )
    return {
        "repair_attempts": attempt,
        "repair_context": context.model_dump(),
    }


def review_changes_node(state: AgentState) -> AgentState:
    plan = ImplementationPlan.model_validate(state["plan"])
    change_set = CodeChangeSet.model_validate(state["code_changes"])
    test_analysis = TestAnalysis.model_validate(state["test_analysis"])
    result = Reviewer().review(
        issue=state["issue"],
        plan=plan,
        change_set=change_set,
        diff=state.get("diff", ""),
        test_analysis=test_analysis,
        repair_attempts=state.get("repair_attempts", 0),
    )
    return {"review_result": result.model_dump()}


def approval_gate_node(state: AgentState) -> AgentState:
    review = ReviewResult.model_validate(state["review_result"])
    decision = ApprovalGate().decide(
        review=review,
        approved=state.get("approved", False),
    )
    return {"approval_decision": decision.model_dump()}


def prepare_publication_node(state: AgentState) -> AgentState:
    approval = ApprovalDecision.model_validate(state["approval_decision"])
    changed_files = state.get("modified_files", [])
    git_safety = None
    if "workspace_path" in state:
        git_safety = inspect_git_safety(
            workspace_path=state["workspace_path"],
            expected_changed_files=changed_files,
        )
    package = PublicationPreparer().prepare(
        issue=state["issue"],
        approval=approval,
        changed_files=changed_files,
        issue_number=state.get("issue_number"),
        repository=state.get("repository"),
        git_safety=git_safety,
    )
    return {"publication_package": package.model_dump()}


def publish_dry_run_node(state: AgentState) -> AgentState:
    package = PublicationPackage.model_validate(state["publication_package"])
    result = PublishExecutor().dry_run(package)
    return {"publish_result": result.model_dump()}


def summarize_run_node(state: AgentState) -> AgentState:
    summary = RunSummarizer().summarize(dict(state))
    return {"run_summary": summary.model_dump()}


def _select_target_paths(
    plan: ImplementationPlan,
    repository_context: RepositoryContext | None,
    limit: int = 3,
) -> list[str]:
    paths: list[str] = []
    if repository_context:
        paths.extend(file.path for file in repository_context.matched_files)
    paths.extend(path for path in plan.files_to_inspect if "/" in path or "." in path)

    seen: set[str] = set()
    selected: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            selected.append(path)
        if len(selected) >= limit:
            break
    return selected


def build_workflow():
    graph = StateGraph(AgentState)
    graph.add_node("fetch_github_issue", fetch_github_issue_node)
    graph.add_node("issue_analyzer", issue_analyzer_node)
    graph.add_node("repo_explorer", repo_explorer_node)
    graph.add_node("planner", planner_node)
    graph.add_node("load_target_files", load_target_files_node)
    graph.add_node("code_writer", code_writer_node)
    graph.add_node("apply_code_changes", apply_code_changes_node)
    graph.add_node("run_tests", run_tests_node)
    graph.add_node("analyze_tests", analyze_tests_node)
    graph.add_node("decide_repair", decide_repair_node)
    graph.add_node("prepare_repair", prepare_repair_node)
    graph.add_node("review_changes", review_changes_node)
    graph.add_node("approval_gate", approval_gate_node)
    graph.add_node("prepare_publication", prepare_publication_node)
    graph.add_node("publish_dry_run", publish_dry_run_node)
    graph.add_node("summarize_run", summarize_run_node)

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
    graph.add_edge("planner", "load_target_files")
    graph.add_edge("load_target_files", "code_writer")
    graph.add_conditional_edges(
        "code_writer",
        after_code_writer_route,
        {
            "apply_code_changes": "apply_code_changes",
            "run_tests": "run_tests",
            "end": "summarize_run",
        },
    )
    graph.add_conditional_edges(
        "apply_code_changes",
        after_apply_changes_route,
        {
            "run_tests": "run_tests",
            "end": "summarize_run",
        },
    )
    graph.add_edge("run_tests", "analyze_tests")
    graph.add_edge("analyze_tests", "decide_repair")
    graph.add_conditional_edges(
        "decide_repair",
        after_repair_decision_route,
        {
            "prepare_repair": "prepare_repair",
            "review_changes": "review_changes",
            "end": "summarize_run",
        },
    )
    graph.add_edge("prepare_repair", "load_target_files")
    graph.add_edge("review_changes", "approval_gate")
    graph.add_conditional_edges(
        "approval_gate",
        after_approval_gate_route,
        {
            "prepare_publication": "prepare_publication",
            "end": "summarize_run",
        },
    )
    graph.add_conditional_edges(
        "prepare_publication",
        after_prepare_publication_route,
        {
            "publish_dry_run": "publish_dry_run",
            "end": "summarize_run",
        },
    )
    graph.add_edge("publish_dry_run", "summarize_run")
    graph.add_edge("summarize_run", END)

    return graph.compile()
