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
          run_metrics: { total_tokens: 8732 },
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
    expect(view.review.status).toBe("Passed");
    expect(view.tokens).toBe("6.4k");
    expect(view.verification.every((item) => item.verified)).toBe(true);
    expect(view.publish.prUrl).toBe("https://github.com/example/demo/pull/1");
  });

  it("does not show ready copy or fake artifacts for provider failures", () => {
    const run: RunStatusResponse = {
      run_id: "run-2",
      lifecycle_status: "completed",
      request: { repository: "example/demo", issue_number: 8 },
      error: null,
      response: {
        status: "needs_human",
        next_action: "inspect_failure",
        summary: "LLM provider failed before the workflow could continue.",
        run_summary: {
          status: "needs_human",
          summary: "LLM provider failed before the workflow could continue.",
          next_action: "inspect_failure",
          tests_passed: false,
          repair_attempts: 0,
          metrics: null
        },
        result: {
          repository: "example/demo",
          issue_number: 8,
          issue: "Fix submit validation",
          llm_error: {
            stage: "reviewer",
            message: "Gemini request failed with 503 Service Unavailable."
          },
          run_summary: {
            status: "needs_human",
            summary: "LLM provider failed before the workflow could continue.",
            next_action: "inspect_failure"
          }
        }
      }
    };

    const view = buildRunView(run);

    expect(view.headline).toBe("RepoPilot needs your attention.");
    expect(view.canReview).toBe(false);
    expect(view.diffFile).toBe("No changed files");
    expect(view.diffStats).toBe("+0 -0");
    expect(view.diffLines[0].text).toBe("No diff was generated for this run.");
    expect(view.review.status).toBe("Not run");
    expect(view.publish.status).toBe("Locked");
  });

  it("does not show success copy for failed runs without artifacts", () => {
    const run: RunStatusResponse = {
      run_id: "run-3",
      lifecycle_status: "failed",
      request: { repository: "example/demo", issue_number: 9 },
      response: null,
      error: {
        code: "provider_error",
        message: "Model provider operation failed. Check provider configuration.",
        type: "LLMProviderError"
      }
    };

    const view = buildRunView(run);

    expect(view.headline).toBe("Run failed before completion.");
    expect(view.summary).toBe("Model provider operation failed. Check provider configuration.");
    expect(view.planSteps).toEqual(["No implementation plan was produced for this run."]);
    expect(view.diffFile).toBe("No changed files");
    expect(view.tests.summary).toBe("Test output will appear after a run executes.");
    expect(view.review.risk).toBe("n/a");
    expect(view.tokens).toBe("n/a");
    expect(view.canReview).toBe(false);
  });

  it("does not expose a pull request link for dry run publication results", () => {
    const run: RunStatusResponse = {
      run_id: "run-4",
      lifecycle_status: "completed",
      request: { repository: "example/demo", issue_number: 10 },
      error: null,
      response: {
        status: "approved",
        next_action: "human_review",
        summary: "Approved.",
        run_summary: {
          status: "approved",
          summary: "Approved.",
          next_action: "human_review",
          tests_passed: true,
          repair_attempts: 0
        },
        result: {
          repository: "example/demo",
          issue_number: 10,
          issue: "Fix destination validation",
          modified_files: ["src/app.ts"],
          review_result: { status: "approved" },
          approval_decision: { approved: true },
          approval_binding: { status: "bound", head_commit: "abc123", git_safety: { status: "safe" } },
          publication_package: {
            branch_name: "repopilot/issue-10",
            pr_title: "Fix #10: destination validation"
          },
          publish_result: {
            mode: "dry_run",
            status: "ready",
            summary: "Publication dry run passed.",
            branch_name: "repopilot/issue-10",
            pr_url: "https://github.com/example/demo/pull/new/repopilot/issue-10"
          }
        }
      }
    };

    const view = buildRunView(run);

    expect(view.publish.mode).toBe("dry_run");
    expect(view.publish.status).toBe("ready");
    expect(view.publish.prUrl).toBeUndefined();
  });

  it("uses durable run events for the execution timeline", () => {
    const run: RunStatusResponse = {
      run_id: "run-5",
      lifecycle_status: "completed",
      publication_status: "ready",
      request: { repository: "example/demo", issue_number: 11 },
      events: [
        {
          run_id: "run-5",
          event_type: "run.created",
          created_at: "2026-10-08T00:00:00Z",
          metadata: { request_id: "abcdef123456" }
        },
        {
          run_id: "run-5",
          event_type: "run.queued",
          created_at: "2026-10-08T00:00:01Z",
          metadata: {}
        },
        {
          run_id: "run-5",
          event_type: "run.claimed",
          created_at: "2026-10-08T00:00:02Z",
          metadata: {}
        },
        {
          run_id: "run-5",
          event_type: "run.started",
          created_at: "2026-10-08T00:00:03Z",
          metadata: {}
        },
        {
          run_id: "run-5",
          event_type: "run.completed",
          created_at: "2026-10-08T00:00:04Z",
          metadata: {}
        },
        {
          run_id: "run-5",
          event_type: "run.publication_started",
          created_at: "2026-10-08T00:00:05Z",
          metadata: { mode: "dry_run" }
        },
        {
          run_id: "run-5",
          event_type: "run.publication_ready",
          created_at: "2026-10-08T00:00:06Z",
          metadata: { mode: "dry_run", status: "ready" }
        }
      ],
      error: null,
      response: {
        status: "approved",
        next_action: "human_review",
        summary: "Approved.",
        run_summary: {
          status: "approved",
          summary: "Approved.",
          next_action: "human_review",
          tests_passed: true,
          repair_attempts: 0
        },
        result: {
          repository: "example/demo",
          issue_number: 11,
          issue: "Fix timeline",
          modified_files: ["src/app.ts"],
          review_result: { status: "approved" },
          approval_decision: { approved: true },
          approval_binding: { status: "bound", head_commit: "abc123", git_safety: { status: "safe" } },
          publish_result: {
            mode: "dry_run",
            status: "ready",
            summary: "Publication dry run passed."
          }
        }
      }
    };

    const view = buildRunView(run);

    expect(view.timeline.map((item) => item.label)).toEqual([
      "Run created",
      "Queued",
      "Worker claimed run",
      "Execution started",
      "Run completed",
      "Publication started",
      "Publication ready"
    ]);
    expect(view.timeline[0].detail).toBe("Request abcdef12");
    expect(view.timeline[5].detail).toBe("Mode: Dry run");
    expect(view.timeline.every((item) => item.state === "complete")).toBe(true);
  });

  it("reads backend run metric token totals for run intelligence", () => {
    const run: RunStatusResponse = {
      run_id: "run-metrics",
      lifecycle_status: "completed",
      request: { repository: "example/demo", issue_number: 12 },
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
          issue_number: 12,
          review_result: { status: "approved" },
          run_metrics: {
            total_tokens: 12_345
          }
        }
      }
    };

    const view = buildRunView(run);

    expect(view.review.status).toBe("Passed");
    expect(view.tokens).toBe("12.3k");
  });
});
