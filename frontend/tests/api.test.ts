import { afterEach, describe, expect, it, vi } from "vitest";
import { createRun, createSimulation, getHealth, getRunUsage, listRuns, listSimulations, RepoPilotApiError } from "@/lib/api";

describe("RepoPilot API client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends retry keys for real runs and keeps simulations out of billing routes", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await createRun({ issue: "Example" }, "retry-key");
    expect(fetchMock.mock.calls[0][1].headers["Idempotency-Key"]).toBe("retry-key");
    await createSimulation("simulation-key");
    expect(fetchMock.mock.calls[1][0]).toBe("http://localhost:8000/simulations");
    expect(fetchMock.mock.calls[1][1].body).toBe(JSON.stringify({ request_key: "simulation-key" }));
    await getRunUsage();
    await listSimulations();
    expect(fetchMock.mock.calls[2][0]).toBe("http://localhost:8000/usage");
    expect(fetchMock.mock.calls[3][0]).toBe("http://localhost:8000/simulations");
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
