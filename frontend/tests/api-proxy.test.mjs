import { afterEach, describe, expect, it, vi } from "vitest";
import config from "../next.config.mjs";

afterEach(() => vi.unstubAllEnvs());

describe("same-origin API proxy", () => {
  it("keeps local development unchanged without a proxy origin", async () => {
    vi.stubEnv("REPOPILOT_API_ORIGIN", "");
    expect(await config.rewrites()).toEqual([]);
  });

  it("forwards the API prefix to the configured HTTPS backend", async () => {
    vi.stubEnv("REPOPILOT_API_ORIGIN", "https://repopilot.duckdns.org");
    expect(await config.rewrites()).toEqual([
      { source: "/api/:path*", destination: "https://repopilot.duckdns.org/:path*" }
    ]);
  });

  it.each(["http://backend.example", "https://user:secret@backend.example", "https://backend.example/path"])(
    "rejects an unsafe or ambiguous origin: %s", async (origin) => {
      vi.stubEnv("REPOPILOT_API_ORIGIN", origin);
      await expect(config.rewrites()).rejects.toThrow("HTTPS origin");
    }
  );
});
