import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewPanel } from "@/components/run-panels";
import { buildRunView } from "@/lib/run-view-model";
import type { RunStatusResponse } from "@/lib/api";

describe("published review panel", () => {
  afterEach(() => vi.unstubAllGlobals());

  it.each(["published", "publishing"] as const)("locks actions while %s", (publication_status) => {
    vi.stubGlobal("React", React);
    const run: RunStatusResponse = {
      run_id: "run-1", lifecycle_status: "completed", publication_status, request: {},
      response: {
        status: "approved", next_action: "publish", summary: "Approved", run_summary: { tests_passed: true },
        result: {
          approval_decision: { approved: true },
          test_analysis: { status: "passed", summary: "40 tests passed" },
          review_result: { status: "approved" },
          publish_result: { status: publication_status, pr_url: "https://github.com/example/demo/pull/1" }
        }
      }
    };
    const html = renderToStaticMarkup(React.createElement(ReviewPanel, {
      run, view: buildRunView(run), isBusy: false, activeAction: null,
      onApprove: vi.fn(), onReject: vi.fn(), onPublish: vi.fn()
    }));
    expect(html).not.toContain("Approve changes");
    expect(html).not.toContain(">Reject</button>");
    expect(html).not.toContain("Ready for decision");
    expect(html).not.toContain(">Dry Run</button>");
    expect(html).toContain("The review decision is locked");
    if (publication_status === "published") {
      expect(html).toContain("https://github.com/example/demo/pull/1");
    }
  });
});
