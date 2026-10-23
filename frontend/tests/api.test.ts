import { afterEach, describe, expect, it, vi } from "vitest";
import { createRun, getBilling, getHealth, getRunUsage, listRuns, startSandboxCheckout, RepoPilotApiError } from "@/lib/api";

describe("RepoPilot API client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends retry keys for real runs and checkout", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await createRun({ issue: "Example" }, "retry-key");
    expect(fetchMock.mock.calls[0][1].headers["Idempotency-Key"]).toBe("retry-key");
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/runs");
    await startSandboxCheckout("checkout-key");
    expect(fetchMock.mock.calls[1][0]).toBe("http://localhost:8000/billing/checkout");
    expect(fetchMock.mock.calls[1][1].body).toBe(JSON.stringify({ request_key: "checkout-key" }));
  });

  it("reads current run allowance and purchased credit balances without caching", async () => {
    const usage = { enforced: true, introductory: null, run_credits: 3, billing_enabled: false };
    const billing = { enabled: false, environment: "sandbox", credit_balance: 3, pack_attempts: 5,
      test_price_cents: 500, currency: "usd", purchases: [], activity: [] };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(usage)))
      .mockResolvedValueOnce(new Response(JSON.stringify(billing)));
    vi.stubGlobal("fetch", fetchMock);
    expect(await getRunUsage()).toEqual(usage);
    expect(await getBilling()).toEqual(billing);
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/usage");
    expect(fetchMock.mock.calls[1][0]).toBe("http://localhost:8000/billing");
    for (const [, init] of fetchMock.mock.calls) expect(init.cache).toBe("no-store");
  });

  it("creates runs with JSON payloads", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          run_id: "run-1",
          lifecycle_status: "queued",
          request: { repository: "example/demo", issue_number: 1 },
          response: null,
          error: null
        }),
        { status: 202 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const run = await createRun({ repository: "example/demo", issue_number: 1 });

    expect(run.run_id).toBe("run-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/runs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ repository: "example/demo", issue_number: 1 }),
        headers: { "Content-Type": "application/json" }
      })
    );
  });

  it("surfaces API error responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "validation_error",
              message: "repository and issue_number must be provided together."
            }
          }),
          { status: 422 }
        )
      )
    );

    await expect(createRun({ repository: "example/demo" })).rejects.toMatchObject({
      code: "validation_error",
      message: "repository and issue_number must be provided together.",
      status: 422
    });
  });

  it("lists durable runs from the API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            run_id: "run-1",
            lifecycle_status: "completed",
            publication_status: "ready",
            request: { repository: "example/demo", issue_number: 1 },
            events: [],
            response: null,
            error: null
          }
        ]),
        { status: 200 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    const runs = await listRuns();

    expect(runs).toHaveLength(1);
    expect(runs[0].run_id).toBe("run-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/runs",
      expect.objectContaining({
        headers: {}
      })
    );
  });


  it("reports unreachable APIs consistently", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));

    await expect(getHealth()).rejects.toBeInstanceOf(RepoPilotApiError);
    await expect(getHealth()).rejects.toMatchObject({
      code: "api_unreachable",
      status: 0
    });
  });

  it("does not force JSON preflight headers for bodyless health checks", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", service: "repopilot" }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await getHealth();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/health",
      expect.objectContaining({
        headers: {}
      })
    );
  });
});
