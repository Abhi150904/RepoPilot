import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunLauncherContent } from "@/components/run-launcher";
import type { RunUsage } from "@/lib/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const usage: RunUsage = { enforced: true, introductory: { total: 2, used: 0, reserved: 0, remaining: 2 },
  billing_enabled: true, run_credits: 4 };
const spent = { total: 2, used: 2, reserved: 0, remaining: 0 };

function render(overrides = {}) {
  vi.stubGlobal("React", React);
  return renderToStaticMarkup(React.createElement(RunLauncherContent, { usage, repository: "owner/repo",
    issueNumber: "1", busy: false, loading: false, error: null,
    onRepository: () => {}, onIssueNumber: () => {}, onStart: () => {},
    onRefresh: () => {}, ...overrides }));
}

function startDisabled(html: string) {
  return /<button[^>]*disabled=""[^>]*>.*?Start AI run<\/button>/.test(html);
}

describe("Command Center run access", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("shows lifetime free allowance and purchased run credits", () => {
    const html = render();
    expect(html).toContain("2 of 2");
    expect(html).toContain("free AI runs remaining");
    expect(html).toContain("Two lifetime free runs per GitHub account");
    expect(html).toContain("purchased run credits");
    expect(html).toContain("Start AI run");
    expect(html).toContain("Repository");
    expect(html).not.toContain('type="radio"');
    expect(startDisabled(html)).toBe(false);
  });
  it("allows purchased credits after the free allowance, regardless of checkout availability", () => {
    for (const billing_enabled of [true, false]) {
      const html = render({ usage: { ...usage, introductory: spent, run_credits: 1, billing_enabled } });
      expect(startDisabled(html)).toBe(false);
      expect(html).toContain("purchased run credit</p>");
      expect(html).not.toContain("No runs available");
    }
  });
  it("allows free runs without purchased credits", () => {
    expect(startDisabled(render({ usage: { ...usage, run_credits: 0 } }))).toBe(false);
  });
  it("blocks exhausted or reserved allowances without credits and links to Billing", () => {
    for (const introductory of [spent, { total: 2, used: 1, reserved: 1, remaining: 0 }, null]) {
      const html = render({ usage: { ...usage, introductory, run_credits: 0 } });
      expect(startDisabled(html)).toBe(true);
      expect(html).toContain("No runs available");
      expect(html).toContain('href="/billing">Buy run credits in Billing');
    }
  });
  it("shows reservations and allows credits when the free allowance is absent", () => {
    expect(render({ usage: { ...usage, introductory: { total: 2, used: 0, reserved: 2, remaining: 0 } } }))
      .toContain("(2 reserved)");
    expect(startDisabled(render({ usage: { ...usage, introductory: null } }))).toBe(false);
  });
  it("allows local execution without an allowance or purchased credits", () => {
    const html = render({ usage: { enforced: false, introductory: null, run_credits: 0, billing_enabled: false } });
    expect(html).toContain("Local execution");
    expect(startDisabled(html)).toBe(false);
  });
  it("blocks submission while access is unknown, refreshing or busy", () => {
    for (const state of [{ usage: null }, { loading: true }, { usage: null, loading: true }]) {
      expect(startDisabled(render(state))).toBe(true);
    }
    const html = render({ busy: true });
    expect(html).toContain("Starting...");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>.*?Starting\.\.\.<\/button>/);
    expect(render({ error: "Access unavailable" })).toContain('role="alert"');
  });
  it("offers a pending retry even with no remaining allowance or unavailable usage", () => {
    for (const currentUsage of [{ ...usage, introductory: spent, run_credits: 0 }, null]) {
      const html = render({ usage: currentUsage, retryPending: true });
      expect(html).toContain("Retry pending request");
      expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>.*?Retry pending request<\/button>/);
      expect(html).not.toContain("No runs available");
    }
  });
});
