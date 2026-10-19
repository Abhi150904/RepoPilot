import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import RunDetailPage from "@/app/runs/[id]/page";
import ReviewPage from "@/app/runs/[id]/review/page";

const routeState = vi.hoisted(() => ({ values: [] as unknown[] }));

vi.mock("react", async (importOriginal) => {
  const original = await importOriginal<typeof import("react")>();
  return {
    ...original,
    useState: (initial: unknown) => [
      routeState.values.length ? routeState.values.shift() : typeof initial === "function" ? initial() : initial,
      vi.fn()
    ]
  };
});

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "route-run-123" }),
  usePathname: () => "/runs/route-run-123",
  useRouter: () => ({ push: vi.fn() })
}));

vi.mock("@/lib/run-view-model", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/run-view-model")>();
  return {
    ...original,
    buildRunView: () => {
      const view = original.buildRunView(null);
      return { ...view, canReview: true, tests: { ...view.tests, passed: true } };
    }
  };
});

describe("run route compatibility", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("gets the review link from the router without synchronous page params", () => {
    vi.stubGlobal("React", React);
    routeState.values = [{ lifecycle_status: "completed" }, null];
    const html = renderToStaticMarkup(React.createElement(RunDetailPage));
    expect(html).toContain('href="/runs/route-run-123/review"');
  });

  for (const Page of [RunDetailPage, ReviewPage]) {
    it(`does not render artifacts or review actions for an inaccessible ${Page.name}`, () => {
      vi.stubGlobal("React", React);
      routeState.values = [null, "Run not found."];
      const html = renderToStaticMarkup(React.createElement(Page));
      expect(html).toContain("Run unavailable");
      expect(html).toContain("Run not found.");
      expect(html).toContain('href="/runs"');
      expect(html).not.toContain("The fix is tested");
      expect(html).not.toContain("run_service.py");
      expect(html).not.toContain("Execution timeline");
      expect(html).not.toContain("Publication options");
      expect(html).not.toContain('href="/runs/route-run-123/review"');
    });
  }
});
