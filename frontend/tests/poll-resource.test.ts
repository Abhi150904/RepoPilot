import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RepoPilotApiError, type RunStatusResponse } from "@/lib/api";
import { pollResource, runNeedsRefresh } from "@/lib/poll-resource";

describe("resource polling", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("refreshes active runs and stops after completion", async () => {
    const run = (lifecycle_status: RunStatusResponse["lifecycle_status"]): RunStatusResponse => ({
      run_id: "run-1", request: {}, lifecycle_status
    });
    const load = vi.fn()
      .mockResolvedValueOnce(run("queued"))
      .mockResolvedValueOnce(run("running"))
      .mockResolvedValueOnce(run("completed"));
    const onData = vi.fn();
    const stop = pollResource({ load, onData, onError: vi.fn(), shouldPoll: runNeedsRefresh });
    expect(load).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(9000);
    expect(load).toHaveBeenCalledTimes(3);
    expect(onData).toHaveBeenLastCalledWith(run("completed"));
    stop();
  });

  it("waits for the previous request before scheduling another", async () => {
    let resolve!: (value: number) => void;
    const load = vi.fn(() => new Promise<number>((done) => { resolve = done; }));
    const stop = pollResource({ load, onData: vi.fn(), onError: vi.fn() });
    await vi.advanceTimersByTimeAsync(10000);
    expect(load).toHaveBeenCalledTimes(1);
    resolve(1);
    await vi.advanceTimersByTimeAsync(3000);
    expect(load).toHaveBeenCalledTimes(2);
    stop();
  });

  it("recovers after a temporary connection error", async () => {
    const error = new Error("offline");
    const load = vi.fn().mockRejectedValueOnce(error).mockResolvedValue(1);
    const onError = vi.fn();
    const onData = vi.fn();
    const stop = pollResource({ load, onData, onError });
    await vi.advanceTimersByTimeAsync(3000);
    expect(onError).toHaveBeenCalledWith(error);
    expect(onData).toHaveBeenCalledWith(1);
    stop();
  });

  it.each([401, 403, 404])("stops after HTTP %s", async (status) => {
    const load = vi.fn().mockRejectedValue(new RepoPilotApiError({ status, code: "unavailable", message: "Unavailable" }));
    const stop = pollResource({ load, onData: vi.fn(), onError: vi.fn() });
    await vi.advanceTimersByTimeAsync(10000);
    expect(load).toHaveBeenCalledTimes(1);
    stop();
  });

  it("aborts requests and ignores responses after leaving the page", async () => {
    let resolve!: (value: number) => void;
    const load = vi.fn((_signal: AbortSignal) => new Promise<number>((done) => { resolve = done; }));
    const onData = vi.fn();
    const stop = pollResource({ load, onData, onError: vi.fn() });
    stop();
    expect(load.mock.calls[0][0].aborted).toBe(true);
    resolve(1);
    await vi.advanceTimersByTimeAsync(10000);
    expect(onData).not.toHaveBeenCalled();
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("cancels scheduled refreshes on cleanup", async () => {
    const load = vi.fn().mockResolvedValue(1);
    const stop = pollResource({ load, onData: vi.fn(), onError: vi.fn() });
    await vi.advanceTimersByTimeAsync(0);
    stop();
    await vi.advanceTimersByTimeAsync(10000);
    expect(load).toHaveBeenCalledTimes(1);
  });

  it.each(["completed", "failed", "interrupted"] as const)("does not poll %s runs", (lifecycle_status) => {
    expect(runNeedsRefresh({ run_id: "run-1", request: {}, lifecycle_status })).toBe(false);
  });

  it("keeps refreshing while publication is in progress", () => {
    expect(runNeedsRefresh({ run_id: "run-1", request: {}, lifecycle_status: "completed", publication_status: "publishing" })).toBe(true);
  });
});
