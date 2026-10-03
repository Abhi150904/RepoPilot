from __future__ import annotations

from app.agents.approval import ApprovalGate
from app.schemas.execution import ReviewResult


def test_approval_gate_waits_without_explicit_approval() -> None:
    decision = ApprovalGate().decide(
        review=ReviewResult(
            approved=True,
            summary="Automated review approved the tested patch.",
            next_action="await_human_approval",
        ),
        approved=False,
    )

    assert decision.approved is False
    assert decision.status == "awaiting_approval"
    assert decision.next_action == "human_review"


def test_approval_gate_accepts_explicit_approval() -> None:
    decision = ApprovalGate().decide(
        review=ReviewResult(
            approved=True,
            summary="Automated review approved the tested patch.",
            next_action="await_human_approval",
        ),
        approved=True,
    )

    assert decision.approved is True
    assert decision.status == "approved"
    assert decision.next_action == "commit_changes"


def test_approval_gate_blocks_unreviewed_patch() -> None:
    decision = ApprovalGate().decide(
        review=ReviewResult(
            approved=False,
            summary="Automated review found issues.",
            next_action="repair",
        ),
        approved=True,
    )

    assert decision.approved is False
    assert decision.status == "not_ready"
    assert decision.next_action == "inspect_failure"
