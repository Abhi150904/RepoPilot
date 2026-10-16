from __future__ import annotations

from abc import ABC, abstractmethod
import re
from typing import TypeVar
from pydantic import BaseModel


from app.core.config import Settings, get_settings
from app.schemas.code_change import CodeChangeSet, FileChange, SourceFile
from app.schemas.execution import (
    RepairContext,
    ReviewFinding,
    ReviewResult,
    TestAnalysis,
)
from app.schemas.issue import IssueAnalysis
from app.schemas.plan import ImplementationPlan
from app.schemas.repository import RepositoryContext

T = TypeVar("T", bound=BaseModel)


class LLMProviderError(RuntimeError):
    """Raised when a model provider cannot produce valid structured output."""


class LLMProvider(ABC):
    """Small provider interface used by Version 0 agents."""

    @abstractmethod
    def analyze_issue(self, issue: str) -> IssueAnalysis:
        raise NotImplementedError

    @abstractmethod
    def create_plan(
        self,
        issue: str,
        analysis: IssueAnalysis,
        repository_context: RepositoryContext | None = None,
    ) -> ImplementationPlan:
        raise NotImplementedError

    @abstractmethod
    def propose_code_changes(
        self,
        issue: str,
        analysis: IssueAnalysis,
        plan: ImplementationPlan,
        target_files: list[SourceFile],
        repair_context: RepairContext | None = None,
    ) -> CodeChangeSet:
        raise NotImplementedError

    @abstractmethod
    def review_changes(
        self,
        issue: str,
        plan: ImplementationPlan,
        change_set: CodeChangeSet,
        diff: str,
        test_analysis: TestAnalysis,
        repair_attempts: int = 0,
    ) -> ReviewResult:
        raise NotImplementedError


class MockLLMProvider(LLMProvider):
    """Deterministic provider that keeps the first milestone runnable locally."""

    def analyze_issue(self, issue: str) -> IssueAnalysis:
        issue_lower = issue.lower()
        subject = _short_subject(issue)
        suspected_area = _guess_suspected_area(issue_lower)
        return IssueAnalysis(
            summary=f"The issue appears related to {subject}.",
            suspected_area=suspected_area,
            likely_cause=_guess_likely_cause(issue_lower, suspected_area),
            risk_level=_guess_risk_level(issue_lower),
        )

    def create_plan(
        self,
        issue: str,
        analysis: IssueAnalysis,
        repository_context: RepositoryContext | None = None,
    ) -> ImplementationPlan:
        files_to_inspect = [
            "login route",
            "request validation schema",
            "login endpoint tests",
        ]
        if repository_context:
            files_to_inspect = (
                [file.path for file in repository_context.matched_files]
                if repository_context.matched_files
                else ["No repository files matched; broaden repository search before editing."]
            )

        return ImplementationPlan(
            summary=f"Investigate and fix the reported behavior in {analysis.suspected_area}.",
            steps=_build_plan_steps(analysis=analysis, has_context=bool(repository_context)),
            files_to_inspect=files_to_inspect,
            tests_required=_build_required_tests(issue),
        )

    def propose_code_changes(
        self,
        issue: str,
        analysis: IssueAnalysis,
        plan: ImplementationPlan,
        target_files: list[SourceFile],
        repair_context: RepairContext | None = None,
    ) -> CodeChangeSet:
        changes = [
            change
            for file in target_files
            if (change := _propose_file_change(issue, plan, file, repair_context)) is not None
        ]
        return CodeChangeSet(
            summary=f"Prepared concrete source changes for {len(changes)} file(s).",
            changes=changes,
        )

    def review_changes(
        self,
        issue: str,
        plan: ImplementationPlan,
        change_set: CodeChangeSet,
        diff: str,
        test_analysis: TestAnalysis,
        repair_attempts: int = 0,
    ) -> ReviewResult:
        findings: list[ReviewFinding] = []
        if test_analysis.status != "passed":
            findings.append(
                ReviewFinding(
                    severity="error",
                    category="correctness",
                    message="Patch cannot be approved because tests did not pass.",
                )
            )
        if not change_set.changes:
            findings.append(
                ReviewFinding(
                    severity="error",
                    category="correctness",
                    message="No source changes were proposed for the issue.",
                )
            )
        if not diff.strip():
            findings.append(
                ReviewFinding(
                    severity="error",
                    category="maintainability",
                    message="No deterministic diff is available for review.",
                )
            )
        approved = not any(finding.severity == "error" for finding in findings)
        return ReviewResult(
            approved=approved,
            summary=(
                "Automated review approved the tested patch."
                if approved
                else "Automated review found issues that should be addressed before human approval."
            ),
            findings=findings,
            next_action="await_human_approval" if approved else "repair",
        )


