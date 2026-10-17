import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import RunDetailPage from "@/app/runs/[id]/page";

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
    const html = renderToStaticMarkup(React.createElement(RunDetailPage));
    expect(html).toContain('href="/runs/route-run-123/review"');
  });
});
