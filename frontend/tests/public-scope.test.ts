import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { existsSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/app-shell";
import LandingPage from "@/app/page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/app",
  useRouter: () => ({ push: vi.fn() })
}));

describe("public app scope", () => {
  beforeEach(() => vi.stubGlobal("React", React));
  afterEach(() => vi.unstubAllGlobals());

  it("keeps evaluations out of navigation and removes the page route", () => {
    const html = renderToStaticMarkup(React.createElement(AppShell, null, "content"));
    expect(html).not.toContain("Evaluations");
    expect(html).not.toContain('href="/evaluations"');
    for (const href of ["/app", "/runs", "/repositories", "/settings"]) {
      expect(html).toContain(`href="${href}"`);
    }
    expect(existsSync("app/evaluations/page.tsx")).toBe(false);
  });

  it("does not advertise an evaluation UI on the landing page", () => {
    const html = renderToStaticMarkup(React.createElement(LandingPage));
    expect(html).not.toContain('id="evaluations"');
    expect(html).not.toContain("Evaluation signals");
    expect(html).toContain("Verification");
  });
});
