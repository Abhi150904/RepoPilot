from __future__ import annotations

from app.schemas.execution import ApprovalDecision, ReviewResult


class ApprovalGate:
    """Stops reviewed changes until explicit human approval is present."""

    def decide(self, review: ReviewResult, approved: bool = False) -> ApprovalDecision:
        if not review.approved:
            return ApprovalDecision(
                approved=False,
                status="not_ready",
                summary="Automated review did not approve the patch, so human approval is not available yet.",
                next_action="inspect_failure",
            )

        if approved:
            return ApprovalDecision(
                approved=True,
                status="approved",
                summary="Human approval was provided for this reviewed patch.",
                next_action="commit_changes",
            )

        return ApprovalDecision(
            approved=False,
            status="awaiting_approval",
            summary="Automated review approved the patch; waiting for explicit human approval.",
            next_action="human_review",
        )
