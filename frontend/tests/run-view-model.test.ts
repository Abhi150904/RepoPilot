import { describe, expect, it } from "vitest";
import { buildRunView } from "@/lib/run-view-model";
import type { RunStatusResponse } from "@/lib/api";

describe("buildRunView", () => {
  it("maps completed backend results into product-facing workspace data", () => {
    const run: RunStatusResponse = {
      run_id: "run-1",
      lifecycle_status: "completed",
      request: { repository: "example/demo", issue_number: 7, max_repair_attempts: 2 },
      error: null,
      response: {
        status: "ready_for_review",
        next_action: "approve_changes",
        summary: "Ready for approval.",
        run_summary: {
          status: "ready_for_review",
          summary: "Ready for approval.",
          next_action: "approve_changes",
          tests_passed: true,
          repair_attempts: 0,
          metrics: { tokens: 6420 }
        },
        result: {
          repository: "example/demo",
          issue_number: 7,
          issue: "Fix login validation",
          analysis: { risk_level: "medium" },
          plan: { steps: ["Add validation", "Add regression test"] },
          modified_files: ["backend/routes/login.py", "backend/tests/test_login.py"],
          diff: "+new line\n-old line\n unchanged",
          test_analysis: { status: "passed", summary: "26 tests passed." },
          review_result: { status: "approved" },
          approval_decision: { approved: true },
          approval_binding: {
            status: "bound",
            head_commit: "abc123",
            git_safety: { status: "safe" }
          },
          publication_package: {
            branch_name: "repopilot/issue-7",
            pr_title: "fix: login validation"
          },
          publish_result: {
            status: "published",
            summary: "Pull request opened.",
            branch_name: "repopilot/issue-7",
            pr_url: "https://github.com/example/demo/pull/1"
          }
        }
      }
    };

    const view = buildRunView(run);

    expect(view.repository).toBe("example/demo");
    expect(view.issue).toBe("#7 Fix login validation");
    expect(view.planSteps).toEqual(["Add validation", "Add regression test"]);
    expect(view.diffStats).toBe("+1 -1");
    expect(view.tests.label).toBe("passed");
    expect(view.review.confidence).toBe("96");
    expect(view.tokens).toBe("6.4k");
    expect(view.verification.every((item) => item.verified)).toBe(true);
    expect(view.publish.prUrl).toBe("https://github.com/example/demo/pull/1");
  });
});