def get_llm(role: str, settings: Settings | None = None) -> LLMProvider:
    config = settings or get_settings()
    provider = config.llm_provider.strip().lower()
    if provider == "mock":
        return MockLLMProvider()
    if provider == "openai":
        from app.core.openai_provider import OpenAILLMProvider

        if not config.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when REPO_PILOT_LLM_PROVIDER=openai.")
        return OpenAILLMProvider(
            api_key=config.openai_api_key,
            model=_model_for_role(config, role),
            role=role,
            max_retries=config.llm_max_retries,
            max_output_tokens=config.llm_max_output_tokens,
            max_prompt_chars=config.llm_max_prompt_chars,
            budget_path=config.llm_budget_path,
            budget_usd=config.llm_budget_usd,
            run_budget_usd=config.llm_run_budget_usd,
        )
    raise ValueError(f"Unsupported LLM provider '{config.llm_provider}'. Use openai or mock.")


def _short_subject(issue: str) -> str:
    first_line = issue.strip().splitlines()[0] if issue.strip() else "the reported behavior"
    cleaned = re.sub(r"\s+", " ", first_line).strip(" .")
    return cleaned[:100] or "the reported behavior"


def _guess_suspected_area(issue_lower: str) -> str:
    if any(word in issue_lower for word in ("login", "auth", "token", "jwt")):
        return "authentication flow"
    if any(word in issue_lower for word in ("cli", "command", "argument")):
        return "command-line interface"
    if any(word in issue_lower for word in ("graph", "langgraph", "workflow", "agent")):
        return "agent workflow"
    if any(word in issue_lower for word in ("test", "vitest", "pytest")):
        return "test coverage"
    if any(word in issue_lower for word in ("env", "config", "api key", "model")):
        return "configuration"
    return "application logic"


def _guess_likely_cause(issue_lower: str, suspected_area: str) -> str:
    if any(word in issue_lower for word in ("crash", "error", "exception", "500")):
        return f"Unhandled edge case or missing validation in the {suspected_area}."
    if any(word in issue_lower for word in ("missing", "not available", "not yet")):
        return f"Feature or integration work is incomplete in the {suspected_area}."
    if any(word in issue_lower for word in ("wrong", "incorrect", "invalid")):
        return f"Incorrect branching or data handling in the {suspected_area}."
    return f"The {suspected_area} likely needs inspection against the issue requirements."


def _guess_risk_level(issue_lower: str) -> str:
    if any(word in issue_lower for word in ("security", "data loss", "production", "crash")):
        return "high"
    if any(word in issue_lower for word in ("500", "error", "refactor", "workflow", "agent", "api")):
        return "medium"
    return "low"


def _build_plan_steps(analysis: IssueAnalysis, has_context: bool) -> list[str]:
    steps = [
        f"Review the relevant {analysis.suspected_area} files.",
        "Reproduce or reason through the reported behavior.",
        "Identify the smallest code change that addresses the issue.",
        "Add or update regression tests for the reported behavior.",
        "Run the focused test suite and inspect failures before widening changes.",
    ]
    if not has_context:
        steps.insert(0, "Use repository exploration to identify likely files before editing.")
    return steps


def _build_required_tests(issue: str) -> list[str]:
    subject = _short_subject(issue).lower()
    return [
        f"regression test for: {subject}",
        "existing behavior around the touched code path remains unchanged",
    ]


PROMPT_VERSION = "2026-10-04"


