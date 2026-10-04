from __future__ import annotations

from app.core.llm import LLMProvider
from app.schemas.code_change import CodeChangeSet
from app.schemas.execution import ReviewFinding, ReviewResult, TestAnalysis
from app.schemas.plan import ImplementationPlan


class Reviewer:
    """Reviews a tested patch before human approval or publication."""

    def __init__(self, llm: LLMProvider | None = None) -> None:
        self._llm = llm

    def review(
        self,
        issue: str,
        plan: ImplementationPlan,
        change_set: CodeChangeSet,
        diff: str,
        test_analysis: TestAnalysis,
        repair_attempts: int = 0,
    ) -> ReviewResult:
        if self._llm is not None:
            return self._llm.review_changes(
                issue=issue,
                plan=plan,
                change_set=change_set,
                diff=diff,
                test_analysis=test_analysis,
                repair_attempts=repair_attempts,
            )

        findings = _collect_findings(
            issue=issue,
            plan=plan,
            change_set=change_set,
            diff=diff,
            test_analysis=test_analysis,
        )
        approved = not any(finding.severity == "error" for finding in findings)
        return ReviewResult(
            approved=approved,
            summary=_summary(approved=approved, repair_attempts=repair_attempts),
            findings=findings,
            next_action="await_human_approval" if approved else "repair",
        )


def _collect_findings(
    issue: str,
    plan: ImplementationPlan,
    change_set: CodeChangeSet,
    diff: str,
    test_analysis: TestAnalysis,
) -> list[ReviewFinding]:
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

    if not plan.tests_required:
        findings.append(
            ReviewFinding(
                severity="warning",
                category="test_coverage",
                message="The implementation plan does not list required tests.",
            )
        )

    issue_terms = _important_issue_terms(issue)
    changed_text = "\n".join(
        change.proposed_content or ""
        for change in change_set.changes
    ).lower()
    if issue_terms and not any(term in changed_text for term in issue_terms):
        findings.append(
            ReviewFinding(
                severity="warning",
                category="correctness",
                message="Changed source does not obviously reference the main issue terms.",
            )
        )

    for change in change_set.changes:
        if change.proposed_content is not None and not change.proposed_content.strip():
            findings.append(
                ReviewFinding(
                    severity="error",
                    category="maintainability",
                    message="A generated file change has empty proposed content.",
                    path=change.path,
                )
            )

    return findings


def _important_issue_terms(issue: str) -> list[str]:
    terms = []
    for term in ("email", "destination", "token", "password", "login"):
        if term in issue.lower():
            terms.append(term)
    return terms


def _summary(approved: bool, repair_attempts: int) -> str:
    if approved:
        if repair_attempts:
            return f"Automated review approved the tested patch after {repair_attempts} repair attempt(s)."
        return "Automated review approved the tested patch."
    return "Automated review found issues that should be addressed before human approval."
