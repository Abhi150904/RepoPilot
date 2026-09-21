from __future__ import annotations

from app.graph.workflow import build_workflow


def test_version_zero_workflow_produces_analysis_and_plan() -> None:
    workflow = build_workflow()

    result = workflow.invoke(
        {"issue": "Login endpoint returns 500 when email is missing."}
    )

    assert result["analysis"]["risk_level"] == "medium"
    assert "email" in result["analysis"]["summary"]
    assert result["plan"]["steps"]
    assert result["plan"]["tests_required"]