def _build_analysis_payload(issue: str) -> dict[str, object]:
    return _build_json_payload(
        role="analyzer",
        task="Analyze a software issue for RepoPilot.",
        rules=[
            "Return JSON only.",
            "Keep the analysis concise and implementation-oriented.",
            "Set risk_level to low, medium, or high only.",
            "Do not propose code changes in this step.",
        ],
        output_schema={
            "summary": "short explanation of the reported issue",
            "suspected_area": "likely codebase area involved",
            "likely_cause": "probable cause of the behavior",
            "risk_level": "low | medium | high",
        },
        context={
            "issue": issue,
        },
    )


def _build_plan_payload(
    issue: str,
    analysis: IssueAnalysis,
    repository_context: RepositoryContext | None,
) -> dict[str, object]:
    return _build_json_payload(
        role="planner",
        task="Create a focused implementation plan for RepoPilot.",
        rules=[
            "Return JSON only.",
            "Keep steps concrete and ordered.",
            "Prefer repository paths from repository_context when provided.",
            "Do not invent exact files when no repository context is available.",
            "Include regression tests that would prove the issue is fixed.",
        ],
        output_schema={
            "summary": "brief implementation strategy",
            "steps": ["ordered implementation step"],
            "files_to_inspect": ["repo path or specific code area"],
            "tests_required": ["regression test to add or update"],
        },
        context={
            "issue": issue,
            "analysis": analysis.model_dump(),
            "repository_context": (
                repository_context.model_dump() if repository_context else None
            ),
        },
    )


def _build_code_payload(
    issue: str,
    analysis: IssueAnalysis,
    plan: ImplementationPlan,
    target_files: list[SourceFile],
    repair_context: RepairContext | None,
) -> dict[str, object]:
    return _build_json_payload(
        role="coder",
        task="Return structured source-code changes for RepoPilot.",
        rules=[
            "Return JSON only.",
            "Do not return markdown fences.",
            "Do not return unified diffs.",
            "Every change.path must exactly match one of allowed_target_paths.",
            "Do not invent alternate routes, nearby filenames, or paths that are not listed in allowed_target_paths.",
            "If the desired file is missing from allowed_target_paths, return an empty changes list with a summary explaining that more repository context is needed.",
            "For modify actions, proposed_content must be the complete new file content.",
            "Do not omit unchanged parts of modified files.",
            "Use repair_context.test_summary, repair_context.failure_reason, and repair_context.previous_diff when present.",
        ],
        output_schema={
            "summary": "string",
            "changes": [
                {
                    "path": "string",
                    "action": "modify or create",
                    "explanation": "string",
                    "proposed_content": "complete source file content",
                }
            ],
        },
        context={
            "issue": issue,
            "analysis": analysis.model_dump(),
            "plan": plan.model_dump(),
            "allowed_target_paths": [file.path for file in target_files],
            "target_files": _source_files_for_prompt(target_files),
            "repair_context": _repair_context_for_prompt(repair_context),
        },
    )


def _build_review_payload(
    issue: str,
    plan: ImplementationPlan,
    change_set: CodeChangeSet,
    diff: str,
    test_analysis: TestAnalysis,
    repair_attempts: int,
) -> dict[str, object]:
    return _build_json_payload(
        role="reviewer",
        task="Review a tested RepoPilot patch before human approval.",
        rules=[
            "Return JSON only.",
            "Approve only when tests passed and the diff appears relevant to the issue.",
            "Call out correctness, edge case, security, maintainability, and test coverage concerns.",
            "Use severity error for blockers, warning for non-blocking risks, info for context.",
            "Set next_action to await_human_approval when approved, repair when fixable, or needs_human when uncertain.",
        ],
        output_schema={
            "approved": "boolean",
            "summary": "review verdict",
            "findings": [
                {
                    "severity": "info | warning | error",
                    "category": "correctness | edge_cases | error_handling | security | maintainability | test_coverage",
                    "message": "finding text",
                    "path": "optional repo path",
                }
            ],
            "next_action": "await_human_approval | repair | needs_human",
        },
        context={
            "issue": issue,
            "plan": plan.model_dump(),
            "change_set": _change_set_for_prompt(change_set),
            "diff": diff,
            "test_analysis": _test_analysis_for_prompt(test_analysis),
            "repair_attempts": repair_attempts,
        },
    )


