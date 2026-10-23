import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BillingContent } from "@/components/billing-content";
import type { BillingStatus } from "@/lib/api";

const data: BillingStatus = { enabled: true, environment: "sandbox", credit_balance: 0, pack_attempts: 5,
  test_price_cents: 500, currency: "usd", purchases: [], activity: [] };

function render(overrides = {}) {
  vi.stubGlobal("React", React);
  return renderToStaticMarkup(React.createElement(BillingContent, { data, loading: false, signedOut: false, busy: false,
    error: null, notice: null, onRefresh: () => {}, onCheckout: () => {}, ...overrides }));
}

describe("sandbox billing", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("labels money as test-only and provides no balance-spending action", () => {
    const html = render();
    expect(html).toContain("Sandbox test payment. No real charge.");
    expect(html).toContain('aria-describedby="checkout-disclosure"');
    expect(html).toContain("One credit per AI run");
    expect(html).toContain("5 run credits");
    expect(html).toContain("$5.00");
    expect(html).not.toContain("Start AI run");
    expect(html).toContain('href="/app"');
  });
  it("does not expose checkout when unavailable or signed out", () => {
    expect(render({ data: { ...data, enabled: false } })).not.toContain("Buy credits");
    expect(render({ data: null, signedOut: true })).toContain("Sign in with GitHub");
  });
  it("shows billing errors", () => {
    const html = render({ error: "Request failed" });
    expect(html).toContain('role="alert"');
    expect(html).toContain("Request failed");
  });
  it("keeps balances and ledger visible when checkout is disabled", () => {
    const html = render({ data: { ...data, enabled: false, credit_balance: 3 } });
    expect(html).toContain("3 <span");
    expect(html).toContain("Payment history");
    expect(html).toContain("Credit activity");
    expect(html).toContain("Checkout is currently unavailable");
  });
  it("disables checkout while loading or submitting", () => {
    for (const state of [{ loading: true }, { busy: true }]) {
      expect(render(state)).toMatch(/disabled="" aria-describedby="checkout-disclosure"/);
    }
  });
  it("renders payment history with a stable timezone and singular credits", () => {
    const html = render({ data: { ...data, credit_balance: 1,
      purchases: [{ id: "paid", state: "paid", created_at: "2026-10-22T12:00:00Z" }],
      activity: [{ id: "spent", kind: "run", delta: -1, created_at: "2026-10-22T12:00:00Z" }] } });
    expect(html).toContain('dateTime="2026-10-22T12:00:00Z"');
    expect(html).toContain("UTC");
    expect(html).toContain("Payment history");
    expect(html).toContain("-1 credit");
    expect(html).not.toContain("-1 credits");
  });
  it("labels reservations, returned credits and historical usage readably", () => {
    const html = render({ data: { ...data, activity: ["run", "run_release", "simulation"].map((kind) => ({
      id: kind, kind, delta: kind === "run_release" ? 1 : -1, created_at: "2026-10-22T12:00:00Z",
    })) } });
    expect(html).toContain("AI run reservation");
    expect(html).toContain("Returned run credit");
    expect(html).toContain("Previous usage");
    expect(html).not.toContain(">simulation<");
  });
});
