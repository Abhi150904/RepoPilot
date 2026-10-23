import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunLauncherContent } from "@/components/run-launcher";
import type { RunUsage } from "@/lib/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const usage: RunUsage = { enforced: true, introductory: { total: 2, used: 0, reserved: 0, remaining: 2 },
  billing_enabled: true, simulation_credits: 4 };

function render(overrides = {}) {
  vi.stubGlobal("React", React);
  return renderToStaticMarkup(React.createElement(RunLauncherContent, { usage, mode: "ai", repository: "owner/repo",
    issueNumber: "1", busy: false, loading: false, error: null, result: null, simulations: [],
    onMode: () => {}, onRepository: () => {}, onIssueNumber: () => {}, onStart: () => {},
    onRefresh: () => {}, onSelect: () => {}, ...overrides }));
}

describe("Command Center run access", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("shows introductory allowance separately from simulation credits", () => {
    const html = render();
    expect(html).toContain("2 of 2");
    expect(html).toContain("free AI runs available");
    expect(html).toContain("simulation credits");
    expect(html).toContain("Start AI run");
    expect(html).toContain("Repository");
  });
  it("blocks AI after two runs even with purchased credits", () => {
    const html = render({ usage: { ...usage, introductory: { total: 2, used: 2, reserved: 0, remaining: 0 } } });
    expect(html).toMatch(/disabled=""[^>]*>.*?Start AI run/);
    expect(html).toContain("Sandbox credits fund simulations only");
  });
  it("keeps simulated execution explicit and does not require repository input", () => {
    const html = render({ mode: "simulation" });
    expect(html).toContain("1 credit per simulation");
    expect(html).toContain("No AI call, repository change, or test execution");
    expect(html).toContain("Start simulation");
    expect(html).not.toContain('placeholder="owner/repo"');
  });
  it("blocks spending when empty, unavailable or access has not loaded", () => {
    expect(render({ mode: "simulation", usage: { ...usage, simulation_credits: 0 } })).toMatch(/disabled=""[^>]*>.*?Start simulation/);
    expect(render({ mode: "simulation", usage: { ...usage, billing_enabled: false } })).toContain("Simulation checkout is currently unavailable");
    expect(render({ usage: null, loading: true })).toMatch(/disabled=""[^>]*>.*?Start AI run/);
  });
});
