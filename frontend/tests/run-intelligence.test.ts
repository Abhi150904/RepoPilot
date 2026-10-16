import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunIntelligence } from "@/components/run-panels";
import { buildRunView } from "@/lib/run-view-model";
import type { RunStatusResponse } from "@/lib/api";

function completedRun(result: Record<string, unknown>): RunStatusResponse {
  return {
    run_id: "run-1", lifecycle_status: "completed", request: {},
    response: { status: "ready", next_action: "review", summary: "Done", run_summary: {}, result }
  };
}

describe("run intelligence", () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each([[true, "Passed"], [false, "Blocked"]] as const)("maps recorded review approval %s", (approved, expected) => {
    const view = buildRunView(completedRun({ review_result: { approved } }));
    expect(view.review.status).toBe(expected);
    expect(view.review.blockers).toBe(approved ? 0 : 1);
  });

  it("keeps unrecorded review and usage distinct from zero", () => {
    const view = buildRunView(completedRun({}));
    expect(view.review.status).toBe("Not run");
    expect(view.usage).toEqual({ requests: "n/a", models: "n/a", estimatedCost: "n/a" });
  });

  it("shows recorded usage and workflow duration, not publication wait time", () => {
    const run = completedRun({ run_metrics: {
      total_runtime_ms: 53000, total_tokens: 12300, llm_call_count: 4, estimated_cost_usd: 0.02,
      llm_calls: [{ model: "test-model" }, { model: "test-model" }]
    } });
    run.created_at = "2026-10-17T01:00:00Z";
    run.updated_at = "2026-10-17T05:00:00Z";
    const view = buildRunView(run);
    expect(view.duration).toBe("53s");
    expect(view.usage).toEqual({ requests: "4", models: "test-model", estimatedCost: "$0.0200" });
    expect(buildRunView(completedRun({ run_metrics: { llm_call_count: 0, estimated_cost_usd: 0 } })).usage.estimatedCost).toBe("$0.00");
  });

  it("does not expose usage details in the run intelligence panel", () => {
    vi.stubGlobal("React", React);
    const view = buildRunView(completedRun({ run_metrics: {
      total_tokens: 12300, llm_call_count: 4, estimated_cost_usd: 0.02,
      llm_calls: [{ model: "private-model" }]
    } }));
    const html = renderToStaticMarkup(React.createElement(RunIntelligence, { view }));
    expect(html).toContain("Automated review");
    expect(html).toContain("Run duration");
    expect(html).not.toContain("Tokens");
    expect(html).not.toContain("Review confidence");
    expect(html).not.toContain("Usage details");
    expect(html).not.toContain("API requests");
    expect(html).not.toContain("Estimated cost");
    expect(html).not.toContain("private-model");
  });
});
