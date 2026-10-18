import { describe, expect, it } from "vitest";
import { summaryFromRun } from "@/lib/run-history";
import type { RunStatusResponse } from "@/lib/api";

describe("summaryFromRun", () => {
  function reviewedRun(approval: Record<string, unknown>): RunStatusResponse {
    return {
      run_id: "approval-state",
      lifecycle_status: "completed",
      publication_status: "not_started",
      request: { repository: "example/demo", issue_number: 3 },
      response: {
        status: "awaiting_approval", next_action: "human_review", summary: "Waiting for approval.",
        run_summary: { tests_passed: true },
        result: { review_result: { approved: true }, approval_decision: approval }
      }
    };
  }

  it("does not mistake approved=false while awaiting approval for rejection", () => {
    const summary = summaryFromRun(reviewedRun({ approved: false, status: "awaiting_approval" }));
    expect(summary.stage).toBe("Ready for approval");
    expect(summary.statusLabel).toBe("awaiting approval");
    expect(summary.needsAttention).toBe(true);
  });

  it("distinguishes automated approval blockers from explicit human rejection", () => {
    const summary = summaryFromRun(reviewedRun({
      approved: false, status: "not_ready", summary: "Automated review did not approve the patch."
    }));
    expect(summary.stage).toBe("Approval blocked");
    expect(summary.statusLabel).toBe("approval blocked");
    expect(summary.needsAttention).toBe(false);
  });

  it("still labels an explicit human rejection as rejected", () => {
    const summary = summaryFromRun(reviewedRun({
      approved: false, status: "not_ready", summary: "Human reviewer rejected this run."
    }));
    expect(summary.stage).toBe("Rejected");
    expect(summary.statusLabel).toBe("rejected");
    expect(summary.needsAttention).toBe(false);
  });

  it("preserves approved and published stages", () => {
    const run = reviewedRun({ approved: true, status: "approved" });
    expect(summaryFromRun(run).stage).toBe("Approved");
    run.publication_status = "published";
    run.response!.result.publish_result = { status: "published" };
    expect(summaryFromRun(run).stage).toBe("Published");
    expect(summaryFromRun(run).statusLabel).toBe("published");
  });

  it("does not keep completed failed-test runs in the attention queue", () => {
    const run: RunStatusResponse = {
      run_id: "run-failed-tests",
      lifecycle_status: "completed",
      request: { repository: "example/demo", issue_number: 1 },
      error: null,
      response: {
        status: "needs_human",
        next_action: "inspect_failure",
        summary: "The test command timed out and needs human inspection.",
        run_summary: {
          status: "needs_human",
          summary: "The test command timed out and needs human inspection.",
          next_action: "inspect_failure",
          tests_passed: false,
          repair_attempts: 0
        },
        result: {
          repository: "example/demo",
          issue_number: 1,
          review_result: { status: "approved" },
          run_summary: {
            status: "needs_human",
            summary: "The test command timed out and needs human inspection."
          }
        }
      }
    };

    const summary = summaryFromRun(run);

    expect(summary.status).toBe("completed");
    expect(summary.stage).toBe("Approval blocked");
    expect(summary.tests).toBe("failed");
    expect(summary.needsAttention).toBe(false);
    expect(summary.attentionLabel).toBe("");
  });

  it("keeps completed passing reviewed runs ready for approval", () => {
    const run: RunStatusResponse = {
      run_id: "run-ready",
      lifecycle_status: "completed",
      request: { repository: "example/demo", issue_number: 2 },
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
          repair_attempts: 0
        },
        result: {
          repository: "example/demo",
          issue_number: 2,
          review_result: { status: "approved" }
        }
      }
    };

    const summary = summaryFromRun(run);

    expect(summary.needsAttention).toBe(true);
    expect(summary.attentionLabel).toBe("Ready for approval");
    expect(summary.attentionAction).toBe("review");
  });

  it("labels provider-limit runs by the actual blocker instead of review", () => {
    const run: RunStatusResponse = {
      run_id: "run-rate-limited",
      lifecycle_status: "completed",
      request: { repository: "example/demo", issue_number: 3 },
      error: null,
      response: {
        status: "needs_human",
        next_action: "inspect_failure",
        summary: "LLM provider failed before the workflow could continue.",
        run_summary: {
          status: "needs_human",
          summary: "LLM provider failed before the workflow could continue.",
          next_action: "inspect_failure",
          tests_passed: null,
          repair_attempts: 0
        },
        result: {
          repository: "example/demo",
          issue_number: 3,
          review_result: { status: "approved" },
          llm_error: {
            type: "rate_limit_exceeded",
            message: "Groq request failed with 429 Too Many Requests."
          }
        }
      }
    };

    const summary = summaryFromRun(run);

    expect(summary.stage).toBe("Provider limit");
    expect(summary.statusLabel).toBe("rate limited");
    expect(summary.needsAttention).toBe(false);
  });

  it("labels runs with no verifier as verification unavailable", () => {
    const run: RunStatusResponse = {
      run_id: "run-no-verifier",
      lifecycle_status: "completed",
      request: { repository: "example/demo", issue_number: 4 },
      error: null,
      response: {
        status: "needs_human",
        next_action: "inspect_failure",
        summary: "Automated verification is unavailable for this repository.",
        run_summary: {
          status: "needs_human",
          summary: "Automated verification is unavailable for this repository.",
          next_action: "inspect_failure",
          tests_passed: null,
          repair_attempts: 0
        },
        result: {
          repository: "example/demo",
          issue_number: 4,
          test_analysis: {
            status: "unavailable",
            summary: "No automated test, lint, or build command was found for this repository.",
            next_action: "inspect_failure"
          }
        }
      }
    };

    const summary = summaryFromRun(run);

    expect(summary.stage).toBe("Verification unavailable");
    expect(summary.tests).toBe("unavailable");
    expect(summary.needsAttention).toBe(false);
  });

  it("uses workflow runtime for duration after later publication updates", () => {
    const run: RunStatusResponse = {
      run_id: "run-published-later",
      lifecycle_status: "completed",
      publication_status: "published",
      created_at: "2026-10-13T08:00:00.000Z",
      updated_at: "2026-10-13T14:13:00.000Z",
      request: { repository: "example/demo", issue_number: 5 },
      error: null,
      response: {
        status: "published",
        next_action: "done",
        summary: "Published.",
        run_summary: {
          status: "published",
          summary: "Published.",
          next_action: "done",
          tests_passed: true,
          repair_attempts: 0
        },
        result: {
          repository: "example/demo",
          issue_number: 5,
          run_metrics: {
            total_runtime_ms: 53_000
          },
          publish_result: {
            status: "published"
          }
        }
      }
    };

    const summary = summaryFromRun(run);

    expect(summary.duration).toBe("53s");
    expect(summary.stage).toBe("Published");
  });
});
