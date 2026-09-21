from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agents.analyzer import IssueAnalyzer
from app.agents.planner import Planner
from app.core.llm import get_llm
from app.graph.state import AgentState
from app.schemas.issue import IssueAnalysis


def issue_analyzer_node(state: AgentState) -> AgentState:
    issue = state["issue"]
    analyzer = IssueAnalyzer(llm=get_llm("analyzer"))
    analysis = analyzer.analyze(issue)
    return {"analysis": analysis.model_dump()}


def planner_node(state: AgentState) -> AgentState:
    issue = state["issue"]
    analysis = IssueAnalysis.model_validate(state["analysis"])
    planner = Planner(llm=get_llm("planner"))
    plan = planner.create_plan(issue=issue, analysis=analysis)
    return {"plan": plan.model_dump()}


def build_workflow():
    graph = StateGraph(AgentState)
    graph.add_node("issue_analyzer", issue_analyzer_node)
    graph.add_node("planner", planner_node)

    graph.add_edge(START, "issue_analyzer")
    graph.add_edge("issue_analyzer", "planner")
    graph.add_edge("planner", END)

    return graph.compile()