def _build_json_payload(
    *,
    role: str,
    task: str,
    rules: list[str],
    output_schema: dict[str, object],
    context: dict[str, object],
) -> dict[str, object]:
    prompt = {
        "prompt_version": PROMPT_VERSION,
        "role": role,
        "task": task,
        "rules": rules,
        "output_schema": output_schema,
        "context": context,
    }
    return prompt


def _model_for_role(config: Settings, role: str) -> str:
    role_models = {
        "analyzer": config.analyzer_model,
        "planner": config.planner_model,
        "coder": config.coder_model,
        "reviewer": config.reviewer_model,
    }
    selected = role_models.get(role) or config.llm_model
    return selected.strip()


def _repair_context_for_prompt(repair_context: RepairContext | None) -> dict[str, object] | None:
    if repair_context is None:
        return None
    data = repair_context.model_dump()
    data["test_summary"] = _truncate_text(str(data.get("test_summary") or ""), 12_000)
    data["failure_reason"] = _truncate_text(str(data.get("failure_reason") or ""), 20_000)
    data["previous_diff"] = _truncate_text(str(data.get("previous_diff") or ""), 40_000)
    return data


def _source_files_for_prompt(target_files: list[SourceFile]) -> list[dict[str, object]]:
    return [file.model_dump() for file in target_files]


def _test_analysis_for_prompt(test_analysis: TestAnalysis) -> dict[str, object]:
    data = test_analysis.model_dump()
    data["summary"] = _truncate_text(str(data.get("summary") or ""), 12_000)
    data["failure_reason"] = _truncate_text(str(data.get("failure_reason") or ""), 20_000)
    return data


def _change_set_for_prompt(change_set: CodeChangeSet) -> dict[str, object]:
    return change_set.model_dump()


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[truncated {omitted} characters]"


def _propose_file_change(
    issue: str,
    plan: ImplementationPlan,
    file: SourceFile,
    repair_context: RepairContext | None,
) -> FileChange | None:
    issue_lower = issue.lower()
    content = file.content
    proposed = content

    if file.path.endswith(".py"):
        proposed = _repair_python_input_lookup(
            content=proposed,
            issue_lower=issue_lower,
            field="email",
            error_message="email is required",
        )
        proposed = _repair_python_input_lookup(
            content=proposed,
            issue_lower=issue_lower,
            field="destination",
            error_message="destination is required",
        )

    if repair_context and repair_context.failure_reason:
        proposed = _apply_repair_context_hint(
            content=proposed,
            failure_reason=repair_context.failure_reason,
        )

    if proposed == content:
        return None

    return FileChange(
        path=file.path,
        action="modify",
        explanation=f"Apply the implementation plan: {plan.summary}",
        proposed_content=proposed,
    )


def _repair_python_input_lookup(
    content: str,
    issue_lower: str,
    field: str,
    error_message: str,
) -> str:
    if field not in issue_lower:
        return content

    bracket_pattern = re.compile(
        rf"^(?P<indent>\s*)(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<payload>[A-Za-z_][A-Za-z0-9_]*)\[['\"]{field}['\"]\]\s*$",
        re.MULTILINE,
    )

    def replace_bracket_lookup(match: re.Match[str]) -> str:
        indent = match.group("indent")
        name = match.group("name")
        payload = match.group("payload")
        return (
            f"{indent}{name} = {payload}.get(\"{field}\")\n"
            f"{indent}if not {name}:\n"
            f"{indent}    return {{\"error\": \"{error_message}\"}}, 400"
        )

    return bracket_pattern.sub(replace_bracket_lookup, content)


def _apply_repair_context_hint(content: str, failure_reason: str) -> str:
    if "AssertionError" not in failure_reason and "FAILED" not in failure_reason:
        return content
    if "email is required" in content or "destination is required" in content:
        return content
    return content
