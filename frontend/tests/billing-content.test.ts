import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BillingContent } from "@/components/billing-content";
import type { BillingStatus } from "@/lib/api";

const data: BillingStatus = { enabled: true, environment: "sandbox", demo_balance: 0, pack_attempts: 5,
  test_price_cents: 500, currency: "usd", purchases: [], activity: [] };

function render(overrides = {}) {
  vi.stubGlobal("React", React);
  return renderToStaticMarkup(React.createElement(BillingContent, { data, loading: false, signedOut: false, busy: null,
    error: null, notice: null, simulation: null, onRefresh: () => {}, onCheckout: () => {}, onSimulate: () => {}, ...overrides }));
}

describe("sandbox billing", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("labels money and output as test-only and disables spending an empty balance", () => {
    const html = render();
    expect(html).toContain("No real money");
    expect(html).toContain("$5.00");
    expect(html).toMatch(/disabled=""[^>]*>.*?Run simulation/);
  });
  it("does not expose checkout when unavailable or signed out", () => {
    expect(render({ data: { ...data, enabled: false } })).not.toContain("Open test checkout");
    expect(render({ data: null, signedOut: true })).toContain("Sign in with GitHub");
  });
  it("shows errors and the explicit simulated result", () => {
    const html = render({ error: "Request failed", simulation: { simulated: true, summary: "Example patch", patch: "+ sample", checks: [], demo_balance: 0 } });
    expect(html).toContain('role="alert"');
    expect(html).toContain("No AI call, repository change, or test execution.");
  });
});
