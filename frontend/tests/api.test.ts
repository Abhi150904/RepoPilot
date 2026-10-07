import { afterEach, describe, expect, it, vi } from "vitest";
import { createRun, getHealth, RepoPilotApiError } from "@/lib/api";

describe("RepoPilot API client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
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
